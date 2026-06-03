#!/usr/bin/env python3
"""Audit the stock actor VM bytecode patterns used by Ancient Empires.

This is a research helper, not an editor action.  It scans every actor script
entry point referenced by every level/difficulty, disassembles the reachable
linear stream, and summarizes the opcode/condition/event/link patterns that the
future Actors tab should understand.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ancient_empires.game_data.actor_scripts import _command_size, _decode_command  # research-only private helpers
from ancient_empires.project import AncientEmpiresProject
from ancient_empires.game_data.room_payload import ACTOR_TABLE_OFFSET, parse_actor_table


def _scan_script(data: bytes, *, max_commands: int = 120):
    pc = 0
    seen: set[int] = set()
    out = []
    while pc < len(data) and len(out) < max_commands:
        if pc in seen:
            out.append((pc, None, b"", "loop_detected"))
            break
        seen.add(pc)
        cmd = _decode_command(data, pc)
        out.append((pc, cmd.opcode, cmd.raw, cmd.label))
        size = _command_size(data, pc)
        pc += size
        if cmd.opcode == 0x00 and data[pc:pc + 7] == b"\0" * 7:
            break
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".", help="directory containing AEPROG.EXE, AE000.DAT and AE001.DAT")
    ap.add_argument("--samples", type=int, default=3, help="sample rows per pattern")
    args = ap.parse_args()

    root = Path(args.root)
    project = AncientEmpiresProject(root / "AEPROG.EXE", [root / "AE000.DAT", root / "AE001.DAT"])

    opcode_counts: Counter[int] = Counter()
    event_counts: Counter[tuple[int, int]] = Counter()
    actor_link_counts: Counter[tuple[int, int]] = Counter()
    condition_next_counts: Counter[tuple[int, int]] = Counter()
    condition_samples: defaultdict[tuple[int, int], list[str]] = defaultdict(list)
    unique_scripts: set[tuple[int, bytes]] = set()

    actor_count = 0
    script_entry_count = 0
    for li, level in enumerate(project.levels, start=1):
        for pi in (0, 1):
            part = level.part(pi)
            for actor in parse_actor_table(part):
                actor_count += 1
                script_entry_count += 1
                start = ACTOR_TABLE_OFFSET + actor.script_offset
                data = bytes(part.raw[start:start + 256])
                unique_scripts.add((actor.script_offset, data[:64]))
                commands = _scan_script(data)
                for pc, opcode, raw, label in commands:
                    if opcode is None:
                        continue
                    opcode_counts[opcode] += 1
                    if opcode in {0x07, 0x08, 0x09} and len(raw) >= 2:
                        event_counts[(opcode, raw[1])] += 1
                    if opcode in {0x0A, 0x0B} and len(raw) >= 2:
                        actor_link_counts[(opcode, raw[1])] += 1
                    if 0x13 <= opcode <= 0x1B:
                        next_pc = pc + len(raw)
                        next_opcode = data[next_pc] if next_pc < len(data) else -1
                        condition_next_counts[(opcode, next_opcode)] += 1
                        key = (opcode, next_opcode)
                        if len(condition_samples[key]) < args.samples:
                            next_label = "<eof>" if next_opcode < 0 else _decode_command(data, next_pc).label
                            condition_samples[key].append(
                                f"L{li:02d} {'Expert' if pi else 'Explorer'} A{actor.index:02d} R{actor.room_index:02d} "
                                f"script={actor.script_offset:04X} pc={pc:04X}: {label}; next: {next_label}"
                            )

    print(f"actors={actor_count} script_entries={script_entry_count} unique_script_prefixes={len(unique_scripts)}")
    print("\nOpcode counts:")
    for opcode, count in sorted(opcode_counts.items()):
        print(f"  {opcode:02X}: {count}")

    print("\nCondition guarded-next-command patterns:")
    for (opcode, next_opcode), count in sorted(condition_next_counts.items()):
        next_label = "EOF" if next_opcode < 0 else f"{next_opcode:02X}"
        print(f"  {opcode:02X} -> next {next_label}: {count}")
        for sample in condition_samples[(opcode, next_opcode)]:
            print(f"      {sample}")

    print("\nEvent ids:")
    for (opcode, event_id), count in sorted(event_counts.items()):
        print(f"  event_{opcode:02X} id={event_id:02X}: {count}")

    print("\nActor link refs from opcodes 0A/0B:")
    for (opcode, ref), count in sorted(actor_link_counts.items()):
        mode = 1 if opcode == 0x0A else 0
        label = f"A{ref}" if ref < 0x80 else f"A+{ref & 0x7F}"
        print(f"  set_actor_mode {label}={mode}: {count}")


if __name__ == "__main__":
    main()
