#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from ae_editor.project import AncientEmpiresProject
from ae_editor.room_payload import control_commands, header_exit_door, parse_exe_payload_directory, parse_platform_triplets, visual_compact3_table, laser_crystal_table


def main() -> None:
    ap = argparse.ArgumentParser(description="Dump EXE-style room payload structures")
    ap.add_argument("dat", nargs="+", help="DAT files, usually AE000.DAT AE001.DAT")
    ap.add_argument("--exe", default="AEPROG.EXE")
    ap.add_argument("--level", type=int, required=True, help="1-based level number")
    ap.add_argument("--difficulty", choices=["Explorer", "Expert"], default="Explorer")
    ap.add_argument("--room", type=int, required=True, help="0-based room index")
    args = ap.parse_args()

    part_index = 1 if args.difficulty == "Expert" else 0
    project = AncientEmpiresProject(Path(args.exe), [Path(x) for x in args.dat])
    part = project.levels[args.level - 1].part(part_index)
    room = part.room(args.room)

    print(f"level={args.level} difficulty={args.difficulty} room={args.room}")
    door = header_exit_door(part.header)
    print(f"exit door: {'<none>' if door is None else door.label}")
    print("platform/control triplets:")
    for p in parse_platform_triplets(room):
        print(f"  @{p.source_offset:02X} idx={p.index:02d} flags={p.flags:02X} orientation={p.orientation} x={p.x_raw:02X} y={p.y:02X} raw={p.raw.hex(' ')}")

    d = parse_exe_payload_directory(room)
    print("\nEXE payload directory:")
    if not d:
        print("  <none>")
    else:
        print(f"  base=@{d.base_offset:02X} dir_count={d.directory_count} selected_index={d.selected_visual_index} variable_start=@{d.variable_start:02X} selected_table_offset={None if d.selected_table_offset is None else '@%02X' % d.selected_table_offset}")
        print("  length-prefixed control records:")
        for rec in d.control_records:
            print(f"    {rec.label}")
        print("  decoded control command bodies:")
        for cmd in control_commands(room):
            print(f"    {cmd.label} command={cmd.command} x={cmd.x_raw} y={cmd.y_raw} arg_a={cmd.arg_a} arg_b={cmd.arg_b} extra={cmd.extra.hex(' ')}")
        if d.sections:
            print("  EXE sections after control records:")
            def dump_c3(name, table):
                if table is None:
                    print(f"    {name}: <none>")
                    return
                print(f"    {name}: @{table.offset:02X} count={table.count}")
                for e in table.entries:
                    print(f"      @{e.source_offset:02X} idx={e.index:02d} x={e.x_raw:02X} y={e.y:02X} code={e.code:02X} raw={e.raw.hex(' ')}")
            dump_c3("section_a compact3", d.sections.section_a)
            print(f"    section_b record12: @{d.sections.section_b_offset if d.sections.section_b_offset is not None else -1:02X} count={d.sections.section_b_count}")
            for i, raw in enumerate(d.sections.section_b_records):
                print(f"      rec12[{i:02d}] {raw.hex(' ')}")
            dump_c3("section_c compact3 / laser-crystal candidates", d.sections.section_c)
            dump_c3("visual compact3", d.sections.visual)
        else:
            print("  EXE sections: <empty/unknown>")

    print("\nrenderer tables:")
    for name, table in [("laser_crystals", laser_crystal_table(room)), ("visual", visual_compact3_table(room))]:
        if not table:
            print(f"  {name}: <none>")
            continue
        print(f"  {name}: @{table.offset:02X} {table.label} count={table.count}")
        for e in table.entries:
            print(f"    @{e.source_offset:02X} idx={e.index:02d} x={e.x_raw:02X} y={e.y:02X} code={e.code:02X} raw={e.raw.hex(' ')}")


if __name__ == "__main__":
    main()
