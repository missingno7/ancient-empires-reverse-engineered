#!/usr/bin/env python3
"""Print decoded actor-table path probes for Ancient Empires levels."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ancient_empires.game_data.actor_scripts import decode_actor_script
from ancient_empires.project import AncientEmpiresProject
from ancient_empires.game_data.room_payload import actor_records_for_room, parse_actor_table


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".", help="directory containing AEPROG.EXE, AE000.DAT and AE001.DAT")
    ap.add_argument("--level", type=int, default=None, help="1-based level number")
    ap.add_argument("--difficulty", choices=["explorer", "expert", "0", "1"], default="expert")
    ap.add_argument("--room", type=int, default=None, help="0-based room index")
    args = ap.parse_args()

    root = Path(args.root)
    project = AncientEmpiresProject(root / "AEPROG.EXE", [root / "AE000.DAT", root / "AE001.DAT"])
    part_index = 0 if args.difficulty in {"explorer", "0"} else 1

    levels = project.levels
    level_indices = [args.level - 1] if args.level is not None else range(len(levels))
    for li in level_indices:
        if li < 0 or li >= len(levels):
            continue
        level = levels[li]
        part = level.part(part_index)
        actors = parse_actor_table(part)
        room_indices = [args.room] if args.room is not None else sorted({a.room_index for a in actors})
        for room_index in room_indices:
            room_actors = actor_records_for_room(part, room_index)
            if not room_actors:
                continue
            print(f"Level {li + 1:02d} {'Expert' if part_index else 'Explorer'} room {room_index}")
            for actor in room_actors:
                decoded = decode_actor_script(part, actor, max_bytes=128, max_segments=12)
                name = actor.confirmed_name or f"frame_{actor.frame:02X}"
                points = " -> ".join(f"({x},{y})" for x, y in decoded.points[:8])
                print(
                    f"  A{actor.index:02d} {name:14s} start=({actor.x},{actor.y}) "
                    f"delay={actor.delay} script=0x{actor.script_offset:04x} {decoded.summary}"
                )
                if decoded.traces:
                    for ti, trace in enumerate(decoded.traces[:6]):
                        if not trace.segments:
                            continue
                        tpoints = " -> ".join(f"({x},{y})" for x, y in trace.points[:8])
                        print(f"      trace {ti}: {trace.label}")
                        print(f"          points {tpoints}")
                elif points:
                    print(f"      points {points}")


if __name__ == "__main__":
    main()
