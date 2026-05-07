"""Lossless actor VM assembler/disassembler.

This module is deliberately assembler-like.  It only represents bytes that are
actually stored in the Ancient Empires actor table / actor script stream; higher
level summaries such as "patrol left/right" should be built on top of this IR,
not used as the source of truth for writing data.

Round-trip contract for a known script region::

    script = decode_script_region(raw_region)
    assert parse_dsl(script.to_dsl()).to_bytes() == raw_region

Labels are only syntax sugar for relative branches.  Unknown opcodes are not
accepted because the current research scan found the VM opcode set to be
0x00..0x1B; failing loudly is safer than silently corrupting actor data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Callable, Dict, Iterable, List, Optional, Tuple


class ActorScriptError(ValueError):
    """Raised when actor DSL/bytecode cannot be decoded or assembled safely."""


# ---------------------------------------------------------------------------
# Numeric helpers


def s8(value: int) -> int:
    value &= 0xFF
    return value - 0x100 if value & 0x80 else value


def enc_s8(value: int) -> int:
    if not -128 <= value <= 127:
        raise ActorScriptError(f"signed byte out of range: {value}")
    return value & 0xFF


def u8(value: int) -> int:
    if not 0 <= value <= 0xFF:
        raise ActorScriptError(f"byte out of range: {value}")
    return value


def u16le(data: bytes, offset: int) -> int:
    if offset + 2 > len(data):
        raise ActorScriptError(f"unexpected EOF while reading u16 at {offset:#x}")
    return data[offset] | (data[offset + 1] << 8)


def s16le(data: bytes, offset: int) -> int:
    value = u16le(data, offset)
    return value - 0x10000 if value & 0x8000 else value


def enc_u16(value: int) -> bytes:
    if not 0 <= value <= 0xFFFF:
        raise ActorScriptError(f"u16 out of range: {value}")
    return value.to_bytes(2, "little")


def enc_s16(value: int) -> bytes:
    if not -32768 <= value <= 32767:
        raise ActorScriptError(f"s16 out of range: {value}")
    return (value & 0xFFFF).to_bytes(2, "little")


def parse_int(text: str) -> int:
    text = text.strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    if text.lower().startswith("-0x"):
        return -int(text[3:], 16)
    return int(text, 10)


# ---------------------------------------------------------------------------
# Instruction model


OPCODE_NAMES: Dict[int, str] = {
    0x00: "wait",
    0x01: "goto",
    0x02: "call",
    0x03: "return",
    0x04: "loop_a",
    0x05: "loop_b",
    0x06: "loop_c",
    0x07: "event_07",
    0x08: "event_08",
    0x09: "event_09",
    0x0A: "set_actor_mode_1",
    0x0B: "set_actor_mode_0",
    0x0C: "set_frames",
    0x0D: "set_frame",
    0x0E: "move",
    0x0F: "move_to",
    0x10: "move_to_room",
    0x11: "hide",
    0x12: "show",
    0x13: "if_runtime_lowbits_set",
    0x14: "if_runtime_lowbits_clear",
    0x15: "if_runtime_bit10_clear",
    0x16: "if_runtime_bit10_set",
    0x17: "if_player_x_gt",
    0x18: "if_player_x_lt",
    0x19: "if_player_y_gt",
    0x1A: "if_player_y_lt",
    0x1B: "if_random_lt",
}
NAME_TO_OPCODE = {name: opcode for opcode, name in OPCODE_NAMES.items()}


def opcode_size(opcode: int) -> int:
    if opcode in {0x00, 0x03, 0x11, 0x12}:
        return 1
    if opcode in {0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0D, 0x17, 0x18, 0x19, 0x1A, 0x1B}:
        return 2
    if opcode in {0x01, 0x02, 0x0C, 0x13, 0x14, 0x15, 0x16}:
        return 3
    if opcode in {0x0E, 0x0F}:
        return 4
    if opcode in {0x04, 0x05, 0x06, 0x10}:
        return 5
    raise ActorScriptError(f"unknown actor opcode {opcode:#04x}")


def branch_target(offset: int, opcode: int, rel: int) -> int:
    return offset + opcode_size(opcode) + rel


@dataclass
class Instruction:
    opcode: int
    args: Tuple[int, ...] = field(default_factory=tuple)
    label: Optional[str] = None
    target_label: Optional[str] = None
    offset: int = 0
    raw: bytes = b""

    @property
    def mnemonic(self) -> str:
        return OPCODE_NAMES[self.opcode]

    def byte_size(self) -> int:
        return opcode_size(self.opcode)

    def target_offset(self) -> Optional[int]:
        if self.opcode in {0x01, 0x02} and self.args:
            return branch_target(self.offset, self.opcode, self.args[0])
        if self.opcode in {0x04, 0x05, 0x06} and self.args:
            return branch_target(self.offset, self.opcode, self.args[0])
        return None

    def to_bytes(self, resolve_label: Optional[Callable[[str], int]] = None) -> bytes:
        op = self.opcode

        def encoded_rel(arg_index: int = 0) -> bytes:
            if self.target_label is not None:
                if resolve_label is None:
                    raise ActorScriptError(f"cannot resolve label {self.target_label!r}")
                target = resolve_label(self.target_label)
                rel = target - (self.offset + opcode_size(op))
            else:
                if arg_index >= len(self.args):
                    raise ActorScriptError(f"missing relative argument for {self.mnemonic}")
                rel = self.args[arg_index]
            return enc_s16(rel)

        if op in {0x00, 0x03, 0x11, 0x12}:
            return bytes([op])
        if op in {0x01, 0x02}:
            return bytes([op]) + encoded_rel(0)
        if op in {0x04, 0x05, 0x06}:
            if self.target_label is not None:
                if len(self.args) != 1:
                    raise ActorScriptError(f"{self.mnemonic} with label needs exactly count arg")
                count = self.args[0]
            else:
                if len(self.args) != 2:
                    raise ActorScriptError(f"{self.mnemonic} needs rel and count")
                count = self.args[1]
            return bytes([op]) + encoded_rel(0) + enc_u16(count)
        if op in {0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0D, 0x17, 0x18, 0x19, 0x1A, 0x1B}:
            return bytes([op, u8(self.args[0])])
        if op == 0x0C:
            return bytes([op, u8(self.args[0]), u8(self.args[1])])
        if op == 0x0E:
            dx, dy, frame_delta = self.args
            return bytes([op, enc_s8(dx), enc_s8(dy), u8(frame_delta)])
        if op == 0x0F:
            x_raw, y, frame_delta = self.args
            return bytes([op, u8(x_raw), u8(y), u8(frame_delta)])
        if op == 0x10:
            x_raw, y, packed_frame, room = self.args
            return bytes([op, u8(x_raw), u8(y), u8(packed_frame), u8(room)])
        if op in {0x13, 0x14, 0x15, 0x16}:
            return bytes([op]) + enc_u16(self.args[0])
        raise ActorScriptError(f"cannot encode opcode {op:#04x}")


@dataclass
class ActorScript:
    instructions: List[Instruction]

    def assign_offsets(self) -> None:
        offset = 0
        for ins in self.instructions:
            ins.offset = offset
            offset += ins.byte_size()

    def label_offsets(self) -> Dict[str, int]:
        self.assign_offsets()
        labels: Dict[str, int] = {}
        for ins in self.instructions:
            if ins.label is not None:
                if ins.label in labels:
                    raise ActorScriptError(f"duplicate label: {ins.label}")
                labels[ins.label] = ins.offset
        return labels

    def to_bytes(self) -> bytes:
        labels = self.label_offsets()

        def resolve(label: str) -> int:
            if label not in labels:
                raise ActorScriptError(f"unknown label: {label}")
            return labels[label]

        out = bytearray()
        for ins in self.instructions:
            out.extend(ins.to_bytes(resolve))
        return bytes(out)

    def to_dsl(self, *, auto_labels: bool = True) -> str:
        self.assign_offsets()
        labels: Dict[int, str] = {}
        instruction_offsets = {ins.offset for ins in self.instructions}
        if auto_labels:
            for ins in self.instructions:
                target = ins.target_offset()
                # Only create labels for targets that are part of this decoded
                # region.  Entry-point display often ends before an out-of-region
                # target, and a dangling label would not assemble back.
                if target is not None and target in instruction_offsets:
                    labels.setdefault(target, f"L{target:04X}")
        for ins in self.instructions:
            if ins.label:
                labels[ins.offset] = ins.label

        lines: List[str] = []
        for ins in self.instructions:
            if ins.offset in labels:
                lines.append(f"{labels[ins.offset]}:")
            lines.append("    " + instruction_to_dsl(ins, labels))
        return "\n".join(lines) + "\n"


def decode_instruction(data: bytes, offset: int) -> Instruction:
    if offset >= len(data):
        raise ActorScriptError(f"offset outside script: {offset:#x}")
    op = data[offset]
    size = opcode_size(op)
    if offset + size > len(data):
        raise ActorScriptError(f"instruction at {offset:#x} crosses script region end")
    raw = data[offset : offset + size]

    if op in {0x00, 0x03, 0x11, 0x12}:
        args: Tuple[int, ...] = ()
    elif op in {0x01, 0x02}:
        args = (s16le(data, offset + 1),)
    elif op in {0x04, 0x05, 0x06}:
        args = (s16le(data, offset + 1), u16le(data, offset + 3))
    elif op in {0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0D, 0x17, 0x18, 0x19, 0x1A, 0x1B}:
        args = (data[offset + 1],)
    elif op == 0x0C:
        args = (data[offset + 1], data[offset + 2])
    elif op == 0x0E:
        args = (s8(data[offset + 1]), s8(data[offset + 2]), data[offset + 3])
    elif op == 0x0F:
        args = (data[offset + 1], data[offset + 2], data[offset + 3])
    elif op == 0x10:
        args = (data[offset + 1], data[offset + 2], data[offset + 3], data[offset + 4])
    elif op in {0x13, 0x14, 0x15, 0x16}:
        args = (u16le(data, offset + 1),)
    else:  # pragma: no cover; opcode_size has already guarded this.
        raise ActorScriptError(f"unknown opcode {op:#04x}")
    return Instruction(opcode=op, args=args, offset=offset, raw=raw)


def decode_script_region(data: bytes, start_offset: int = 0, end_offset: Optional[int] = None) -> ActorScript:
    """Decode a known contiguous script byte region.

    This is the function to use when exact round-trip is required.  It does not
    try to infer control-flow boundaries; it decodes every byte between
    ``start_offset`` and ``end_offset`` as VM instructions.
    """
    if end_offset is None:
        end_offset = len(data)
    if not 0 <= start_offset <= end_offset <= len(data):
        raise ActorScriptError("invalid script region")
    pc = start_offset
    instructions: List[Instruction] = []
    while pc < end_offset:
        ins = decode_instruction(data, pc)
        ins.offset -= start_offset
        instructions.append(ins)
        pc += ins.byte_size()
    return ActorScript(instructions)


def decode_entry_until_stop(data: bytes, start_offset: int = 0, *, max_instructions: int = 256) -> ActorScript:
    """Decode one entry point conservatively until a hard control-flow stop.

    This is useful for display.  It does not claim to cover the whole shared
    script stream, so only use ``decode_script_region`` for exact region edits.
    """
    pc = start_offset
    instructions: List[Instruction] = []
    for _ in range(max_instructions):
        if pc < 0 or pc >= len(data):
            break
        ins = decode_instruction(data, pc)
        ins.offset -= start_offset
        instructions.append(ins)
        pc += ins.byte_size()
        if ins.opcode in {0x00, 0x01, 0x03, 0x11}:
            break
    return ActorScript(instructions)


# ---------------------------------------------------------------------------
# DSL rendering/parsing


def format_actor_ref(value: int) -> str:
    if value < 0x80:
        return f"A{value}"
    return f"REL+{value & 0x7F}"


def parse_actor_ref(text: str) -> int:
    t = text.strip().upper()
    if t.startswith("REL+"):
        return 0x80 | u8(parse_int(t[4:]))
    if t.startswith("A"):
        return u8(parse_int(t[1:]))
    return u8(parse_int(t))


def instruction_to_dsl(ins: Instruction, labels_by_offset: Dict[int, str]) -> str:
    op = ins.opcode
    name = ins.mnemonic
    target = ins.target_offset()
    target_text = labels_by_offset.get(target) if target is not None else None

    if op == 0x00:
        return "wait"
    if op == 0x01:
        if ins.target_label:
            return f"goto {ins.target_label}"
        return f"goto {target_text}" if target_text else f"goto rel={ins.args[0]}"
    if op == 0x02:
        if ins.target_label:
            return f"call {ins.target_label}"
        return f"call {target_text}" if target_text else f"call rel={ins.args[0]}"
    if op == 0x03:
        return "return"
    if op in {0x04, 0x05, 0x06}:
        if ins.target_label:
            count = ins.args[0]
            return f"{name} {ins.target_label} count={count}"
        count = ins.args[1]
        if target_text:
            return f"{name} {target_text} count={count}"
        return f"{name} rel={ins.args[0]} count={count}"
    if op in {0x07, 0x08, 0x09}:
        return f"{name} id={ins.args[0]}"
    if op in {0x0A, 0x0B}:
        return f"{name} actor={format_actor_ref(ins.args[0])}"
    if op == 0x0C:
        return f"set_frames 0x{ins.args[0]:02X}..0x{ins.args[1]:02X}"
    if op == 0x0D:
        return f"set_frame 0x{ins.args[0]:02X}"
    if op == 0x0E:
        return f"move dx={ins.args[0]} dy={ins.args[1]} frame_delta=0x{ins.args[2]:02X}"
    if op == 0x0F:
        return f"move_to x_raw={ins.args[0]} y={ins.args[1]} frame_delta=0x{ins.args[2]:02X}"
    if op == 0x10:
        return f"move_to_room room={ins.args[3]} x_raw={ins.args[0]} y={ins.args[1]} frame=0x{ins.args[2]:02X}"
    if op == 0x11:
        return "hide"
    if op == 0x12:
        return "show"
    if op in {0x13, 0x14, 0x15, 0x16}:
        return f"{name} offset=0x{ins.args[0]:04X}"
    if op in {0x17, 0x18, 0x19, 0x1A, 0x1B}:
        return f"{name} value={ins.args[0]}"
    raise ActorScriptError(f"cannot render opcode {op:#04x}")


LABEL_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):$")
ARG_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.+)$")


def parse_args(parts: Iterable[str]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for part in parts:
        match = ARG_RE.fullmatch(part)
        if not match:
            raise ActorScriptError(f"invalid argument {part!r}")
        result[match.group(1)] = match.group(2)
    return result


def parse_dsl(text: str) -> ActorScript:
    instructions: List[Instruction] = []
    pending_label: Optional[str] = None

    def add(opcode: int, args: Tuple[int, ...] = (), target_label: Optional[str] = None) -> None:
        nonlocal pending_label
        instructions.append(Instruction(opcode=opcode, args=args, label=pending_label, target_label=target_label))
        pending_label = None

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        label_match = LABEL_RE.fullmatch(line)
        if label_match:
            if pending_label is not None:
                raise ActorScriptError(f"line {line_no}: label {pending_label!r} has no instruction")
            pending_label = label_match.group(1)
            continue

        parts = line.split()
        cmd, rest = parts[0], parts[1:]
        try:
            if cmd == "wait":
                add(0x00)
            elif cmd == "goto":
                if len(rest) != 1:
                    raise ActorScriptError("goto needs label or rel=N")
                if rest[0].startswith("rel="):
                    add(0x01, (parse_int(rest[0][4:]),))
                else:
                    add(0x01, target_label=rest[0])
            elif cmd == "call":
                if len(rest) != 1:
                    raise ActorScriptError("call needs label or rel=N")
                if rest[0].startswith("rel="):
                    add(0x02, (parse_int(rest[0][4:]),))
                else:
                    add(0x02, target_label=rest[0])
            elif cmd == "return":
                add(0x03)
            elif cmd in {"loop_a", "loop_b", "loop_c"}:
                op = NAME_TO_OPCODE[cmd]
                if not rest:
                    raise ActorScriptError(f"{cmd} needs target and count=N")
                target = rest[0]
                kwargs = parse_args(rest[1:])
                count = parse_int(kwargs["count"])
                if target.startswith("rel="):
                    add(op, (parse_int(target[4:]), count))
                else:
                    add(op, (count,), target_label=target)
            elif cmd in {"event_07", "event_08", "event_09"}:
                kwargs = parse_args(rest)
                add(NAME_TO_OPCODE[cmd], (parse_int(kwargs["id"]),))
            elif cmd in {"set_actor_mode_1", "set_actor_mode_0"}:
                kwargs = parse_args(rest)
                add(NAME_TO_OPCODE[cmd], (parse_actor_ref(kwargs["actor"]),))
            elif cmd == "set_frames":
                if len(rest) != 1 or ".." not in rest[0]:
                    raise ActorScriptError("set_frames needs MIN..MAX")
                lo, hi = rest[0].split("..", 1)
                add(0x0C, (parse_int(lo), parse_int(hi)))
            elif cmd == "set_frame":
                if len(rest) != 1:
                    raise ActorScriptError("set_frame needs one value")
                add(0x0D, (parse_int(rest[0]),))
            elif cmd == "move":
                kwargs = parse_args(rest)
                add(0x0E, (parse_int(kwargs["dx"]), parse_int(kwargs["dy"]), parse_int(kwargs["frame_delta"])))
            elif cmd == "move_to":
                kwargs = parse_args(rest)
                add(0x0F, (parse_int(kwargs["x_raw"]), parse_int(kwargs["y"]), parse_int(kwargs["frame_delta"])))
            elif cmd == "move_to_room":
                kwargs = parse_args(rest)
                add(0x10, (parse_int(kwargs["x_raw"]), parse_int(kwargs["y"]), parse_int(kwargs["frame"]), parse_int(kwargs["room"])))
            elif cmd == "hide":
                add(0x11)
            elif cmd == "show":
                add(0x12)
            elif cmd in {"if_runtime_lowbits_set", "if_runtime_lowbits_clear", "if_runtime_bit10_clear", "if_runtime_bit10_set"}:
                kwargs = parse_args(rest)
                add(NAME_TO_OPCODE[cmd], (parse_int(kwargs["offset"]),))
            elif cmd in {"if_player_x_gt", "if_player_x_lt", "if_player_y_gt", "if_player_y_lt", "if_random_lt"}:
                kwargs = parse_args(rest)
                add(NAME_TO_OPCODE[cmd], (parse_int(kwargs["value"]),))
            else:
                raise ActorScriptError(f"unknown DSL command {cmd!r}")
        except KeyError as exc:
            raise ActorScriptError(f"line {line_no}: missing argument {exc.args[0]!r}") from exc
        except ActorScriptError as exc:
            raise ActorScriptError(f"line {line_no}: {exc}") from exc

    if pending_label is not None:
        raise ActorScriptError(f"label {pending_label!r} has no instruction")
    return ActorScript(instructions)


def round_trip_dsl(data: bytes) -> str:
    """Return DSL and assert that DSL -> bytes exactly matches ``data``."""
    script = decode_script_region(data)
    dsl = script.to_dsl()
    encoded = parse_dsl(dsl).to_bytes()
    if encoded != data:
        raise ActorScriptError(
            "round-trip mismatch\n"
            f"original: {data.hex(' ')}\n"
            f"encoded:  {encoded.hex(' ')}\n"
            f"dsl:\n{dsl}"
        )
    return dsl


# ---------------------------------------------------------------------------
# Actor record DSL.  This also round-trips the 0x20-byte record itself.


@dataclass
class ActorRecordIR:
    index: int
    actor_type: int
    room: int
    x: int
    y: int
    frame: int
    variant: int
    hidden: int
    delay: int
    cooldown: int
    frame_min: int
    frame_max: int
    script: int
    saved_pc: int
    loop_a: int
    loop_b: int
    loop_c: int
    restart: int
    contact: int
    vertical_marker: int
    activated: int
    raw_state: bytes

    @classmethod
    def from_record(cls, record) -> "ActorRecordIR":
        return cls(
            index=record.index,
            actor_type=record.actor_type,
            room=record.room_index,
            x=record.x,
            y=record.y,
            frame=record.frame,
            variant=record.frame_variant,
            hidden=record.hidden,
            delay=record.delay,
            cooldown=record.cooldown,
            frame_min=record.frame_min,
            frame_max=record.frame_max,
            script=record.script_offset,
            saved_pc=record.saved_script_offset,
            loop_a=record.loop_counter_a,
            loop_b=record.loop_counter_b,
            loop_c=record.loop_counter_c,
            restart=record.restart_script_offset,
            contact=record.contact_behavior,
            vertical_marker=record.vertical_marker,
            activated=record.activated_flag,
            raw_state=bytes(record.runtime_tail),
        )

    def to_bytes(self) -> bytes:
        if len(self.raw_state) != 4:
            raise ActorScriptError("actor raw_state must be exactly 4 bytes")
        out = bytearray()
        out.extend([u8(self.actor_type), u8(self.room)])
        out.extend(enc_u16(self.x))
        out.extend(enc_u16(self.y))
        out.extend([u8(self.frame), u8(self.variant), u8(self.hidden), u8(self.delay), u8(self.cooldown)])
        out.extend([u8(self.frame_min), u8(self.frame_max)])
        out.extend(enc_u16(self.script))
        out.extend(enc_u16(self.saved_pc))
        out.extend(enc_u16(self.loop_a))
        out.extend(enc_u16(self.loop_b))
        out.extend(enc_u16(self.loop_c))
        out.extend(enc_u16(self.restart))
        out.extend([u8(self.contact), u8(self.vertical_marker), u8(self.activated)])
        out.extend(self.raw_state)
        if len(out) != 0x20:
            raise ActorScriptError(f"internal actor record size mismatch: {len(out)}")
        return bytes(out)

    def to_dsl(self, name: Optional[str] = None) -> str:
        title = f"actor A{self.index}" + (f" \"{name}\"" if name else "") + " {"
        raw_state = " ".join(f"{b:02X}" for b in self.raw_state)
        return "\n".join(
            [
                title,
                f"    mode 0x{self.actor_type:02X}",
                f"    room {self.room}",
                f"    position x={self.x} y={self.y}",
                f"    frame 0x{self.frame:02X}",
                f"    variant 0x{self.variant:02X}",
                f"    hidden 0x{self.hidden:02X}",
                f"    delay {self.delay}",
                f"    cooldown {self.cooldown}",
                f"    frames 0x{self.frame_min:02X}..0x{self.frame_max:02X}",
                f"    script 0x{self.script:04X}",
                f"    saved_pc 0x{self.saved_pc:04X}",
                f"    restart 0x{self.restart:04X}",
                f"    loops a={self.loop_a} b={self.loop_b} c={self.loop_c}",
                f"    contact 0x{self.contact:02X}",
                f"    vertical_marker 0x{self.vertical_marker:02X}",
                f"    activated 0x{self.activated:02X}",
                f"    raw_state {raw_state}",
                "}",
                "",
            ]
        )

ACTOR_HEADER_RE = re.compile(r'^actor\s+A(\d+)(?:\s+"([^"]*)")?\s*\{$')


def parse_actor_record_dsl(text: str) -> ActorRecordIR:
    """Parse the actor-record block emitted by ``ActorRecordIR.to_dsl``.

    This covers the 0x20-byte table record.  The optional quoted name is ignored
    because it is derived from the sprite/frame mapping, not stored in the raw
    actor record.
    """
    lines = [line.split("#", 1)[0].strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if len(lines) < 2:
        raise ActorScriptError("empty actor record DSL")
    header = ACTOR_HEADER_RE.fullmatch(lines[0])
    if not header:
        raise ActorScriptError("actor record must start with: actor A# { ... }")
    if lines[-1] != "}":
        raise ActorScriptError("actor record block must end with }")

    index = parse_int(header.group(1))
    fields: Dict[str, object] = {"index": index}
    for line in lines[1:-1]:
        parts = line.split()
        key = parts[0]
        rest = parts[1:]
        if key == "mode":
            fields["actor_type"] = parse_int(rest[0])
        elif key == "room":
            fields["room"] = parse_int(rest[0])
        elif key == "position":
            kwargs = parse_args(rest)
            fields["x"] = parse_int(kwargs["x"])
            fields["y"] = parse_int(kwargs["y"])
        elif key == "frame":
            fields["frame"] = parse_int(rest[0])
        elif key == "variant":
            fields["variant"] = parse_int(rest[0])
        elif key == "hidden":
            fields["hidden"] = parse_int(rest[0])
        elif key == "delay":
            fields["delay"] = parse_int(rest[0])
        elif key == "cooldown":
            fields["cooldown"] = parse_int(rest[0])
        elif key == "frames":
            if len(rest) != 1 or ".." not in rest[0]:
                raise ActorScriptError("frames line must be: frames MIN..MAX")
            lo, hi = rest[0].split("..", 1)
            fields["frame_min"] = parse_int(lo)
            fields["frame_max"] = parse_int(hi)
        elif key == "script":
            fields["script"] = parse_int(rest[0])
        elif key == "saved_pc":
            fields["saved_pc"] = parse_int(rest[0])
        elif key == "restart":
            fields["restart"] = parse_int(rest[0])
        elif key == "loops":
            kwargs = parse_args(rest)
            fields["loop_a"] = parse_int(kwargs["a"])
            fields["loop_b"] = parse_int(kwargs["b"])
            fields["loop_c"] = parse_int(kwargs["c"])
        elif key == "contact":
            fields["contact"] = parse_int(rest[0])
        elif key == "vertical_marker":
            fields["vertical_marker"] = parse_int(rest[0])
        elif key == "activated":
            fields["activated"] = parse_int(rest[0])
        elif key == "raw_state":
            raw = bytes(parse_int(part) for part in rest)
            if len(raw) != 4:
                raise ActorScriptError("raw_state must contain exactly 4 bytes")
            fields["raw_state"] = raw
        else:
            raise ActorScriptError(f"unknown actor record field {key!r}")

    required = {
        "index", "actor_type", "room", "x", "y", "frame", "variant", "hidden",
        "delay", "cooldown", "frame_min", "frame_max", "script", "saved_pc",
        "loop_a", "loop_b", "loop_c", "restart", "contact", "vertical_marker",
        "activated", "raw_state",
    }
    missing = sorted(required - set(fields))
    if missing:
        raise ActorScriptError(f"missing actor record fields: {', '.join(missing)}")
    return ActorRecordIR(**fields)  # type: ignore[arg-type]
