from pathlib import Path
from unittest.mock import patch

from ae_editor.audio.core import AudioItem
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


class _ImmediateThread:
    def __init__(self, *, target, **_kwargs) -> None:
        self.target = target

    def start(self) -> None:
        self.target()


def test_audio_preview_plays_from_ui_poll_after_worker_finishes():
    harness = _Harness()
    with (
        patch("ae_editor.ui.audio_tab.Thread", _ImmediateThread),
        patch("ae_editor.ui.audio_tab.temp_preview_wav", return_value=Path("preview.wav")),
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
        patch("ae_editor.ui.audio_tab.Thread", _ImmediateThread),
        patch("ae_editor.ui.audio_tab.temp_preview_wav", return_value=Path("preview.wav")),
        patch("ae_editor.ui.audio_tab.play_audio_file") as play,
        patch("ae_editor.ui.audio_tab.stop_audio_playback"),
    ):
        harness.play_selected_audio()
        harness.stop_audio_preview()
        harness.callbacks.pop(0)()

    assert not play.called
    assert harness.status.value == "Audio preview stopped"
