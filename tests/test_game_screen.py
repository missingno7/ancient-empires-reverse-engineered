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
