from pathlib import Path
from threading import Event
import time
from unittest.mock import patch

from ae_editor.audio.core import AudioItem
from ae_editor.audio import playback
from ae_editor.audio.playback import AudioPreviewResult
from ae_editor.ui.audio_tab import AudioTabMixin


class _Status:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


class _Project:
    exe = Path("game.exe")


class _Harness(AudioTabMixin):
    def __init__(self) -> None:
        self.status = _Status()
        self.project = _Project()
        self.callbacks = []
        self.item = AudioItem(
            kind="soundcard-music",
            key="AE000:054",
            label="AE000:054",
            archive_name="AE000",
            resource_index=54,
            resource_type=0,
            sound_id=None,
            offset=None,
            length=3,
            data=b"abc",
        )

    def _selected_audio_item(self):
        return self.item

    def _audio_preview_speed(self) -> float:
        return 1.0

    def after(self, _delay, callback) -> None:
        self.callbacks.append(callback)


class _Task:
    def __init__(self, result) -> None:
        self.result = result
        self.cancelled = False

    def poll(self):
        return self.result

    def cancel(self):
        self.cancelled = True


def test_audio_preview_plays_from_ui_poll_after_worker_finishes():
    harness = _Harness()
    with (
        patch("ae_editor.ui.audio_tab.start_audio_preview_async", return_value=_Task((AudioPreviewResult("wav", Path("preview.wav")), None))),
        patch("ae_editor.ui.audio_tab.play_audio_file") as play,
    ):
        harness.play_selected_audio()
        assert harness.status.value == "Preparing audio preview for AE000:054..."
        assert not play.called
        harness.callbacks.pop(0)()

    play.assert_called_once_with(Path("preview.wav"))
    assert harness.status.value == "Playing synthesized preview for AE000:054"


def test_audio_preview_stop_discards_late_worker_result():
    harness = _Harness()
    with (
        patch("ae_editor.ui.audio_tab.start_audio_preview_async", return_value=_Task((AudioPreviewResult("wav", Path("preview.wav")), None))),
        patch("ae_editor.ui.audio_tab.play_audio_file") as play,
        patch("ae_editor.ui.audio_tab.stop_audio_playback"),
    ):
        harness.play_selected_audio()
        harness.stop_audio_preview()
        harness.callbacks.pop(0)()

    assert not play.called
    assert harness.status.value == "Audio preview stopped"


def test_audio_preview_reports_realtime_after_async_start_finishes():
    harness = _Harness()
    with patch(
        "ae_editor.ui.audio_tab.start_audio_preview_async",
        return_value=_Task((AudioPreviewResult("realtime"), None)),
    ):
        harness.play_selected_audio()
        assert harness.status.value == "Preparing audio preview for AE000:054..."
        harness.callbacks.pop(0)()

    assert harness.status.value == "Playing realtime preview for AE000:054"


def test_new_preview_and_stop_cancel_obsolete_cache_render():
    item = _Harness().item
    started = Event()
    cancelled = []

    def render(_item, **kwargs):
        started.set()
        while True:
            try:
                kwargs["cancel_check"]()
            except playback.PreviewCancelled:
                cancelled.append(True)
                raise
            time.sleep(0.005)

    with patch("ae_editor.audio.playback.temp_preview_wav", side_effect=render):
        playback.render_preview_async(item)
        assert started.wait(1.0)
        playback.render_preview_async(item)
        deadline = time.monotonic() + 1.0
        while len(cancelled) < 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        playback.stop_audio_playback()
        deadline = time.monotonic() + 1.0
        while len(cancelled) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)

    assert len(cancelled) == 2


def test_async_preview_realtime_start_does_not_cancel_its_own_task():
    item = _Harness().item
    with patch("ae_editor.audio.playback.play_audio_item_realtime", return_value=True):
        task = playback.start_audio_preview_async(item, exe_path=Path("game.exe"))
        deadline = time.monotonic() + 1.0
        result = None
        while time.monotonic() < deadline:
            result = task.poll()
            if result is not None:
                break
            time.sleep(0.005)
    assert result == (AudioPreviewResult("realtime"), None)
