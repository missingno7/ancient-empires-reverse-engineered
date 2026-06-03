#!/usr/bin/env python3
"""Dump lossless actor record + actor entry DSL for selected stock actors."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ancient_empires.game_data.actor_dsl import ActorRecordIR, decode_entry_until_stop, parse_dsl, ActorScriptError
from ancient_empires.game_data.actor_scripts import actor_script_bytes
from ancient_empires.project import AncientEmpiresProject
from ancient_empires.game_data.room_payload import actor_records_for_room, parse_actor_table


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".", help="directory containing AEPROG.EXE, AE000.DAT and AE001.DAT")
    ap.add_argument("--level", type=int, required=True, help="1-based level number")
    ap.add_argument("--difficulty", choices=["explorer", "expert", "0", "1"], default="explorer")
    ap.add_argument("--room", type=int, default=None, help="0-based room index")
    ap.add_argument("--actor", type=int, default=None, help="actor index A#")
    ap.add_argument("--max-bytes", type=int, default=192)
    args = ap.parse_args()

    root = Path(args.root)
    project = AncientEmpiresProject(root / "AEPROG.EXE", [root / "AE000.DAT", root / "AE001.DAT"])
    part_index = 0 if args.difficulty in {"explorer", "0"} else 1
    part = project.levels[args.level - 1].part(part_index)

    actors = parse_actor_table(part)
    if args.room is not None:
        actors = actor_records_for_room(part, args.room)
    if args.actor is not None:
        actors = [a for a in actors if a.index == args.actor]

    for actor in actors:
        name = actor.confirmed_name or f"frame_{actor.frame:02X}"
        print(ActorRecordIR.from_record(actor).to_dsl(name), end="")
        start, data = actor_script_bytes(part, actor, args.max_bytes)
        try:
            dsl = decode_entry_until_stop(data, 0).to_dsl()
            encoded = parse_dsl(dsl).to_bytes()
            original = data[:len(encoded)]
            status = "roundtrip=OK" if encoded == original else "roundtrip=MISMATCH"
        except ActorScriptError as exc:
            dsl = f"# decode error: {exc}\n"
            status = "roundtrip=ERROR"
        print(f"script A{actor.index}_entry_at_0x{actor.script_offset:04X} {{  # absolute part offset 0x{start:04X}, {status}")
        for line in dsl.splitlines():
            print("    " + line)
        print("}\n")


if __name__ == "__main__":
    main()
