from pathlib import Path

import pytest

from ancient_empires.project import AncientEmpiresProject

EXE = Path("game_data/AEPROG.EXE")
DATS = [Path("game_data/AE000.DAT"), Path("game_data/AE001.DAT")]


def _engine():
    pytest.importorskip("numpy")
    pytest.importorskip("sounddevice")
    from ae_game.app.audio_engine import GameAudioEngine

    project = AncientEmpiresProject(EXE, DATS)
    return GameAudioEngine(project)


def test_level_music_mapping_matches_asm_per_region_pairs():
    from ae_game.app.audio_engine import level_music_base_index

    # AEPROG 0x4874 with stage G = 2*level: each region has a pair of tracks,
    # the final region samples one track per earlier region.
    assert [level_music_base_index(L) for L in range(8)] == [115, 117, 115, 117, 119, 121, 119, 121]
    assert level_music_base_index(12) == 127
    assert [level_music_base_index(L) for L in (16, 17, 18, 19)] == [115, 119, 123, 127]


def test_audio_engine_indexes_sfx_and_music():
    engine = _engine()
    try:
        assert {0, 1, 2, 8, 12} <= set(engine._sfx_items)
        # PC-speaker and sound-card halves of the first level pair are present.
        assert ("AE001.DAT", 115) in engine._music_by_index
        assert ("AE001.DAT", 116) in engine._music_by_index
    finally:
        engine.shutdown()


def test_audio_engine_renders_both_music_halves():
    engine = _engine()
    try:
        pc = engine._render_music_item(engine._music_by_index[("AE001.DAT", 115)])
        sc = engine._render_music_item(engine._music_by_index[("AE001.DAT", 116)])
        assert pc is not None and len(pc) > 0
        assert sc is not None and len(sc) > 0  # OPL rendered + resampled
    finally:
        engine.shutdown()


def test_audio_engine_music_mode_switch():
    engine = _engine()
    try:
        assert engine.music_mode() == "soundcard"
        engine.set_music_mode("pcspeaker")
        assert engine.music_mode() == "pcspeaker"
        engine.set_music_mode("soundcard")
        assert engine.music_mode() == "soundcard"
    finally:
        engine.shutdown()


def test_audio_engine_toggles_are_no_op_safe():
    engine = _engine()
    try:
        engine.set_sound_enabled(False)
        engine.set_music_enabled(False)
        engine.play_sfx(12)
        assert engine._active_sfx == []
        engine.set_sound_enabled(True)
    finally:
        engine.shutdown()
