from __future__ import annotations

import csv
from pathlib import Path

from ..constants import ROOM_COLUMNS, ROOM_COUNT, ROOM_ROWS
from ..project import AncientEmpiresProject
from ..rendering.room_renderer import RenderOptions
from ..game_data.room_payload import header_exit_door, parse_exe_payload_directory, parse_platform_triplets, visual_compact3_table, laser_crystal_table

DIFFICULTY_LABELS = ["explorer", "expert"]


def export_room_previews(project: AncientEmpiresProject, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    for level in project.levels:
        for part in level.parts:
            opts = RenderOptions(mode="game", zoom=1, grid=False, part_index=part.index)
            for room_index in range(ROOM_COUNT):
                image = project.renderer.render_room(level, room_index, opts)
                image.save(outdir / f"level_{level.index + 1:02d}_{DIFFICULTY_LABELS[part.index]}_room_{room_index:02d}.png")


def export_bank_sheets(project: AncientEmpiresProject, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    for rid, bank in project.graphics.banks.items():
        safe = rid.replace(":", "_")
        project.graphics.make_bank_sheet(rid, bank).save(outdir / f"bank_{safe}_sheet.png")


def export_probe_csv(project: AncientEmpiresProject, outpath: Path) -> None:
    with outpath.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "level", "difficulty", "theme", "room", "record_offset", "terrain_offset",
            "preamble_hex", "trailing_nonzero", "platform_triplets", "control_records",
            "exit_door", "crystal_table", "visual_table", "x", "y", "tile_hex", "tile_dec",
        ])
        for level in project.levels:
            for part in level.parts:
                for room in part.rooms:
                    directory = parse_exe_payload_directory(room)
                    controls = "" if directory is None else " | ".join(r.label for r in directory.control_records)
                    platforms = " | ".join(p.label for p in parse_platform_triplets(room))
                    crystals = laser_crystal_table(room)
                    visual = visual_compact3_table(room)
                    door = header_exit_door(part.header)
                    door_txt = "" if door is None else f"room={door.room_index} x={door.x_raw:02X} y={door.y_raw:02X}"
                    crystal_txt = "" if crystals is None else f"@0x{crystals.offset:02X} n={crystals.count}"
                    visual_txt = "" if visual is None else f"@0x{visual.offset:02X} n={visual.count}"
                    trailing_nonzero = sum(1 for b in room.trailing if b)
                    for y in range(ROOM_ROWS):
                        for x in range(ROOM_COLUMNS):
                            value = room.get(x, y)
                            if value:
                                writer.writerow([
                                    level.index + 1,
                                    DIFFICULTY_LABELS[part.index],
                                    part.theme,
                                    room.index,
                                    f"0x{room.record_offset:04X}",
                                    f"0x{room.terrain_offset:04X}",
                                    room.preamble.hex(" "),
                                    trailing_nonzero,
                                    platforms,
                                    controls,
                                    door_txt,
                                    crystal_txt,
                                    visual_txt,
                                    x,
                                    y,
                                    f"{value:02X}",
                                    value,
                                ])
