from pathlib import Path

from ae_editor.game_data.dat_archive import DatArchive
from ae_editor.game_data.level_format import Level, load_levels
from ae_editor.game_data.level_flip import flip_level_horizontally


def test_horizontal_level_flip_is_involution_for_all_stock_levels():
    root = Path(__file__).resolve().parents[1]
    ae001 = DatArchive(root / "AE001.DAT")
    for source in load_levels(ae001):
        level = Level(source.index, ae001[source.index].decoded)
        original = level.to_bytes()
        flip_level_horizontally(level)
        flip_level_horizontally(level)
        assert level.to_bytes() == original, f"level {source.index} changed after double flip"
