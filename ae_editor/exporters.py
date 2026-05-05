from __future__ import annotations

import csv
from pathlib import Path

from .constants import ROOM_COLUMNS, ROOM_COUNT, ROOM_ROWS
from .project import AncientEmpiresProject
from .renderer import RenderOptions


def export_room_previews(project: AncientEmpiresProject, outdir: Path, crop_left: int = 2) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    opts = RenderOptions(mode="terrain", zoom=1, grid=False, crop_left_columns=crop_left)
    for level in project.levels:
        for room_index in range(ROOM_COUNT):
            image = project.renderer.render_room(level, room_index, opts)
            image.save(outdir / f"level_{level.index + 1:02d}_room_{room_index:02d}.png")


def export_bank_sheets(project: AncientEmpiresProject, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    for rid, bank in project.graphics.banks.items():
        project.graphics.make_bank_sheet(rid, bank).save(outdir / f"bank_{rid:03d}_sheet.png")


def export_probe_csv(project: AncientEmpiresProject, outpath: Path) -> None:
    with outpath.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["level", "theme", "room", "x", "y", "tile_hex", "tile_dec", "header_hex", "footer_hex"])
        for level in project.levels:
            header_hex = level.header.hex(" ")
            footer_hex = level.footer.hex(" ")
            for room in level.rooms:
                for y in range(ROOM_ROWS):
                    for x in range(ROOM_COLUMNS):
                        value = room.get(x, y)
                        if value:
                            writer.writerow([level.index + 1, level.theme, room.index, x, y, f"{value:02X}", value, header_hex, footer_hex])
