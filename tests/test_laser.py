"""Flashlight laser: fire, beam, actor freeze, lever trip (AEPROG 0x5a3b)."""
from pathlib import Path

from ancient_empires.engine import PlayerController, PlayerInput, PlayerState, RoomSimulation
from ancient_empires.engine.player import SFX_LASER, TOOL_BOOTS, TOOL_FLASHLIGHT
from ancient_empires.engine.room_simulation import LASER_FREEZE_TICKS, LASER_SUBSTEPS_PER_TICK, LASER_TTL
from ancient_empires.constants import ROOM_COLUMNS, ROOM_ROWS


EXE = Path("game_data/AEPROG.EXE")
DATS = [Path("game_data/AE000.DAT"), Path("game_data/AE001.DAT")]


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
    assert SFX_LASER in flash.pending_sounds

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


def test_laser_freezes_an_actor_on_the_beam():
    from ancient_empires.project import AncientEmpiresProject

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[8], 0, 0)
    assert sim.fire_laser(40, 60, 0) is True
    sim.step()
    actor = next(a for a in sim.actors.values() if a.room_index == 0 and a.active)
    bx, by = sim.laser_points[len(sim.laser_points) // 2]
    actor.x, actor.y = bx, by  # stand the actor in the moving trail

    sim.step()
    assert actor.frozen == LASER_FREEZE_TICKS - 1  # frozen, counting down

    # Frozen actors do not advance their script position.
    pc = actor.pc
    sim.laser_ttl = 0
    sim.laser_points = []
    sim.step()
    assert actor.pc == pc  # still frozen, script paused


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
    assert sim.control_states[idx] != before
