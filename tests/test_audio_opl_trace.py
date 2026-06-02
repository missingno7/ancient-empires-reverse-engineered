from pathlib import Path
from unittest.mock import patch

import numpy as np

from ae_editor.audio.core import (
    _apply_dosbox_opl_filter,
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


def test_soundcard_wav_uses_chip_emulator_only_with_no_fallback():
    # One correct path: the real YM3812 chip renderer.  There is no Python-FM or
    # square-wave fallback - a missing backend is a loud, explicit error, not a
    # quietly different sound.
    from ae_editor.audio.core import Ym3812Unavailable

    expected = Path("chip.wav")
    with patch("ae_editor.audio.core.synthesize_ym3812_wav", return_value=expected) as chip:
        assert synthesize_soundcard_music_wav(b"x", "game.exe", "out.wav") == expected
        chip.assert_called_once()

    with patch("ae_editor.audio.core.synthesize_ym3812_wav", side_effect=Ym3812Unavailable("no backend")):
        try:
            synthesize_soundcard_music_wav(b"x", "game.exe", "out.wav")
            assert False, "expected Ym3812Unavailable to propagate (no fallback)"
        except Ym3812Unavailable:
            pass


def test_dosbox_opl_filter_profiles_are_opt_in():
    pcm = np.array([0, 1000, -1000, 1000], dtype=np.int32)
    with patch.dict("os.environ", {"AE_OPL_FILTER_PROFILE": "off"}):
        assert np.array_equal(_apply_dosbox_opl_filter(pcm, 49716), pcm)
    with patch.dict("os.environ", {"AE_OPL_FILTER_PROFILE": "sbpro2"}):
        filtered = _apply_dosbox_opl_filter(pcm, 49716)
    assert filtered.tolist() != pcm.tolist()
    assert abs(filtered[1]) < abs(pcm[1])
