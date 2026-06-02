from pathlib import Path
from unittest.mock import patch

from ae_editor.audio.core import AudioItem
from ae_editor.ui.simulation_tab import SimulationTabMixin


class _Task:
    def poll(self):
        return Path("effect.wav"), None


class _Harness(SimulationTabMixin):
    def __init__(self) -> None:
        self.callbacks = []
        self.sim_last_sound_status = ""
        self.item = AudioItem(
            kind="pc-speaker-sfx",
            key="sound-01",
            label="sound 01",
            archive_name="AE000",
            resource_index=65,
            resource_type=0,
            sound_id=1,
            offset=0,
            length=3,
            data=b"abc",
        )

    def _simulation_sound_items(self):
        return {1: self.item}

    def after(self, _delay, callback):
        self.callbacks.append(callback)


def test_simulation_effect_render_is_polled_outside_tick():
    harness = _Harness()
    with (
        patch("ae_editor.ui.simulation_tab.render_preview_async", return_value=_Task()),
        patch("ae_editor.ui.simulation_tab.play_audio_file") as play,
    ):
        harness._play_simulation_sound(1)
        assert harness.sim_last_sound_status == "play_sound 0x01: preparing"
        assert not play.called
        harness.callbacks.pop(0)()

    play.assert_called_once_with(Path("effect.wav"))


def test_simulation_uses_caf1_priority_for_same_tick_sound_burst():
    class _Sim:
        def drain_pending_sound_ids(self):
            return [7, 3, 5]

    harness = _Harness()
    played = []
    harness._play_simulation_sound = played.append
    harness._play_pending_simulation_sounds(_Sim())
    assert played == [3]


def test_simulation_does_not_restart_same_active_sound():
    harness = _Harness()
    harness._simulation_active_sound_id = 1
    harness._simulation_active_sound_until = __import__("time").monotonic() + 10
    assert harness._simulation_sound_is_blocked(1)
    assert harness._simulation_sound_is_blocked(2)
    assert not harness._simulation_sound_is_blocked(0)
