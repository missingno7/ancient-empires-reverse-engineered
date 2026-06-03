from pathlib import Path
import hashlib

from ancient_empires.project import AncientEmpiresProject
from ancient_empires.rendering.game_screen import BACKGROUND_COLOR, GameScreenRenderer


EXE = Path("game_data/AEPROG.EXE")
DATS = [Path("game_data/AE000.DAT"), Path("game_data/AE001.DAT")]


def test_level_1_explorer_room_0_game_screen_regression():
    project = AncientEmpiresProject(EXE, DATS)
    image = GameScreenRenderer(project.graphics, project.renderer).render(project.levels[0])

    assert image.size == (320, 200)
    assert hashlib.sha256(image.tobytes()).hexdigest() == (
        "06edf140ef02ad6673e2616771305d8bda16f5ea37203995c3f290922ace784c"
    )


def test_screen_frame_uses_solid_blue_background():
    project = AncientEmpiresProject(EXE, DATS)
    image = GameScreenRenderer(project.graphics, project.renderer).render(project.levels[0])

    # The border outside the room viewport is the blue backdrop (index 137),
    # not black.
    assert image.getpixel((2, 2)) == BACKGROUND_COLOR
    assert image.getpixel((160, 8)) == BACKGROUND_COLOR


def test_toggling_a_platform_control_changes_the_render():
    from ancient_empires.engine import RoomSimulation
    from ancient_empires.engine.runtime import control_targets

    project = AncientEmpiresProject(EXE, DATS)
    renderer = GameScreenRenderer(project.graphics, project.renderer)

    # L0 room 1 has a control that targets a platform.
    sim = RoomSimulation(project.levels[0], 0, 1)
    cidx = next(
        c.record.index
        for c in sim.controls()
        if any(t.kind == "platform" for t in control_targets(c))
    )

    before = renderer.render(project.levels[0], room_index=1, simulation=sim).tobytes()
    sim.toggle_control(cidx)
    assert sim.active_target_indices("platform")  # platform now travelled
    after = renderer.render(project.levels[0], room_index=1, simulation=sim).tobytes()
    assert before != after  # pressed switch + moved platform are drawn


def test_platform_offset_override_is_render_only():
    from ancient_empires.engine import RoomSimulation
    from ancient_empires.game_data.room_payload import parse_platform_triplets

    project = AncientEmpiresProject(EXE, DATS)
    renderer = GameScreenRenderer(project.graphics, project.renderer)
    sim = RoomSimulation(project.levels[0], 0, 1)
    platform = next(p for p in parse_platform_triplets(sim.room) if p.visible)

    before_state = dict(sim.platform_offsets)
    baseline = renderer.render(project.levels[0], room_index=1, simulation=sim).tobytes()
    shifted = renderer.render(
        project.levels[0],
        room_index=1,
        simulation=sim,
        platform_offsets_override={platform.index: (8, 0)},
    ).tobytes()

    assert shifted != baseline
    assert sim.platform_offsets == before_state


def test_header_artifact_and_exit_door_render_options():
    from ancient_empires.game_data.room_payload import header_exit_door, header_object_candidates

    project = AncientEmpiresProject(EXE, DATS)
    renderer = GameScreenRenderer(project.graphics, project.renderer)
    part = project.levels[0].parts[0]
    artifact = header_object_candidates(part.header)[0]
    door = header_exit_door(part.header)

    artifact_room = artifact.room_plus_one - 1
    visible_artifact = renderer.render(project.levels[0], room_index=artifact_room).tobytes()
    collected_artifact = renderer.render(
        project.levels[0],
        room_index=artifact_room,
        collected_artifacts={artifact.index},
    ).tobytes()

    assert visible_artifact != collected_artifact
    assert door is not None

    visible_exit = renderer.render(project.levels[0], room_index=door.room_index).tobytes()
    hidden_exit = renderer.render(
        project.levels[0],
        room_index=door.room_index,
        show_exit_door=False,
    ).tobytes()

    assert visible_exit != hidden_exit


def test_hud_artifact_pieces_and_invulnerability_uses_change_the_render():
    from ancient_empires.rendering.game_screen import GameHudState

    project = AncientEmpiresProject(EXE, DATS)
    renderer = GameScreenRenderer(project.graphics, project.renderer)

    empty = renderer.render(project.levels[0], hud=GameHudState(artifact_pieces=0)).tobytes()
    collected = renderer.render(project.levels[0], hud=GameHudState(artifact_pieces=6)).tobytes()
    uses_empty = renderer.render(
        project.levels[0],
        hud=GameHudState(tool_index=2, invulnerability_uses=0),
    ).tobytes()
    uses_full = renderer.render(
        project.levels[0],
        hud=GameHudState(tool_index=2, invulnerability_uses=4),
    ).tobytes()

    assert empty != collected
    assert uses_empty != uses_full


def test_hud_indices_follow_asm_level_table():
    from ae_game.app.main_window import hud_indices_for_level, level_display_name

    assert hud_indices_for_level(0) == (0, 0)
    assert hud_indices_for_level(3) == (0, 3)
    assert hud_indices_for_level(4) == (1, 0)
    assert hud_indices_for_level(16) == (4, 0)
    assert hud_indices_for_level(19) == (4, 3)
    assert level_display_name(0) == "Near East I"
    assert level_display_name(7) == "Egypt IV"
    assert level_display_name(18) == "Ancient World III"


def test_green_block_moves_when_symbol_sequence_completes():
    from ancient_empires.engine import RoomSimulation

    project = AncientEmpiresProject(EXE, DATS)
    renderer = GameScreenRenderer(project.graphics, project.renderer)
    # L8 room 0 carries a green block with a symbol sequence.
    sim = RoomSimulation(project.levels[8], 0, 0)
    block = sim.green_blocks[0]

    before = renderer.render(project.levels[8], room_index=0, simulation=sim).tobytes()
    # Emitting one symbol consumes it from the drawn sequence (render changes).
    sim.emit_symbol(block.sequence[0])
    assert block.remaining_sequence == block.sequence[1:]
    partial = renderer.render(project.levels[8], room_index=0, simulation=sim).tobytes()
    assert before != partial  # a symbol disappeared from the block

    for symbol in block.remaining_sequence[:]:
        sim.emit_symbol(symbol)
    assert block.at_alternate  # sequence complete -> block swapped
    after = renderer.render(project.levels[8], room_index=0, simulation=sim).tobytes()
    assert partial != after  # block now drawn at its alternate position
