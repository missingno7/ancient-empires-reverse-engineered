"""Flashlight laser: fire, beam, actor freeze, lever trip (AEPROG 0x5a3b)."""
from pathlib import Path

import pytest

from ancient_empires.engine import PlayerController, PlayerInput, PlayerState, RoomSimulation
from ancient_empires.engine.player import SFX_LASER, TOOL_BOOTS, TOOL_FLASHLIGHT
from ancient_empires.engine.room_simulation import (
    LASER_DIRECTION_STEPS,
    LASER_SUBSTEPS_PER_TICK,
    LASER_TTL,
    REFLECTOR_AUTO_TICKS,
)
from ancient_empires.constants import ROOM_COLUMNS, ROOM_ROWS


EXE = Path("game_data/AEPROG.EXE")
DATS = [Path("game_data/AE000.DAT"), Path("game_data/AE001.DAT")]
pytestmark = pytest.mark.game_data


def _controller(tool):
    controller = object.__new__(PlayerController)
    controller.state = PlayerState(x=80, y=32, tool=tool)
    controller.pending_sounds = []
    return controller


def test_flashlight_space_fires_laser_boots_does_not():
    tiles = [0] * (ROOM_COLUMNS * ROOM_ROWS)

    flash = _controller(TOOL_FLASHLIGHT)
    flash.tick(PlayerInput(use_tool=True), tiles)
    assert flash.state.fired_laser is True
    # The SFX is chosen by the caller from the fire result (0x14 fired / 0x17
    # cooldown), so player.tick only latches the intent.
    assert SFX_LASER not in flash.pending_sounds

    boots = _controller(TOOL_BOOTS)
    boots.tick(PlayerInput(use_tool=True), tiles)
    assert boots.state.fired_laser is False  # boots jumps, does not fire


def test_laser_stops_at_a_wall():
    from ancient_empires.project import AncientEmpiresProject

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[8], 0, 0)
    # Build a clear row with a wall and fire along it.
    assert sim.fire_laser(40, 60, 0) is True  # facing right
    assert sim.laser_ttl == LASER_TTL
    assert sim.fire_laser(40, 60, 0) is False  # DS:08FE cooldown/active flag

    # 0x5a3b only seeds the coordinate ring; 0x5ac3 grows the trail later.
    assert len(sim.laser_points) == 1
    sim.step()
    xs = [bx for bx, _ in sim.laser_points]
    assert xs == sorted(xs)  # monotonic to the right
    assert 1 < len(xs) <= LASER_SUBSTEPS_PER_TICK + 1
    # All beam points are on non-solid tiles (it stops before any wall).
    tiles = sim.runtime_tiles()
    for bx, by in sim.laser_points:
        col, row = bx // 8 - 1, by // 8 - 2
        if 0 <= col < ROOM_COLUMNS and 0 <= row < ROOM_ROWS:
            assert not tiles[row * ROOM_COLUMNS + col] & 0x07


def test_laser_freezes_only_actor_with_nonzero_freeze_byte_at_head():
    from ancient_empires.project import AncientEmpiresProject

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[0], 0, 0)
    assert sim.fire_laser(40, 60, 0) is True
    sim.step()
    actor = next(a for a in sim.actors.values() if a.room_index == 0 and a.active and a.delay > 0)
    bx, by = sim._laser_head_point()
    actor.x, actor.y = bx, by  # overlap the ASM DS:C04E head coordinate

    sim._laser_freeze_actors()
    assert actor.frozen == actor.delay  # byte 0x0A = byte 0x09

    # Frozen actors do not advance their script position.
    pc = actor.pc
    sim.laser_ttl = 0
    sim.laser_points = []
    sim.step()
    assert actor.pc == pc  # still frozen, script paused


def test_laser_does_not_freeze_projectile_records_with_zero_freeze_byte():
    from ancient_empires.project import AncientEmpiresProject

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[8], 0, 1)
    projectile = next(a for a in sim.actors.values() if a.name in {"Fireball", "Energy Orb"})
    projectile.activate()
    projectile.hidden = 0
    projectile.delay = 0

    assert sim.fire_laser(40, 60, 0) is True
    sim.step()
    bx, by = sim._laser_head_point()
    projectile.room_index = sim.room_index
    projectile.x, projectile.y = bx, by

    sim._laser_freeze_actors()
    assert projectile.frozen == 0


def test_laser_trips_a_lever():
    from ancient_empires.project import AncientEmpiresProject

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[1], 0, 0)
    lever = next(c for c in sim.controls() if c.command == 2)
    idx = lever.record.index
    before = sim.control_states[idx]

    # Fire from the left, along the lever's row, toward it.  The real laser is
    # not instant; tick until the moving trail reaches the command-2 lever.
    assert sim.fire_laser(lever.x_raw * 2 - 0x10 - 40, lever.y_raw - 4, 0) is True
    for _ in range(LASER_TTL):
        sim.step()
        if sim.control_states[idx] != before:
            break
    after = sim.control_states[idx]
    assert after != before

    # ASM 0x5c2f..0x5c67 sets one pending trigger and kills the travelling
    # head.  The historical trail must not keep toggling the same jello/lever
    # on following ticks.
    for _ in range(12):
        sim.step()
    assert sim.control_states[idx] == after


def test_reflected_laser_can_trip_jello_inside_current_solid_tile():
    from types import SimpleNamespace

    sim = object.__new__(RoomSimulation)
    sim.laser_ttl = LASER_TTL
    sim._laser_slots = [(80, 80)] * 24
    sim._laser_head = 23
    sim._laser_direction = 6
    sim._laser_phase = 0
    sim._laser_freeze_probe_points = []
    sim.laser_points = []
    sim._laser_triggered_controls = set()
    sim._laser_reflection_latch_entry = None
    sim._reflector_at_point = lambda x, y: None
    sim.controls = lambda: [SimpleNamespace(command=2, x_raw=40, y_raw=81, record=SimpleNamespace(index=0))]
    sim.control_states = {0: False}
    sim.toggle_control = lambda idx: sim.control_states.__setitem__(idx, not sim.control_states[idx])

    solid = [0] * (ROOM_COLUMNS * ROOM_ROWS)
    solid[(81 // 8 - 2) * ROOM_COLUMNS + (80 // 8 - 1)] = 0x07
    sim.runtime_tiles = lambda: solid

    sim._step_laser()

    assert sim.control_states[0] is True


def test_reflected_laser_can_trip_jello_before_boundary_solid_from_opposite_side():
    from types import SimpleNamespace

    sim = object.__new__(RoomSimulation)
    sim.laser_ttl = LASER_TTL
    sim._laser_slots = [(111, 83)] * 24
    sim._laser_head = 23
    sim._laser_direction = 9
    sim._laser_phase = 0
    sim._laser_freeze_probe_points = []
    sim.laser_points = []
    sim._laser_reflection_latch_entry = None
    sim._reflector_at_point = lambda x, y: None
    sim.controls = lambda: [SimpleNamespace(command=2, x_raw=48, y_raw=80, record=SimpleNamespace(index=0))]
    sim.control_states = {0: False}
    sim._laser_triggered_controls = set()
    sim.toggle_control = lambda idx: sim.control_states.__setitem__(idx, not sim.control_states[idx])
    solid = [0] * (ROOM_COLUMNS * ROOM_ROWS)
    solid[(83 // 8 - 2) * ROOM_COLUMNS + (110 // 8 - 1)] = 0x07
    sim.runtime_tiles = lambda: solid

    sim._step_laser()

    assert sim.control_states[0] is True


def test_laser_jello_probe_uses_exclusive_far_edges():
    from types import SimpleNamespace

    sim = object.__new__(RoomSimulation)
    sim.controls = lambda: [SimpleNamespace(command=2, x_raw=40, y_raw=80, record=SimpleNamespace(index=0))]
    sim.control_states = {0: False}
    sim._laser_triggered_controls = set()
    sim.toggle_control = lambda idx: sim.control_states.__setitem__(idx, not sim.control_states[idx])

    assert sim._laser_try_trigger_jello((40 + 8) * 2, 80 + 16) is False
    assert sim.control_states[0] is False


def test_laser_jello_probe_uses_asm_8_by_16_box():
    from types import SimpleNamespace

    sim = object.__new__(RoomSimulation)
    sim.controls = lambda: [SimpleNamespace(command=2, x_raw=40, y_raw=80, record=SimpleNamespace(index=0))]
    sim.control_states = {0: False}
    sim._laser_triggered_controls = set()
    sim.toggle_control = lambda idx: sim.control_states.__setitem__(idx, not sim.control_states[idx])

    assert sim._laser_try_trigger_jello((40 + 7) * 2, 80 + 15) is True
    sim.control_states[0] = False
    sim._laser_triggered_controls.clear()
    assert sim._laser_try_trigger_jello((40 + 8) * 2, 80 + 8) is False


def test_leftward_laser_jello_probe_uses_asm_raw_x_shift():
    from types import SimpleNamespace

    sim = object.__new__(RoomSimulation)
    sim.controls = lambda: [SimpleNamespace(command=2, x_raw=40, y_raw=80, record=SimpleNamespace(index=0))]
    sim.control_states = {0: False}
    sim._laser_triggered_controls = set()
    sim.toggle_control = lambda idx: sim.control_states.__setitem__(idx, not sim.control_states[idx])

    assert sim._laser_try_trigger_jello((40 + 8) * 2 - 1, 80) is True
    assert sim.control_states[0] is True


def test_laser_freeze_filter_uses_delay_not_actor_mode():
    from ancient_empires.project import AncientEmpiresProject

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[0], 0, 0)
    actor = next(a for a in sim.actors.values() if a.room_index == 0 and a.delay > 0)
    actor.deactivate()  # actor_type=1 records are still part of the draw/freeze pass in AEPROG
    actor.hidden = 0

    assert sim.fire_laser(40, 60, 0) is True
    sim.step()
    bx, by = sim._laser_head_point()
    actor.x, actor.y = bx, by

    sim._laser_freeze_actors()
    assert actor.frozen == actor.delay


def test_laser_reflectors_deflect_by_runtime_rotation():
    from ancient_empires.project import AncientEmpiresProject
    from ancient_empires.game_data.room_payload import laser_crystal_table

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[4], 0, 0)
    sim.runtime_tiles_cache = [0] * (ROOM_COLUMNS * ROOM_ROWS)
    entry = laser_crystal_table(sim.room).entries[0]
    # Fire a horizontal beam into an actual non-transparent triangular face
    # pixel from the current reflector sprite.  0x5f3c uses the raw section-C
    # anchor, not the editor top-left (which is cropped by -8,-16).
    target_x = entry.x_raw * 2 + 11
    target_y = entry.y + 4
    assert sim._laser_reflection_class(entry, target_x, target_y, sim.reflector_sprite_index(entry)) == 1

    # It should not behave like a rectangular mirror; 0x5f3c classifies the
    # touched sprite nibble and then 0x5cfd..0x5d40 rewrites the 12-way direction.
    assert sim.fire_laser(target_x - 53 - 0x10, target_y - 4, 0) is True
    before_dir = sim._laser_direction
    for _ in range(10):
        sim.step()
        if "reflect" in sim.reflector_events.get(entry.index, ""):
            break

    assert "reflect" in sim.reflector_events[entry.index]
    assert sim._laser_direction != before_dir
    assert sim.laser_points


def test_triggered_reflector_rotation_changes_deflection_angle():
    from ancient_empires.project import AncientEmpiresProject
    from ancient_empires.game_data.room_payload import laser_crystal_table

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[4], 0, 0)
    entry = laser_crystal_table(sim.room).entries[0]
    # Pick a raw in-sprite pixel that is reflective both before and after the
    # trigger rotates the frame.  The same world coordinate can then prove that
    # runtime orientation, not static art, controls the outgoing direction.
    frame0 = sim.reflector_sprite_index(entry)
    x = y = None
    for local_y in range(30):
        for local_x in range(30):
            wx = entry.x_raw * 2 + local_x
            wy = entry.y + local_y
            if (sim._laser_reflection_class(entry, wx, wy, frame0)
                    and sim._laser_reflection_class(entry, wx, wy, (frame0 + 1) % 24)):
                x, y = wx, wy
                break
        if x is not None:
            break
    assert x is not None and y is not None

    sim._laser_direction = 3
    sim._laser_phase = 0
    assert sim._laser_try_reflect(x, y) is True
    first = sim._laser_direction

    sim._laser_reflection_latch_entry = None
    sim._advance_reflector(entry.index, entry.code, reason="test")
    sim._laser_direction = 3
    assert sim._laser_try_reflect(x, y) is True
    second = sim._laser_direction

    assert first != second



def test_reflector_transparent_pixels_do_not_reflect():
    from ancient_empires.project import AncientEmpiresProject
    from ancient_empires.game_data.room_payload import laser_crystal_table

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[4], 0, 0)
    entry = laser_crystal_table(sim.room).entries[0]
    x = entry.x_raw * 2
    y = entry.y

    # Raw top-left is inside the 30x30 broad-phase rectangle but
    # transparent/background in the real triangular sprite mask, so 0x5f3c
    # returns 0 and no reflection is produced.
    sim._laser_direction = 3
    assert sim._reflector_at_point(x, y) == entry
    assert sim._laser_try_reflect(x, y) is False


def test_reflector_face_pixel_selects_asm_reflection_formula():
    from ancient_empires.project import AncientEmpiresProject
    from ancient_empires.game_data.room_payload import laser_crystal_table

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[4], 0, 0)
    entry = laser_crystal_table(sim.room).entries[0]
    frame = sim.reflector_sprite_index(entry)

    # Same reflector, same incoming direction, but different coloured pixels in
    # the triangular sprite select 0x5f3c classes 1 and 2.  The formulas are
    # frame-old_dir and frame-old_dir-8, normalized into the 12 direction rows.
    class1 = (entry.x_raw * 2 + 11, entry.y + 4)
    class2 = (entry.x_raw * 2 + 21, entry.y + 17)
    assert sim._laser_reflection_class(entry, *class1, frame) == 1
    assert sim._laser_reflection_class(entry, *class2, frame) == 2

    sim._laser_direction = 3
    sim._laser_reflection_latch_entry = None
    assert sim._laser_try_reflect(*class1) is True
    assert sim._laser_direction == (frame - 3) % 12

    sim._laser_direction = 3
    sim._laser_reflection_latch_entry = None
    assert sim._laser_try_reflect(*class2) is True
    assert sim._laser_direction == (frame - 3 - 8) % 12


def test_laser_direction_steps_match_asm_ds_0900_table():
    assert LASER_DIRECTION_STEPS == {
        0: [(0, 0), (0, -1), (0, -1), (0, -1), (0, -1), (0, -1)],
        1: [(0, -1), (1, -1), (1, -1), (0, -1), (1, -1), (1, -1)],
        2: [(0, -1), (1, -1), (1, 0), (1, -1), (1, 0), (1, -1)],
        3: [(1, 0)] * 6,
        4: [(1, 0), (1, 1), (1, 0), (1, 1), (1, 0), (1, 1)],
        5: [(1, 0), (1, 1), (1, 1), (0, 1), (1, 1), (1, 1)],
        6: [(0, 1)] * 6,
        7: [(0, 1), (-1, 1), (-1, 1), (0, 1), (-1, 1), (-1, 1)],
        8: [(0, 1), (-1, 1), (-1, 0), (-1, 1), (-1, 0), (-1, 1)],
        9: [(-1, 0)] * 6,
        10: [(-1, 0), (-1, -1), (-1, 0), (-1, -1), (-1, 0), (-1, -1)],
        11: [(-1, 0), (-1, -1), (-1, -1), (0, -1), (-1, -1), (-1, -1)],
    }


def test_reflected_laser_uses_corrected_asm_direction_row():
    from ancient_empires.project import AncientEmpiresProject
    from ancient_empires.game_data.room_payload import laser_crystal_table

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[4], 0, 0)
    entry = laser_crystal_table(sim.room).entries[0]
    frame = sim.reflector_sprite_index(entry)
    x = entry.x_raw * 2 + 11
    y = entry.y + 4
    assert sim._laser_reflection_class(entry, x, y, frame) == 1

    sim._laser_direction = 3
    sim._laser_phase = 0
    assert sim._laser_try_reflect(x, y) is True
    expected_direction = (frame - 3) % 12

    assert sim._laser_direction_step() == LASER_DIRECTION_STEPS[expected_direction][0]


def test_laser_can_reflect_from_multiple_reflectors():
    from types import SimpleNamespace

    sim = object.__new__(RoomSimulation)
    first = SimpleNamespace(index=0)
    second = SimpleNamespace(index=1)
    entries = {(1, 0): first, (2, 0): first, (3, 0): None, (4, 0): second}
    sim._reflector_at_point = lambda x, y: entries[(x, y)]
    sim.reflector_sprite_index = lambda entry: 13 if entry.index == 0 else 8
    sim._laser_reflection_class = lambda entry, x, y, frame: 1
    sim._laser_direction = 3
    sim._laser_reflection_latch_entry = None
    sim.reflector_events = {}
    sim.pending_sound_ids = []

    assert sim._laser_try_reflect(1, 0) is True
    assert sim._laser_direction == (13 - 3) % 12
    assert sim._laser_try_reflect(2, 0) is False

    assert sim._laser_try_reflect(3, 0) is False
    old_direction = sim._laser_direction
    assert sim._laser_try_reflect(4, 0) is True
    assert sim._laser_direction == (8 - old_direction) % 12


def test_auto_reflectors_rotate_once_per_ten_non_laser_ticks():
    from ancient_empires.project import AncientEmpiresProject
    from ancient_empires.game_data.room_payload import laser_crystal_table

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[4], 0, 0)
    entry = next(e for e in laser_crystal_table(sim.room).entries if e.code & 0x80)
    start = sim.reflector_sprite_index(entry)

    for _ in range(REFLECTOR_AUTO_TICKS - 1):
        sim.step()
    assert sim.reflector_sprite_index(entry) == start
    sim.step()
    assert sim.reflector_sprite_index(entry) == (start + 1) % 24


def test_auto_reflector_counter_pauses_while_laser_active():
    from ancient_empires.project import AncientEmpiresProject
    from ancient_empires.game_data.room_payload import laser_crystal_table

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[4], 0, 0)
    entry = next(e for e in laser_crystal_table(sim.room).entries if e.code & 0x80)
    start = sim.reflector_sprite_index(entry)

    assert sim.fire_laser(20, 80, 0) is True
    for _ in range(REFLECTOR_AUTO_TICKS * 2):
        sim.step()
    assert sim.reflector_sprite_index(entry) == start

def test_laser_range_is_not_the_cooldown_counter():
    from ancient_empires.project import AncientEmpiresProject

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[4], 0, 0)
    sim.runtime_tiles_cache = [0] * (ROOM_COLUMNS * ROOM_ROWS)

    assert sim.fire_laser(20, 80, 0) is True
    for _ in range(LASER_TTL + 8):
        sim.step()
        if sim._laser_head_point() is None:
            break

    # DS:C0C0 is not a range TTL. It only starts counting down after SI becomes
    # zero, so a clear horizontal shot can travel farther than 0x18 ticks.
    assert sim._laser_head_point() is not None
    assert max(x for x, _ in sim.laser_points) > 20 + LASER_TTL * LASER_SUBSTEPS_PER_TICK


def test_reflector_frame_uses_low_five_bits_and_reverse_step():
    from types import SimpleNamespace

    sim = object.__new__(RoomSimulation)
    sim.reflector_frames = {0: 0x0D}
    sim.reflector_events = {}
    entry = SimpleNamespace(index=0, code=0x8D)  # auto flag + low-five frame 13
    reverse_entry = SimpleNamespace(index=1, code=0x52)  # reverse flag + frame 18

    assert sim.reflector_sprite_index(entry) == 0x0D
    sim._advance_reflector(entry.index, entry.code, reason="auto")
    assert sim.reflector_sprite_index(entry) == 0x0E

    sim.reflector_frames[1] = reverse_entry.code & 0x1F
    sim._advance_reflector(reverse_entry.index, reverse_entry.code, reason="button")
    assert sim.reflector_sprite_index(reverse_entry) == 0x11


def test_flashlight_does_not_fire_while_on_a_rope():
    tiles = [0] * (ROOM_COLUMNS * ROOM_ROWS)
    flash = _controller(TOOL_FLASHLIGHT)
    flash.state.on_ladder = 1  # AEPROG 0x4210: laser branch skipped while climbing
    flash.tick(PlayerInput(use_tool=True), tiles)
    assert flash.state.fired_laser is False
