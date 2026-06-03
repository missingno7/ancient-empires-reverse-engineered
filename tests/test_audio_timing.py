from ancient_empires.audio.core import PC_SPEAKER_DIRECT_BASE_DIVISOR, _duration_ticks_from_game_code


def test_direct_pitch_base_matches_exe_ds_17fc_table_head():
    assert PC_SPEAKER_DIRECT_BASE_DIVISOR == 0x8E88


def test_high_bit_duration_code_keeps_full_base_duration():
    # ASM C9A4 tests AH bit 7 and jumps straight to storing BX, which still
    # contains base + bend. The low seven bits are not a literal tick count.
    assert _duration_ticks_from_game_code(0x81, 300) == 300
    assert _duration_ticks_from_game_code(0xA6, 300, 12) == 312


def test_regular_duration_code_still_uses_subdivision_and_dotted_flag():
    assert _duration_ticks_from_game_code(0x03, 300) == 37
    assert _duration_ticks_from_game_code(0x0B, 300) == 55


def test_caf1_sound_00_duration_matches_capture_note():
    from pathlib import Path

    from ancient_empires.audio.core import build_audio_atlas, pc_speaker_preview_duration_seconds
    from ancient_empires.project import AncientEmpiresProject

    root = Path(__file__).resolve().parents[1]
    project = AncientEmpiresProject(
        root / "game_data" / "AEPROG.EXE",
        [root / "game_data" / "AE000.DAT", root / "game_data" / "AE001.DAT"],
    )
    item = next(
        item
        for item in build_audio_atlas(project)
        if item.kind == "pc-speaker-sfx" and item.sound_id == 0x00
    )
    duration = pc_speaker_preview_duration_seconds(item.data, music=False, audio_kind=item.kind)
    assert abs(duration - 5.87266) < 0.01
