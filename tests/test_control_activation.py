"""Walk-onto-button activation through the simulation (AEPROG 0x3c50)."""
from pathlib import Path

from ancient_empires.project import AncientEmpiresProject
from ancient_empires.engine import RoomSimulation
from ancient_empires.game_data.room_payload import control_commands


EXE = Path("game_data/AEPROG.EXE")
DATS = [Path("game_data/AE000.DAT"), Path("game_data/AE001.DAT")]


def _sim_with_button():
    project = AncientEmpiresProject(EXE, DATS)
    # L0 room 1 carries floor buttons (command 1) and a ceiling button.
    sim = RoomSimulation(project.levels[0], 0, 1)
    button = next(c for c in control_commands(sim.part.room(1)) if c.command == 1)
    return sim, button


def test_walking_onto_button_toggles_it_once():
    sim, button = _sim_with_button()
    idx = button.record.index
    bx = button.x_raw * 2

    assert sim.control_states[idx] is False

    # Step onto the button: toggles on the rising edge.
    sim.set_player_position(bx, button.y_raw - 32)
    sim.apply_player_object_interaction()
    assert sim.control_states[idx] is True

    # Standing still does not retrigger (debounced on object-code change).
    sim.apply_player_object_interaction()
    assert sim.control_states[idx] is True


def test_leaving_and_returning_toggles_again():
    sim, button = _sim_with_button()
    idx = button.record.index
    bx = button.x_raw * 2

    sim.set_player_position(bx, button.y_raw - 32)
    sim.apply_player_object_interaction()
    assert sim.control_states[idx] is True

    # Walk well away (off every control), then back.
    sim.set_player_position(0, 0)
    sim.apply_player_object_interaction()
    sim.set_player_position(bx, button.y_raw - 32)
    sim.apply_player_object_interaction()
    assert sim.control_states[idx] is False


def test_ceiling_button_needs_reaching_up_not_walking_under():
    # L19 part0 room0 has command-0 ceiling buttons at y=104 (idx 3/4).
    project = AncientEmpiresProject(EXE, DATS)
    button = next(
        c
        for c in control_commands(project.levels[19].part(0).room(0))
        if c.command == 0 and c.y_raw == 104
    )
    idx = button.record.index
    bx = button.x_raw * 2

    # Walking under it (head/body below the button) must NOT trigger.
    sim = RoomSimulation(project.levels[19], 0, 0)
    sim.set_player_position(bx, 112)
    sim.apply_player_object_interaction()
    assert sim.control_states[idx] is False

    # Reaching up into it (head at the button) DOES trigger.
    sim = RoomSimulation(project.levels[19], 0, 0)
    sim.set_player_position(bx, button.y_raw - 8)
    sim.apply_player_object_interaction()
    assert sim.control_states[idx] is True


def test_platform_slides_gradually():
    from ancient_empires.engine.runtime import control_targets
    from ancient_empires.game_data.room_payload import parse_platform_triplets

    project = AncientEmpiresProject(EXE, DATS)
    sim = RoomSimulation(project.levels[0], 0, 1)
    cidx = next(
        c.record.index
        for c in sim.controls()
        if any(t.kind == "platform" for t in control_targets(c))
    )
    platform = next(p for p in parse_platform_triplets(sim.room) if p.visible)

    sim.toggle_control(cidx)
    assert sim.platform_render_offset(platform) == (0, 0)  # not yet moved

    sim.step()
    first = sim.platform_render_offset(platform)
    assert first != (0, 0) and max(abs(first[0]), abs(first[1])) <= 8  # one 8px step

    for _ in range(10):
        sim.step()
    settled = sim.platform_render_offset(platform)
    assert max(abs(settled[0]), abs(settled[1])) == 48  # reaches full travel
