from ae_editor.game_data.level_flip import (
    _mirror_visual_code,
    _rewrite_script_instruction,
    _toggle_packed_frame_variant,
    mirror_x_raw,
)


def test_horizontal_flip_toggles_actor_and_decor_facing_bits():
    assert _toggle_packed_frame_variant(0x05) == 0x85
    assert _toggle_packed_frame_variant(0x85) == 0x05

    assert _mirror_visual_code(0x12) == 0x52
    assert _mirror_visual_code(0x52) == 0x12


def test_horizontal_flip_swaps_player_x_gt_lt_conditions():
    original_x = 0x30
    gt = bytearray([0x17, original_x])
    lt = bytearray([0x18, original_x])

    assert _rewrite_script_instruction(gt, 0)
    assert gt[0] == 0x18
    assert gt[1] == mirror_x_raw(original_x)

    assert _rewrite_script_instruction(lt, 0)
    assert lt[0] == 0x17
    assert lt[1] == mirror_x_raw(original_x)
