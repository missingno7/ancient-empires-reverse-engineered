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
    # Pixel-exact guard for the default room-0 render.  Update this hash only
    # when an intentional render change lands (HUD energy bar, player draw
    # anchor, animated decals, etc.).
    assert hashlib.sha256(image.tobytes()).hexdigest() == (
        "07a3f00a272bf17c336fec2199f82a94d7c377bf51cf29df7f8dc0c92ca12b49"
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


def test_hud_energy_bar_width_tracks_energy():
    """The HUD energy gauge (AEPROG 0x738a) fills width = energy*16 at (244,164)."""
    from ancient_empires.rendering.game_screen import GameHudState

    project = AncientEmpiresProject(EXE, DATS)
    renderer = GameScreenRenderer(project.graphics, project.renderer)

    def green_pixels(energy):
        img = renderer.render(project.levels[0], hud=GameHudState(energy=energy)).convert("RGBA")
        return sum(
            1
            for x in range(244, 308)
            for y in range(164, 174)
            if img.getpixel((x, y)) == (0, 200, 0, 255)
        )

    assert green_pixels(0) == 0
    assert green_pixels(2) == 2 * 16 * 10
    assert green_pixels(4) == 4 * 16 * 10


def test_apple_pickup_render_suppressed_when_collected():
    from ancient_empires.game_data.room_payload import part_apple_marker

    project = AncientEmpiresProject(EXE, DATS)
    renderer = GameScreenRenderer(project.graphics, project.renderer)
    apple_room = next(ri for ri in range(10) if part_apple_marker(project.levels[0].part(0), ri))
    visible = renderer.render(project.levels[0], room_index=apple_room, apple_collected=False).tobytes()
    eaten = renderer.render(project.levels[0], room_index=apple_room, apple_collected=True).tobytes()
    assert visible != eaten


def _make_game_window():
    """Create a hidden GameWindow, or skip if Tk has no display."""
    import pytest
    tkinter = pytest.importorskip("tkinter")
    from ae_game.app.main_window import GameWindow

    project = AncientEmpiresProject(EXE, DATS)
    try:
        window = GameWindow(project, scale=1)
    except tkinter.TclError as exc:  # headless CI
        pytest.skip(f"Tk unavailable: {exc}")
    window.root.withdraw()
    return window


def test_enemy_contact_damages_player_with_mercy_window_and_god_mode():
    from ae_game.app.main_window import HURT_INVULN_TICKS

    window = _make_game_window()
    try:
        actors = [a for a in window.simulation.actors.values() if a.room_index == window.room_index]
        if not actors:
            import pytest

            pytest.skip("no actor in starting room to test contact")
        actor = actors[0]
        actor.actor_type = 0
        actor.hidden = 0
        window.player.state.x, window.player.state.y = actor.x, actor.y

        window.player.state.energy = 4
        window._apply_enemy_contact()
        assert window.player.state.energy == 3
        assert window._hurt_cooldown == HURT_INVULN_TICKS

        # Mercy window: no further damage until it expires.
        window._apply_enemy_contact()
        assert window.player.state.energy == 3

        # God mode blocks damage entirely.
        window._hurt_cooldown = 0
        window.god_mode = True
        window._apply_enemy_contact()
        assert window.player.state.energy == 3
    finally:
        window._on_close()


def test_apple_pickup_restores_full_energy_once():
    from ancient_empires.game_data.room_payload import part_apple_marker

    window = _make_game_window()
    try:
        room = next(ri for ri in range(10) if part_apple_marker(window.project.levels[0].part(0), ri))
        window.room_index = room
        window.simulation = window._room_simulation(room)
        marker = part_apple_marker(window.simulation.part, room)
        # Stand on the apple; _tick syncs the sim's player position before pickup.
        window.player.state.x, window.player.state.y = marker.x_raw * 2, marker.y_raw
        window.simulation.set_player_position(window.player.state.x, window.player.state.y)
        window.player.state.energy = 1

        window._collect_apple()
        assert window.player.state.energy == 4
        assert window._apple_collected()

        # Eating once removes it; a second pass does not heal again.
        window.player.state.energy = 2
        window._collect_apple()
        assert window.player.state.energy == 2
    finally:
        window._on_close()


def test_player_draw_state_hurt_then_blink_then_normal():
    from ae_game.app.main_window import (
        HURT_INVULN_TICKS,
        HURT_ANIM_THRESHOLD,
        HURT_FRAME,
    )

    window = _make_game_window()
    try:
        # Drive the hurt window the way _tick does: advance, then read draw state.
        window._hurt_cooldown = HURT_INVULN_TICKS
        window._invuln_timer = 0
        modes = []
        for _ in range(HURT_INVULN_TICKS):
            window._advance_invuln_timers()
            modes.append(window._player_draw_state())
        # First ticks (timer > 0x1a) show the hurt frame.
        assert modes[0] == (HURT_FRAME, False, False)
        assert modes[2] == (HURT_FRAME, False, False)
        # Then it alternates blink-off / shown until the window ends.
        blink_phase = modes[HURT_INVULN_TICKS - HURT_ANIM_THRESHOLD:]
        assert any(b for (_, b, _) in blink_phase)
        assert any(not b for (_, b, _) in blink_phase)
        # Window over -> normal draw.
        window._hurt_cooldown = 0
        assert window._player_draw_state() == (None, False, False)
    finally:
        window._on_close()


def test_immortality_tool_spends_uses_and_grants_halo():
    from ae_game.app.main_window import IMMORTALITY_TICKS, IMMORTALITY_USES
    from ancient_empires.engine.player import TOOL_IMMORTALITY

    window = _make_game_window()
    try:
        window.player.state.tool = TOOL_IMMORTALITY
        window.immortality_uses = IMMORTALITY_USES
        window._invuln_timer = 0

        window._activate_immortality()
        assert window.immortality_uses == IMMORTALITY_USES - 1
        assert window._invuln_timer == IMMORTALITY_TICKS
        assert window._player_draw_state() == (None, False, True)  # halo

        # Cannot re-activate while still invulnerable.
        window._activate_immortality()
        assert window.immortality_uses == IMMORTALITY_USES - 1

        # Spend the rest; never goes negative.
        for _ in range(10):
            window._invuln_timer = 0
            window._activate_immortality()
        assert window.immortality_uses == 0

        # Immortality blocks enemy damage.
        actors = [a for a in window.simulation.actors.values() if a.room_index == window.room_index]
        if actors:
            a = actors[0]
            a.actor_type = 0
            a.hidden = 0
            window.player.state.x, window.player.state.y = a.x, a.y
            window.player.state.energy = 4
            window._invuln_timer = IMMORTALITY_TICKS
            window._hurt_cooldown = 0
            window.god_mode = False
            window._apply_enemy_contact()
            assert window.player.state.energy == 4
    finally:
        window._on_close()


def test_laser_plays_fire_sound_then_cooldown_click():
    from ae_game.app.main_window import SFX_LASER, SFX_LASER_BLOCKED
    from ancient_empires.engine.player import TOOL_FLASHLIGHT

    window = _make_game_window()
    try:
        played = []
        window.audio.play_sfx = lambda sid: played.append(sid)
        window.player.state.tool = TOOL_FLASHLIGHT

        window._keys = {"space"}
        window._tick()           # press: a beam fires
        window._keys = set()
        window._tick()           # release so the tool re-arms
        window._keys = {"space"}
        window._tick()           # press again while the laser is still cooling down

        assert SFX_LASER in played          # an actual beam
        assert SFX_LASER_BLOCKED in played  # the cooldown click, no new beam
    finally:
        window._on_close()


def test_pickup_box_is_shared_asm_query_for_artifacts_and_apples():
    """Artifacts and apples register the same 8x16 raw-x box (AEPROG 0x2e7d /
    0x2ede) tested against the one player query box (0x3b05)."""
    from ancient_empires.engine import RoomSimulation

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[0], 0, 0)
    # Player query box is x = px//2+1 .. +14, y = py+1 .. +39 (raw-x space).
    sim.set_player_position(40, 40)
    obj_x, obj_y = 21, 41  # inside the query box -> overlaps
    assert sim.player_pickup_overlaps(obj_x, obj_y)
    # An object far outside the query box does not overlap (range, not whole room).
    assert not sim.player_pickup_overlaps(obj_x + 30, obj_y)
    assert not sim.player_pickup_overlaps(obj_x, obj_y + 60)


def test_player_face_boxes_are_tight_per_frame():
    from ancient_empires.engine.player import load_player_face_boxes, player_face_box

    boxes = load_player_face_boxes(EXE)
    assert len(boxes) == 24  # 12 frames x 2 facings
    xn, yn, xf, yf = player_face_box(boxes, 0, 0)
    # Much tighter than the 32x40 sprite / the old 39x47 contact box.
    assert (xf - xn) < 20 and (yf - yn) < 40
    # Facing flips the box within the sprite width.
    assert player_face_box(boxes, 0, 1) != (xn, yn, xf, yf)


def test_enemy_contact_uses_tight_face_boxes_not_whole_sprite():
    window = _make_game_window()
    try:
        actors = [a for a in window.simulation.actors.values() if a.room_index == window.room_index]
        if not actors:
            import pytest

            pytest.skip("no actor in starting room")
        actor = actors[0]
        actor.actor_type = 0
        actor.hidden = 0

        # Overlapping the actor hurts.
        window.player.state.frame = 0
        window.player.state.facing = 0
        window.player.state.x, window.player.state.y = actor.x, actor.y
        window.player.state.energy = 4
        window._hurt_cooldown = 0
        window._invuln_timer = 0
        window._apply_enemy_contact()
        assert window.player.state.energy == 3

        # Standing well clear of the actor's sprite does NOT hurt (the old whole
        # sprite box would have).
        window.player.state.energy = 4
        window._hurt_cooldown = 0
        window.player.state.x = actor.x + 48
        window._apply_enemy_contact()
        assert window.player.state.energy == 4
    finally:
        window._on_close()


def test_animated_decor_renders_on_top_of_static_decor():
    """L1 Explorer room 4 has a statue (static decor) with animated eyes; the
    eyes (AEPROG 0xd818) draw after the static decor (0x2d3e), so the render
    visibly changes across animation phases instead of being hidden."""
    from ancient_empires.rendering.room_renderer import RenderOptions
    from ancient_empires.game_data.room_payload import animated_decor_table

    project = AncientEmpiresProject(EXE, DATS)
    room = project.levels[0].part(0).room(4)
    assert animated_decor_table(room) is not None  # the statue eyes record

    def frame(phase):
        return project.renderer.render_room(
            project.levels[0], 4,
            RenderOptions(mode="game", zoom=1, part_index=0, animated_decor_phase=phase),
        ).tobytes()

    frames = {frame(p) for p in range(4)}
    assert len(frames) > 1  # the eyes animate on top of the statue


def test_level_naming_is_shared_between_game_and_editor():
    from ancient_empires.constants import level_display_name, hud_indices_for_level

    assert level_display_name(0) == "Near East I"
    assert level_display_name(4) == "Egypt I"
    assert level_display_name(19) == "Ancient World IV"
    assert hud_indices_for_level(5) == (1, 1)
    # Game and editor import the same helpers (no divergent copies).
    from ae_game.app.main_window import level_display_name as game_name
    from ae_editor.ui.common import level_display_name as editor_name
    assert game_name is editor_name is level_display_name


def test_artifact_puzzle_registers_rapid_key_taps():
    """The cursor puzzle handles keys on the event (not sampled per ~100ms
    tick), so quick taps pressed-and-released between ticks are not dropped."""
    from types import SimpleNamespace
    from ancient_empires.engine.artifact_puzzle import ArtifactPuzzleState

    window = _make_game_window()
    try:
        window.artifact_puzzle = ArtifactPuzzleState(level_index=0, expert=False)
        start_col = window.artifact_puzzle.cursor_col
        # Five fast taps with no tick in between (the old sampler lost these).
        for _ in range(5):
            window._on_key_press(SimpleNamespace(keysym="Right"))
            window._on_key_release(SimpleNamespace(keysym="Right"))
        assert window.artifact_puzzle is not None
        moved = (window.artifact_puzzle.cursor_col - start_col) % 6
        assert moved == 5  # every tap registered
    finally:
        window._on_close()
