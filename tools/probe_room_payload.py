#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from ae_editor.project import AncientEmpiresProject
from ae_editor.room_payload import parse_room_payload


def main() -> None:
    ap = argparse.ArgumentParser(description="Dump suspected object/trigger payload records for one room")
    ap.add_argument("--exe", required=True)
    ap.add_argument("--level", type=int, default=1, help="1-based level number")
    ap.add_argument("--page", choices=["A", "B"], default="A")
    ap.add_argument("--room", type=int, default=0)
    ap.add_argument("dat", nargs="+", help="AE000.DAT and AE001.DAT")
    args = ap.parse_args()

    project = AncientEmpiresProject(args.exe, [Path(p) for p in args.dat])
    level = project.levels[args.level - 1]
    part_index = 0 if args.page == "A" else 1
    room = level.room(args.room, part_index)
    parsed = parse_room_payload(room)

    print(f"level={args.level} page={args.page} room={args.room}")
    print(f"record_offset=0x{room.record_offset:04X} terrain_offset=0x{room.terrain_offset:04X}")
    print("leading triplets:")
    for p in parsed.leading_triplets:
        print(f"  +0x{p.source_offset:02X} {p.raw.hex(' ')}  {p.label}  tile=({p.tile_x:.2f},{p.tile_y:.2f})")
    print("candidate tables:")
    for c in parsed.candidate_tables:
        print(f"  offset=0x{c.offset:02X} schema={c.schema} count={c.count} score={c.score}")
        for p in c.points:
            print(f"    +0x{p.source_offset:02X} {p.raw.hex(' ')}  {p.label}  tile=({p.tile_x:.2f},{p.tile_y:.2f})")


if __name__ == "__main__":
    main()
