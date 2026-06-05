from pathlib import Path

import pytest

from ancient_empires.project import AncientEmpiresProject
from ancient_empires.rendering.bitmap_font import BitmapFont
from ancient_empires.rendering.dialog_screen import DifficultyDialogRenderer


EXE = Path("game_data/AEPROG.EXE")
DATS = [Path("game_data/AE000.DAT"), Path("game_data/AE001.DAT")]
pytestmark = pytest.mark.game_data


def test_bitmap_font_resource_draws_menu_text():
    project = AncientEmpiresProject(EXE, DATS)
    font = BitmapFont.from_resource(project.ae000[0].decoded)

    assert font.line_height == 10
    assert font.measure("Which Level of Difficulty?") > 120


def test_difficulty_dialog_has_inverted_selected_row():
    project = AncientEmpiresProject(EXE, DATS)
    font = BitmapFont.from_resource(project.ae000[0].decoded)
    image = DifficultyDialogRenderer(font).render(0)

    assert image.size == (320, 200)
    assert image.getpixel((160, 100))[:3] == (255, 255, 255)
    assert image.getpixel((120, 128))[:3] == (0, 0, 0)
    assert image.getpixel((120, 140))[:3] == (255, 255, 255)
