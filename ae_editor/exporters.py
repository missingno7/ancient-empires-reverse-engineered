from __future__ import annotations

import csv
from pathlib import Path

from .constants import ROOM_COLUMNS, ROOM_COUNT, ROOM_ROWS
from .project import AncientEmpiresProject
from .renderer import RenderOptions


def export_room_previews(project: AncientEmpiresProject, outdir: Path, crop_left: int = 0) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    for level in project.levels:
        for part in level.parts:
            opts = RenderOptions(mode="terrain", zoom=1, grid=False, crop_left_columns=crop_left, part_index=part.index)
            for room_index in range(ROOM_COUNT):
                image = project.renderer.render_room(level, room_index, opts)
                image.save(outdir / f"level_{level.index + 1:02d}_page_{chr(65 + part.index)}_room_{room_index:02d}.png")


def export_bank_sheets(project: AncientEmpiresProject, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    for rid, bank in project.graphics.banks.items():
        project.graphics.make_bank_sheet(rid, bank).save(outdir / f"bank_{rid:03d}_sheet.png")


def export_probe_csv(project: AncientEmpiresProject, outpath: Path) -> None:
    with outpath.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "level", "page", "theme", "room", "record_offset", "terrain_offset",
            "preamble_hex", "trailing_nonzero", "x", "y", "tile_hex", "tile_dec",
            "part_header_hex", "part_footer_hex",
        ])
        for level in project.levels:
            for part in level.parts:
                header_hex = part.header.hex(" ")
                footer_hex = part.footer.hex(" ")
                for room in part.rooms:
                    trailing_nonzero = sum(1 for b in room.trailing if b)
                    for y in range(ROOM_ROWS):
                        for x in range(ROOM_COLUMNS):
                            value = room.get(x, y)
                            if value:
                                writer.writerow([
                                    level.index + 1,
                                    chr(65 + part.index),
                                    part.theme,
                                    room.index,
                                    f"0x{room.record_offset:04X}",
                                    f"0x{room.terrain_offset:04X}",
                                    room.preamble.hex(" "),
                                    trailing_nonzero,
                                    x,
                                    y,
                                    f"{value:02X}",
                                    value,
                                    header_hex,
                                    footer_hex,
                                ])
