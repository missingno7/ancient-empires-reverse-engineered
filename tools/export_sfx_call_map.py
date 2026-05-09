#!/usr/bin/env python3
"""Export Ancient Empires SFX call-site evidence from the current data set.

This helper is intentionally conservative.  It does not try to decompile game
logic; it lists places where AEPROG_full_disasm.asm visibly calls CAF1 and it
also scans decoded actor bytecode for opcode 0x07, which the ASM maps to
`lods al; push ax; call CAF1`.
"""
from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ae_editor.game_data.dat_archive import DatArchive
from ae_editor.game_data.level_format import load_levels
from ae_editor.game_data.room_payload import parse_actor_table
from ae_editor.game_data.actor_scripts import actor_script_bytes, _command_size


def scan_hardcoded_calls(asm_path: Path) -> list[dict[str, str]]:
    lines = asm_path.read_text(errors="ignore").splitlines()
    rows: list[dict[str, str]] = []
    for idx, line in enumerate(lines):
        if "call   0xcaf1" not in line:
            continue
        addr_match = re.search(r"^\s*([0-9a-f]+):", line)
        addr = addr_match.group(1).upper() if addr_match else "?"
        ctx = lines[max(0, idx - 10):idx]
        sound_id: str | None = None
        source = "unknown"
        for prev in reversed(ctx):
            mov = re.search(r"mov\s+ax,0x([0-9a-f]+)", prev)
            if mov:
                sound_id = f"0x{int(mov.group(1), 16):02X}"
                source = "immediate"
                break
            if "xor    ax,ax" in prev or "33 c0" in prev:
                sound_id = "0x00"
                source = "immediate"
                break
            if "lods   al" in prev:
                sound_id = "script byte"
                source = "actor/script opcode 0x07"
                break
            if "push   WORD PTR" in prev:
                sound_id = "variable"
                source = "runtime variable"
                break
        rows.append({
            "address": f"0x{addr}",
            "sound_id": sound_id or "unknown",
            "source": source,
            "context_before": " | ".join(s.strip() for s in ctx[-4:]),
        })
    return rows


def scan_actor_script_sound_uses(levels) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for level_no, level in enumerate(levels, start=1):
        for part in level.parts:
            difficulty = "Explorer" if part.index == 0 else "Expert"
            for actor in parse_actor_table(part):
                start_abs, data = actor_script_bytes(part, actor, limit=512)
                pc = 0
                seen: set[int] = set()
                # Linear scan is enough to find most explicit play_sound bytes.
                # We stop on zero padding and on simple loops to avoid walking
                # arbitrary shared script fragments forever.
                for _ in range(220):
                    if pc >= len(data) or pc in seen:
                        break
                    seen.add(pc)
                    opcode = data[pc]
                    size = _command_size(data, pc)
                    raw = data[pc:pc + size]
                    if opcode == 0x00 and raw == b"\x00":
                        break
                    if opcode == 0x07 and len(raw) >= 2:
                        rows.append({
                            "sound_id": f"0x{raw[1]:02X}",
                            "level": str(level_no),
                            "difficulty": difficulty,
                            "actor_index": str(actor.index),
                            "actor_name": actor.confirmed_name or "",
                            "room_index": str(actor.room_index),
                            "script_offset": f"0x{actor.script_offset:04X}",
                            "pc": f"0x{pc:04X}",
                            "absolute_part_offset": f"0x{start_abs + pc:04X}",
                        })
                    pc += max(1, size)
    return rows


def main() -> None:
    asm_path = ROOT / "Decompile notes" / "AEPROG_full_disasm.asm"
    hardcoded = scan_hardcoded_calls(asm_path)
    levels = load_levels(DatArchive(ROOT / "AE001.DAT"))
    actor_uses = scan_actor_script_sound_uses(levels)

    out_dir = ROOT / "docs"
    out_dir.mkdir(exist_ok=True)
    with (out_dir / "sfx_hardcoded_caf1_calls.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["address", "sound_id", "source", "context_before"])
        writer.writeheader()
        writer.writerows(hardcoded)
    with (out_dir / "sfx_actor_script_uses.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["sound_id", "level", "difficulty", "actor_index", "actor_name", "room_index", "script_offset", "pc", "absolute_part_offset"])
        writer.writeheader()
        writer.writerows(actor_uses)

    print("Hardcoded CAF1 calls:", len(hardcoded))
    print("Actor-script play_sound opcodes:", len(actor_uses))
    print("Actor-script sound IDs:", dict(sorted(Counter(row["sound_id"] for row in actor_uses).items())))


if __name__ == "__main__":
    main()
