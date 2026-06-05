from pathlib import Path

import pytest

from ancient_empires.project import AncientEmpiresProject
from ancient_empires.rendering.map_screen import (
    ANCIENT_WORLD_LEVEL_INDEX,
    MAP_BACKGROUND_ORIGIN,
    MAP_CHOICES,
    MAP_ORIGIN,
    MapScreenRenderer,
)


EXE = Path("game_data/AEPROG.EXE")
DATS = [Path("game_data/AE000.DAT"), Path("game_data/AE001.DAT")]
pytestmark = pytest.mark.game_data


def test_map_screen_uses_recovered_map_icons_and_selector():
    project = AncientEmpiresProject(EXE, DATS)
    image = MapScreenRenderer(project.graphics).render(0)

    assert image.size == (320, 200)
    assert [choice.level_index for choice in MAP_CHOICES] == [0, 4, 8, 12]
    assert [choice.normal_resource_id for choice in MAP_CHOICES] == [29, 30, 31, 32]
    assert [choice.completed_resource_id for choice in MAP_CHOICES] == [33, 34, 35, 36]

    map_pixel = project.graphics.sprite("AE000", 28, 0).convert("RGBA").getpixel((1, 1))
    background_pixel = project.graphics.sprite("AE000", 26, 0).convert("RGBA").getpixel((40, 160))
    assert image.getpixel((MAP_BACKGROUND_ORIGIN[0] + 40, MAP_BACKGROUND_ORIGIN[1] + 160)) == background_pixel
    assert image.getpixel((MAP_ORIGIN[0] + 1, MAP_ORIGIN[1] + 1)) == map_pixel
    assert image.getpixel(MAP_CHOICES[0].icon_position)[:3] == (231, 0, 0)


def test_completed_region_uses_completed_icon_resource():
    project = AncientEmpiresProject(EXE, DATS)
    image = MapScreenRenderer(project.graphics).render(1, {1})
    egypt = MAP_CHOICES[1]
    completed_pixel = project.graphics.sprite("AE000", egypt.completed_resource_id, 0).convert("RGBA").getpixel((12, 20))

    assert image.getpixel((egypt.icon_position[0] + 12, egypt.icon_position[1] + 20)) == completed_pixel


def test_ancient_world_reveal_uses_recovered_ancient_world_resource():
    project = AncientEmpiresProject(EXE, DATS)
    image = MapScreenRenderer(project.graphics).render_ancient_reveal(24, 24)
    ancient_pixel = project.graphics.sprite("AE000", 26, 0).convert("RGBA").getpixel((40, 40))

    assert ANCIENT_WORLD_LEVEL_INDEX == 16
    assert image.getpixel((MAP_BACKGROUND_ORIGIN[0] + 40, MAP_BACKGROUND_ORIGIN[1] + 40)) == ancient_pixel


def test_map_background_has_12_pixel_top_and_bottom_margins():
    project = AncientEmpiresProject(EXE, DATS)
    image = MapScreenRenderer(project.graphics).render(0)

    assert MAP_BACKGROUND_ORIGIN == (0, 12)
    assert MAP_ORIGIN == (5, 15)
    assert image.getpixel((10, 6))[:3] == (0, 0, 0)
    assert image.getpixel((10, 193))[:3] == (0, 0, 0)
    assert image.getpixel((10, 12))[:3] != (0, 0, 0)
    assert image.getpixel((10, 187))[:3] != (0, 0, 0)


def test_level_enter_transition_reaches_black_screen():
    project = AncientEmpiresProject(EXE, DATS)
    renderer = MapScreenRenderer(project.graphics)
    start = renderer.render_level_enter_transition(0, set(), 0, 18)
    mid = renderer.render_level_enter_transition(0, set(), 9, 18)
    end = renderer.render_level_enter_transition(0, set(), 18, 18)

    assert start.getpixel((160, 100))[:3] != (0, 0, 0)
    assert mid.getpixel((160, 100))[:3] != start.getpixel((160, 100))[:3]
    assert end.getpixel((160, 100))[:3] == (0, 0, 0)


def test_map_icons_shifted_14_pixels_up():
    assert [choice.icon_position for choice in MAP_CHOICES] == [
        (108, 44),
        (38, 78),
        (38, 25),
        (194, 50),
    ]
