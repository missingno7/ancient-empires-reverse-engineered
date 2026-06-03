from pathlib import Path

import pytest

from ae_editor.game_data.dat_archive import DatArchive
from ae_editor.game_data.level_format import Level, load_levels
from ae_editor.game_data.level_flip import flip_level_horizontally

_AE001 = Path(__file__).resolve().parents[1] / "game_data" / "AE001.DAT"


@pytest.mark.skipif(not _AE001.exists(), reason="game data not present")
def test_horizontal_level_flip_is_involution_for_all_stock_levels():
    ae001 = DatArchive(_AE001)
    for source in load_levels(ae001):
        level = Level(source.index, ae001[source.index].decoded)
        original = level.to_bytes()
        flip_level_horizontally(level)
        flip_level_horizontally(level)
        assert level.to_bytes() == original, f"level {source.index} changed after double flip"
