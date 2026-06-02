from pathlib import Path
from unittest.mock import patch

from ae_editor.audio.core import (
    _opl_note_index_register_writes,
    _soundcard_freq_to_note_index,
    synthesize_soundcard_music_wav,
)


def test_opl_note_index_writes_match_e48a_default_table_mapping():
    assert _opl_note_index_register_writes(0, 0, key_on=True) == [(0xA0, 0x57), (0xB0, 0x21)]
    assert _opl_note_index_register_writes(3, 12, key_on=True) == [(0xA3, 0x57), (0xB3, 0x25)]
    assert _opl_note_index_register_writes(8, 95, key_on=True) == [(0xA8, 0x87), (0xB8, 0x3E)]


def test_soundcard_preview_frequency_round_trips_to_e48a_note_index():
    # Sound-card preview raw note index 40 maps to MIDI E4 (64).
    assert _soundcard_freq_to_note_index(329.6275569128699) == 40


def test_soundcard_wav_prefers_chip_emulator_and_retains_fallback():
    expected = Path("chip.wav")
    with patch("ae_editor.audio.core.synthesize_ym3812_wav", return_value=expected) as chip:
        assert synthesize_soundcard_music_wav(b"x", "game.exe", "out.wav") == expected
        chip.assert_called_once()

    with (
        patch("ae_editor.audio.core.synthesize_ym3812_wav", side_effect=RuntimeError("unavailable")),
        patch("ae_editor.audio.core.synthesize_adlib_like_wav", return_value=expected) as fallback,
    ):
        assert synthesize_soundcard_music_wav(b"x", "game.exe", "out.wav") == expected
        fallback.assert_called_once()
