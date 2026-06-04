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


def test_live_spider_draws_one_pixel_white_thread_from_actor_marker():
    from ancient_empires.engine import RoomSimulation
    from ancient_empires.rendering.coordinates import actor_xy
    from ancient_empires.rendering.game_screen import ROOM_ORIGIN

    project = AncientEmpiresProject(EXE, DATS)
    renderer = GameScreenRenderer(project.graphics, project.renderer)
    sim = RoomSimulation(project.levels[0], 0, 2)
    spider = next(actor for actor in sim.actors.values() if actor.name == "Spider" and actor.room_index == 2)

    # The thread is anchored at the spawn y, so it only appears once the spider
    # has descended below it.
    spider.y += 32
    image = renderer.render(project.levels[0], room_index=2, simulation=sim, actors=sim.actors.values())
    rx, ry = actor_xy(spider.x, spider.y)
    x = ROOM_ORIGIN[0] + rx + 16
    top = ROOM_ORIGIN[1] + ry - spider.vertical_marker + 1

    assert image.getpixel((x, top)) == (255, 255, 255, 255)
    assert image.getpixel((x - 1, top)) != (255, 255, 255, 255)

    spider.thread_anchor_y = None
    without_thread = renderer.render(project.levels[0], room_index=2, simulation=sim, actors=sim.actors.values())
    assert without_thread.getpixel((x, top)) != (255, 255, 255, 255)


def test_spider_thread_stretches_from_fixed_anchor_as_it_descends():
    """The thread is pinned to the spawn position; descending the spider
    lengthens it instead of dragging a fixed segment under it."""
    from ancient_empires.engine import RoomSimulation

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[0], 0, 2)
    spider = next(a for a in sim.actors.values() if a.name == "Spider" and a.room_index == 2)

    anchor = spider.thread_anchor_y
    assert anchor is not None
    assert spider.vertical_marker == spider.y - anchor

    spider.y += 40
    # Anchor stays put, so the thread grows by exactly the descent.
    assert spider.vertical_marker == spider.y - anchor

    # Back at (or above) the anchor there is no thread.
    spider.y = anchor
    assert spider.vertical_marker == 0


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


def test_exit_door_frame_override_animates_themed_door():
    from ancient_empires.game_data.room_payload import header_exit_door

    project = AncientEmpiresProject(EXE, DATS)
    renderer = GameScreenRenderer(project.graphics, project.renderer)
    door = header_exit_door(project.levels[0].parts[0].header)

    assert door is not None
    closed = renderer.render(project.levels[0], room_index=door.room_index, exit_door_frame=0).tobytes()
    open_door = renderer.render(project.levels[0], room_index=door.room_index, exit_door_frame=4).tobytes()

    assert closed != open_door


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


def test_animated_background_decor_advances_with_phase():
    """Animated decals cycle their sprite sequence as the phase advances
    (previously they were frozen on the stored preview frame)."""
    from ancient_empires.rendering.room_renderer import RenderOptions

    project = AncientEmpiresProject(EXE, DATS)
    renderer = project.renderer
    # L8 room 8 has visible animated decals (not covered by terrain).
    frames = {
        renderer.render_room(
            project.levels[8],
            8,
            RenderOptions(mode="game", zoom=1, part_index=0, draw_actors=False, animated_decor_phase=phase),
        ).tobytes()
        for phase in range(8)
    }
    assert len(frames) > 1


def test_game_render_omits_editor_only_puzzle_ghost():
    """The faint alternate-position 'ghost' of a green block is an editor aid
    and must not appear in the live game view."""
    from ancient_empires.rendering.room_renderer import RenderOptions

    project = AncientEmpiresProject(EXE, DATS)
    renderer = project.renderer
    base = dict(mode="game", zoom=1, part_index=0, draw_actors=False)
    with_ghost = renderer.render_room(project.levels[8], 0, RenderOptions(**base, draw_puzzle_ghost=True)).tobytes()
    without_ghost = renderer.render_room(project.levels[8], 0, RenderOptions(**base, draw_puzzle_ghost=False)).tobytes()
    assert with_ghost != without_ghost


def test_green_block_footprint_matches_asm_formula():
    """Green-block collision is the 6x2 region at col=raw_x//4-1, row=raw_y//8-1
    (AEPROG 0x3132), not the old geometric heuristic."""
    from ancient_empires.engine import RoomSimulation
    from ancient_empires.engine.room_simulation import _green_block_footprint_cells

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[8], 0, 1)
    block = sim.green_blocks[0]
    rx, ry = block.raw[0], block.raw[1]
    col, row = rx // 4 - 1, ry // 8 - 1
    expected = {(col + dx, row + dy) for dy in range(2) for dx in range(6)}
    assert _green_block_footprint_cells(block, alternate=False) == expected


def test_green_block_teleport_leaves_no_stale_invisible_wall():
    """Moving a block to its alternate position must clear the invisible-solid
    tiles at the default position (and vice versa)."""
    from ancient_empires.engine import RoomSimulation
    from ancient_empires.engine.room_simulation import _green_block_footprint_cells
    from ancient_empires.constants import ROOM_COLUMNS

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[8], 0, 1)
    block = sim.green_blocks[0]
    default_cells = _green_block_footprint_cells(block, alternate=False)

    block.at_alternate = True
    sim._invalidate_runtime_tiles()
    tiles = sim.runtime_tiles()
    alt_cells = _green_block_footprint_cells(block, alternate=True)
    # Default position no longer solid; alternate position now solid.
    assert all(tiles[y * ROOM_COLUMNS + x] != 0x07 for x, y in default_cells - alt_cells)
    assert all(tiles[y * ROOM_COLUMNS + x] == 0x07 for x, y in alt_cells)


def test_invisible_block_overlay_follows_runtime_tiles():
    """The show-invisible overlay reflects the live collision grid, so a moved
    green block (or platform) updates instead of staying on the stored terrain."""
    from ancient_empires.engine import RoomSimulation
    from ancient_empires.rendering.overlay import _invisible_clusters

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[8], 0, 0)
    before = _invisible_clusters(sim.room, sim.runtime_tiles())
    sim.green_blocks[0].at_alternate = True
    sim._invalidate_runtime_tiles()
    after = _invisible_clusters(sim.room, sim.runtime_tiles())
    assert before != after
