"""Room payload parsing for Super Solvers: Challenge of the Ancient Empires.

A room record is 1000 bytes:

    +0x000..0x001  room preamble / metadata
    +0x002..0x2AD  terrain grid, 38×18 bytes
    +0x2AE..0x3E7  trailing payload, 314 bytes

The trailing payload is not random data. Static analysis of AEPROG.EXE points to
this structure:

    trailing +0x00  ten 3-byte platform/control triplets
    trailing +0x1E  payload directory / control records / compact3 sections

Anything still unknown is represented explicitly as an unknown section rather
than being drawn as a guessed object.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Literal

from ..constants import (
    LEVEL_PART_ACTOR_BLOCK_OFFSET,
    LEVEL_PART_ACTOR_BLOCK_SIZE,
    LEVEL_PART_HEADER_SIZE,
    ROOM_COLUMNS,
    ROOM_COUNT,
    ROOM_RECORD_SIZE,
    ROOM_ROWS,
    ROOM_SCREEN_HEIGHT_PX,
    ROOM_SCREEN_WIDTH_PX,
    ROOM_TERRAIN_OFFSET,
    ROOM_TILE_COUNT,
    RUNTIME_TILE_VISIBLE_X_BIAS,
)
from .conveyors import BeltKind, ConveyorRecord, ConveyorVisualRecord, DEFAULT_CONVEYOR_FLAGS
from .level_format import LevelPart, Room

PAYLOAD_DIRECTORY_OFFSET = 0x1E
PLATFORM_TRIPLET_COUNT = 10
PLATFORM_TRIPLET_SIZE = 3
ACTOR_TABLE_OFFSET = LEVEL_PART_ACTOR_BLOCK_OFFSET
ACTOR_TABLE_SIZE = LEVEL_PART_ACTOR_BLOCK_SIZE
ACTOR_RECORD_SIZE = 0x20
CONFIRMED_ACTOR_FRAME_NAMES = {
    0x00: "Ant",
    0x02: "Pill Projectile",
    0x08: "Bat",
    0x0F: "Praying Mantis",
    0x17: "Energy Orb",
    0x1B: "Fireball",
    0x20: "Pegasus Frog",
    0x2B: "Ladybug",
    0x2D: "Scarab",
    0x32: "Scorpion",
    0x37: "Spider",
    0x3B: "Neon Spider",
    0x3F: "Snake",
    0x42: "Flea",
    0x4A: "Caterpillar",
    0x50: "Sparkles",
}

# Exact-frame labels for secondary actors / projectiles.
# These are separate from the stable frame-range names above because they are
# often spawned as independent actor records (typically actor_type=1).
CONFIRMED_ACTOR_FRAME_LABELS = {
    0x02: "Pill Projectile",  # AE000:020:2
    0x07: "Pill Projectile",  # AE000:020:7
    0x17: "Energy Orb",       # AE000:021:0
    0x1B: "Fireball",         # AE000:021:4
    0x50: "Sparkles",         # AE000:022:37
}

PlatformOrientation = Literal["horizontal", "vertical", "unknown"]


@dataclass(frozen=True)
class PlatformTriplet:
    source_offset: int
    index: int
    flags: int
    x_raw: int
    y: int
    raw: bytes

    @property
    def active(self) -> bool:
        return self.raw != b"\x00\x00\x00"

    @property
    def visible(self) -> bool:
        """Whether this triplet is currently known to draw a moving platform.

        Original level 1 room 0 contains two 00-family triplets that do not
        appear in the game.  Treat them as hidden/unknown leftovers instead of
        rendering fake platforms.
        """
        return (self.flags & 0xF0) in {0x40, 0x60, 0x80, 0xA0}

    @property
    def orientation(self) -> PlatformOrientation:
        """Best current orientation model.

        Runtime records are not inferred from collision tile 0x07.  The EXE
        update routine treats 0x80-family records differently from the
        0x40/0x60 family; screenshots confirm that 0x80 and 0xA0 are visible
        vertical platform sprites, while 0x40/0x60 are horizontal.
        """
        high = self.flags & 0xF0
        if high in {0x80, 0xA0}:
            return "vertical"
        if high in {0x00, 0x20, 0x40, 0x60}:
            return "horizontal"
        return "unknown"

    @property
    def label(self) -> str:
        return f"plat[{self.index}] f={self.flags:02X} x={self.x_raw:02X} y={self.y:02X} {self.orientation}"


@dataclass(frozen=True)
class ObjectTableEntry:
    source_offset: int
    index: int
    x_raw: int
    y: int
    code: int
    raw: bytes

    @property
    def label(self) -> str:
        return f"obj[{self.index}] code={self.code:02X} x={self.x_raw:02X} y={self.y:02X}"


@dataclass
class Compact3Table:
    offset: int
    count: int
    entries: list[ObjectTableEntry]
    label: str = "compact3"


ANIMATED_DECOR_RECORD_SIZE = 12
ANIMATED_DECOR_MAX_COUNT = 16


@dataclass(frozen=True)
class AnimatedDecorRecord:
    """12-byte animated background decal record after the visual table.

    Confirmed in L09/R01: count=4 records draw the four torch-holder decals
    from AE001:027 frames 14..16.  The frame bytes are stored as sprite_index+1
    and the sequence is 0-terminated, usually ping-pong with duplicated frames
    to control speed (for example 0F 0F 10 10 11 11 10 10 00).
    """

    source_offset: int
    index: int
    phase: int
    x_raw: int
    y: int
    sequence_raw: bytes
    raw: bytes

    @property
    def sprite_sequence(self) -> list[int]:
        values: list[int] = []
        for value in self.sequence_raw:
            if value == 0:
                break
            # Runtime values are one-based resource subimage ids.
            values.append(max(0, value - 1))
        return values

    @property
    def preview_sprite_index(self) -> int:
        seq = self.sprite_sequence
        if not seq:
            return 0
        return seq[self.phase % len(seq)]

    @property
    def label(self) -> str:
        seq = ",".join(str(v) for v in self.sprite_sequence) or "-"
        return f"anim_decor[{self.index}] phase={self.phase} x={self.x_raw:02X} y={self.y:02X} seq={seq}"


@dataclass
class AnimatedDecorTable:
    offset: int
    count: int
    records: list[AnimatedDecorRecord]


@dataclass(frozen=True)
class LengthPrefixedControlRecord:
    index: int
    source_offset: int
    length: int
    raw: bytes

    @property
    def body(self) -> bytes:
        return self.raw[1:]

    @property
    def label(self) -> str:
        return f"ctrl[{self.index}] @{self.source_offset:02X} len={self.length} {self.raw.hex(' ')}"


@dataclass(frozen=True)
class ControlCommand:
    """Length-prefixed room command with the prefix stripped.

    The command body starts at raw[1:], keeping the length prefix separate from
    the command and its arguments.
    """

    record: LengthPrefixedControlRecord

    @property
    def body(self) -> bytes:
        return self.record.body

    @property
    def command(self) -> int | None:
        return self.body[0] if len(self.body) >= 1 else None

    @property
    def x_raw(self) -> int | None:
        return self.body[1] if len(self.body) >= 2 else None

    @property
    def y_raw(self) -> int | None:
        return self.body[2] if len(self.body) >= 3 else None

    @property
    def arg_a(self) -> int | None:
        return self.body[3] if len(self.body) >= 4 else None

    @property
    def arg_b(self) -> int | None:
        return self.body[4] if len(self.body) >= 5 else None

    @property
    def extra(self) -> bytes:
        return self.body[5:] if len(self.body) > 5 else b""

    @property
    def label(self) -> str:
        return f"cmd[{self.record.index}] @{self.record.source_offset:02X} body={self.body.hex(' ')}"


def control_commands(room: Room) -> list[ControlCommand]:
    directory = parse_exe_payload_directory(room)
    if not directory:
        return []
    return [ControlCommand(record) for record in directory.control_records]


def set_control_command_body(room: Room, index: int, body: bytes, *, allow_resize: bool = False) -> None:
    """Rewrite one length-prefixed control command body.

    By default this preserves the existing record length.  When ``allow_resize``
    is true the record may grow/shrink, which is needed for editor-side target
    lists such as ``P1,P2``.  The room payload has a fixed-size trailing area, so
    growth consumes zero padding after the structured payload and shrinkage adds
    zero padding back at the same boundary.
    """
    if not 1 <= len(body) <= 0xFE:
        raise ValueError("control body must be 1..254 bytes")
    directory = parse_exe_payload_directory(room)
    if directory is None or not 0 <= index < len(directory.control_records):
        raise ValueError(f"control record out of range: {index}")
    record = directory.control_records[index]
    old_body = record.body
    if len(body) == len(old_body):
        room.set_trailing_bytes(record.source_offset, [len(body) + 1])
        room.set_trailing_bytes(record.source_offset + 1, list(body))
        return
    if not allow_resize:
        raise ValueError(f"control body must stay {len(old_body)} bytes, got {len(body)}")

    data = bytearray(room.trailing)
    original_len = len(room.trailing)
    old_raw_len = record.length
    new_raw = bytes([len(body) + 1]) + bytes(body)
    delta = len(new_raw) - old_raw_len
    start = record.source_offset
    end = start + old_raw_len
    if delta > 0:
        data[start:end] = new_raw
        padding_start = _payload_padding_start(room) + delta
        _delete_padding_bytes_after_insert(data, padding_start, delta, original_len)
    else:
        data[start:end] = new_raw
        padding_start = _payload_padding_start(room) + delta
        padding_start = max(0, min(len(data), padding_start))
        data[padding_start:padding_start] = bytes(-delta)
        del data[original_len:]
    _replace_trailing(room, data)


def _control_count_selector_offset(data: bytes) -> int | None:
    base = PAYLOAD_DIRECTORY_OFFSET
    if base >= len(data):
        return None
    selector_offset = base + data[base] * 4 + 1
    if selector_offset >= len(data):
        return None
    return selector_offset


def add_control_command(room: Room, body: bytes) -> int:
    """Append a length-prefixed control/trigger command.

    The room format stores a selected count byte before the variable-length
    records.  Appending is safer than inserting in the middle because existing
    target slot references do not need to be renumbered.  The fixed 314-byte
    payload is preserved by consuming zero padding after the structured payload.
    """
    if not 1 <= len(body) <= 0xFE:
        raise ValueError("control body must be 1..254 bytes")
    directory = parse_exe_payload_directory(room)
    if directory is None:
        raise ValueError("room has no parseable payload directory")
    data = bytearray(room.trailing)
    selector_offset = _control_count_selector_offset(data)
    if selector_offset is None:
        raise ValueError("room has no control-count selector")
    count = data[selector_offset]
    records_end = directory.sections.records_end if directory.sections else None
    if records_end is None:
        # Fall back to walking the records again. This still allows controls to
        # be added to rooms that have no following compact sections.
        records_end, _records = _skip_length_prefixed_records(data, directory.variable_start, count)
    if records_end is None:
        raise ValueError("cannot find end of control record list")
    raw = bytes([len(body) + 1]) + bytes(body)
    if len(raw) > 255:
        raise ValueError("control record too long")
    insert_at = records_end
    original_len = len(room.trailing)
    padding_start = _payload_padding_start(room)
    data[selector_offset] = (count + 1) & 0xFF
    data[insert_at:insert_at] = raw
    shifted_padding_start = padding_start + len(raw) if padding_start >= insert_at else padding_start
    _delete_padding_bytes_after_insert(data, shifted_padding_start, len(raw), original_len)
    _replace_trailing(room, data)
    return count


def delete_control_command(room: Room, index: int) -> None:
    """Delete one control command and keep the fixed room payload size.

    This renumbers following C indices, so the GUI currently exposes it mainly
    for newly-added mistakes rather than as a default workflow.
    """
    directory = parse_exe_payload_directory(room)
    if directory is None or not 0 <= index < len(directory.control_records):
        raise ValueError(f"control record out of range: {index}")
    data = bytearray(room.trailing)
    selector_offset = _control_count_selector_offset(data)
    if selector_offset is None:
        raise ValueError("room has no control-count selector")
    record = directory.control_records[index]
    original_len = len(room.trailing)
    del data[record.source_offset:record.source_offset + record.length]
    data[selector_offset] = max(0, data[selector_offset] - 1)
    old_trailing = room.trailing
    room.trailing = bytes(data[:original_len - record.length])
    padding_start = _payload_padding_start(room)
    room.trailing = old_trailing
    padding_start = max(0, min(len(data), padding_start))
    data[padding_start:padding_start] = bytes(record.length)
    del data[original_len:]
    room.trailing = bytes(data)


@dataclass
class PayloadSections:
    records_end: int
    section_a: Compact3Table | None
    section_b_offset: int | None
    section_b_count: int
    section_b_records: list[bytes]
    section_c: Compact3Table | None
    visual: Compact3Table | None
    animated_decor: AnimatedDecorTable | None
    after_visual: int | None


@dataclass
class ExePayloadDirectory:
    base_offset: int
    directory_count: int
    selected_visual_index: int
    variable_start: int
    selected_table_offset: int | None
    control_records: list[LengthPrefixedControlRecord]
    sections: PayloadSections | None = None


@dataclass(frozen=True)
class ActorTableRecord:
    """Runtime actor record copied from the level-part actor table.

    AEPROG copies the first 0x2750 bytes of a difficulty part to DS:4374 and
    the following 0x0bb8 bytes to DS:b3ae.  DS:b3ae starts with a count byte;
    each record after that is 0x20 bytes.  The draw/update loops filter
    record[1] by the current zero-based room and use x/y/frame from offsets
    0x02/0x04/0x06.
    """

    index: int
    source_offset: int
    raw: bytes
    actor_type: int
    room_index: int
    x: int
    y: int
    frame: int
    frame_variant: int
    hidden: int
    delay: int
    cooldown: int
    frame_min: int
    frame_max: int
    script_offset: int
    saved_script_offset: int
    loop_counter_a: int
    loop_counter_b: int
    loop_counter_c: int
    restart_script_offset: int
    contact_behavior: int
    vertical_marker: int
    activated_flag: int
    runtime_tail: bytes

    @property
    def label(self) -> str:
        name = f"{self.confirmed_name} " if self.confirmed_name else ""
        return (
            f"actor[{self.index}] {name}room={self.room_index} x={self.x} y={self.y} "
            f"frame={self.frame:02X}:{self.frame_variant:02X} "
            f"range={self.frame_min:02X}-{self.frame_max:02X} hidden={self.hidden} "
            f"script={self.script_offset:04X} restart={self.restart_script_offset:04X}"
        )

    @property
    def confirmed_name(self) -> str | None:
        return CONFIRMED_ACTOR_FRAME_LABELS.get(self.frame) or CONFIRMED_ACTOR_FRAME_NAMES.get(self.frame_min)


def parse_actor_table(part) -> list[ActorTableRecord]:
    raw_part = getattr(part, "raw", b"")
    if len(raw_part) < ACTOR_TABLE_OFFSET + 1:
        return []
    table = raw_part[ACTOR_TABLE_OFFSET:ACTOR_TABLE_OFFSET + ACTOR_TABLE_SIZE]
    if not table:
        return []
    count = table[0]
    max_count = min(count, (len(table) - 1) // ACTOR_RECORD_SIZE)
    out: list[ActorTableRecord] = []
    for i in range(max_count):
        off = 1 + i * ACTOR_RECORD_SIZE
        rec = bytes(table[off:off + ACTOR_RECORD_SIZE])
        if len(rec) < ACTOR_RECORD_SIZE:
            break
        out.append(
            ActorTableRecord(
                index=i,
                source_offset=ACTOR_TABLE_OFFSET + off,
                raw=rec,
                actor_type=rec[0],
                room_index=rec[1],
                x=rec[2] | (rec[3] << 8),
                y=rec[4] | (rec[5] << 8),
                frame=rec[6],
                frame_variant=rec[7],
                hidden=rec[8],
                delay=rec[9],
                cooldown=rec[10],
                frame_min=rec[11],
                frame_max=rec[12],
                script_offset=rec[13] | (rec[14] << 8),
                saved_script_offset=rec[15] | (rec[16] << 8),
                loop_counter_a=rec[17] | (rec[18] << 8),
                loop_counter_b=rec[19] | (rec[20] << 8),
                loop_counter_c=rec[21] | (rec[22] << 8),
                restart_script_offset=rec[23] | (rec[24] << 8),
                contact_behavior=rec[25],
                vertical_marker=rec[26],
                activated_flag=rec[27],
                runtime_tail=rec[28:32],
            )
        )
    return out


def actor_records_for_room(part, room_index: int) -> list[ActorTableRecord]:
    return [record for record in parse_actor_table(part) if record.room_index == room_index]


def runtime_offset_for_room_cell(room_index: int, x: int, y: int) -> int:
    if not (0 <= room_index < ROOM_COUNT and 0 <= x < ROOM_COLUMNS and 0 <= y < ROOM_ROWS):
        raise ValueError(f"room tile out of range: room={room_index} x={x} y={y}")
    raw_x = x - RUNTIME_TILE_VISIBLE_X_BIAS
    if raw_x < 0:
        raise ValueError(f"runtime tile x {x} is before the visible room buffer origin")
    return LEVEL_PART_HEADER_SIZE + room_index * ROOM_RECORD_SIZE + ROOM_TERRAIN_OFFSET + y * ROOM_COLUMNS + raw_x


def room_cell_for_runtime_offset(offset: int) -> tuple[int, int, int] | None:
    if offset < LEVEL_PART_HEADER_SIZE:
        return None
    rel = offset - LEVEL_PART_HEADER_SIZE
    room_index = rel // ROOM_RECORD_SIZE
    if not 0 <= room_index < ROOM_COUNT:
        return None
    in_record = rel % ROOM_RECORD_SIZE
    terrain_rel = in_record - ROOM_TERRAIN_OFFSET
    if not 0 <= terrain_rel < ROOM_TILE_COUNT:
        return None
    raw_x = terrain_rel % ROOM_COLUMNS
    return room_index, raw_x + RUNTIME_TILE_VISIBLE_X_BIAS, terrain_rel // ROOM_COLUMNS


def tile_at_runtime_offset(part, offset: int) -> int | None:
    cell = room_cell_for_runtime_offset(offset)
    if cell is None:
        return None
    room_index, x, y = cell
    if not 0 <= x < ROOM_COLUMNS:
        return None
    return part.room(room_index).get(x, y)


def _actor_block(part) -> bytearray:
    raw_part = getattr(part, "raw", b"")
    block = bytearray(raw_part[ACTOR_TABLE_OFFSET:ACTOR_TABLE_OFFSET + ACTOR_TABLE_SIZE])
    if len(block) < ACTOR_TABLE_SIZE:
        block.extend(b"\x00" * (ACTOR_TABLE_SIZE - len(block)))
    return block


def _write_actor_block(part, block: bytearray) -> None:
    if len(block) != ACTOR_TABLE_SIZE:
        raise ValueError(f"actor block size changed: {len(block)} != {ACTOR_TABLE_SIZE}")
    part.set_part_bytes(ACTOR_TABLE_OFFSET, bytes(block))


def _actor_count(block: bytearray) -> int:
    return min(block[0] if block else 0, (ACTOR_TABLE_SIZE - 1) // ACTOR_RECORD_SIZE)


def _actor_record_offset(index: int) -> int:
    return 1 + index * ACTOR_RECORD_SIZE


def _read_actor_u16(block: bytearray, record_offset: int, field: int) -> int:
    return block[record_offset + field] | (block[record_offset + field + 1] << 8)


def _write_actor_u16(block: bytearray, record_offset: int, field: int, value: int) -> None:
    block[record_offset + field] = value & 0xFF
    block[record_offset + field + 1] = (value >> 8) & 0xFF


def _actor_script_used_end(block: bytearray) -> int:
    count = _actor_count(block)
    record_end = 1 + count * ACTOR_RECORD_SIZE
    last_nonzero = 0
    for idx, value in enumerate(block):
        if value:
            last_nonzero = idx + 1
    return max(record_end, last_nonzero)


def _actor_vm_size(block: bytes | bytearray, pc: int) -> int:
    if pc < 0 or pc >= len(block):
        return 0
    opcode = block[pc]
    sizes = {
        0x00: 1, 0x01: 3, 0x02: 3, 0x03: 1, 0x04: 5, 0x05: 5, 0x06: 5,
        0x07: 2, 0x08: 2, 0x09: 2, 0x0A: 2, 0x0B: 2, 0x0C: 3, 0x0D: 2,
        0x0E: 4, 0x0F: 4, 0x10: 5, 0x11: 1, 0x12: 1, 0x13: 3, 0x14: 3,
        0x15: 3, 0x16: 3, 0x17: 2, 0x18: 2, 0x19: 2, 0x1A: 2, 0x1B: 2,
    }
    return min(sizes.get(opcode, 1), max(1, len(block) - pc))


def _actor_s16(block: bytes | bytearray, offset: int) -> int:
    value = block[offset] | (block[offset + 1] << 8)
    return value - 0x10000 if value & 0x8000 else value


def _actor_write_s16(block: bytearray, offset: int, value: int) -> None:
    if not -32768 <= value <= 32767:
        raise ValueError(f"actor branch target is out of rel16 range: {value}")
    raw = value & 0xFFFF
    block[offset] = raw & 0xFF
    block[offset + 1] = (raw >> 8) & 0xFF


def _is_actor_padding_end(block: bytes | bytearray, pc: int) -> bool:
    return block[pc] == 0x00 and not any(block[pc + 1:pc + 8])


def _actor_entry_offsets(block: bytes | bytearray) -> list[int]:
    entries: set[int] = set()
    raw = bytearray(block)
    count = _actor_count(raw)
    record_end = 1 + count * ACTOR_RECORD_SIZE
    for index in range(count):
        rec = _actor_record_offset(index)
        for field in (0x0D, 0x0F, 0x17):
            value = _read_actor_u16(raw, rec, field)
            # saved_pc=0 is the common "no saved return" value.  More
            # generally, actor bytecode lives after the actor records, so values
            # inside the actor table are not script-space entry points.
            if record_end <= value < ACTOR_TABLE_SIZE:
                entries.add(value)
    return sorted(entries)


def _reachable_actor_instruction_offsets(block: bytes | bytearray, *, max_commands: int = 1200) -> list[int]:
    seen: set[int] = set()
    queue: deque[int] = deque(_actor_entry_offsets(block))
    while queue and len(seen) < max_commands:
        pc = queue.popleft()
        if pc < 0 or pc >= ACTOR_TABLE_SIZE or pc in seen:
            continue
        size = _actor_vm_size(block, pc)
        if size <= 0:
            continue
        seen.add(pc)
        opcode = block[pc]
        end = pc + size
        if _is_actor_padding_end(block, pc) or opcode == 0x03:
            continue
        if opcode in {0x01, 0x02} and size >= 3:
            target = end + _actor_s16(block, pc + 1)
            queue.append(target)
            if opcode == 0x02:
                queue.append(end)
            continue
        if opcode in {0x04, 0x05, 0x06} and size >= 5:
            queue.append(end + _actor_s16(block, pc + 1))
            queue.append(end)
            continue
        if 0x13 <= opcode <= 0x1B:
            queue.append(end)
            if end < ACTOR_TABLE_SIZE:
                queue.append(end + _actor_vm_size(block, end))
            continue
        if opcode in {0x00, 0x11}:
            # Yield/hide are runtime pauses, not hard script-stream endings
            # unless followed by padding.
            queue.append(end)
            continue
        queue.append(end)
    return sorted(seen)


@dataclass(frozen=True)
class _ActorBranchRef:
    source: int
    opcode: int
    size: int
    target: int


@dataclass(frozen=True)
class ActorScriptEntryPoint:
    actor_index: int
    field: str
    address: int


@dataclass(frozen=True)
class ActorScriptJumpReference:
    source: int
    opcode: int
    size: int
    target: int


@dataclass(frozen=True)
class ActorScriptActorReference:
    source: int
    opcode: int
    actor_index: int


@dataclass(frozen=True)
class ActorScriptSpaceInstruction:
    address: int
    opcode: int
    size: int
    raw: bytes
    branch_target: int | None = None
    referenced_actor: int | None = None
    padding_end: bool = False

    @property
    def next_address(self) -> int:
        return self.address + self.size


@dataclass(frozen=True)
class ActorScriptSpace:
    raw: bytes
    record_end: int
    used_end: int
    entry_points: list[ActorScriptEntryPoint]
    instructions: list[ActorScriptSpaceInstruction]
    jumps: list[ActorScriptJumpReference]
    actor_refs: list[ActorScriptActorReference]

    @property
    def instruction_by_address(self) -> dict[int, ActorScriptSpaceInstruction]:
        return {ins.address: ins for ins in self.instructions}


def _actor_branch_refs(block: bytes | bytearray) -> list[_ActorBranchRef]:
    refs: list[_ActorBranchRef] = []
    for pc in _reachable_actor_instruction_offsets(block):
        opcode = block[pc]
        size = _actor_vm_size(block, pc)
        if opcode in {0x01, 0x02} and size >= 3:
            refs.append(_ActorBranchRef(pc, opcode, size, pc + size + _actor_s16(block, pc + 1)))
        elif opcode in {0x04, 0x05, 0x06} and size >= 5:
            refs.append(_ActorBranchRef(pc, opcode, size, pc + size + _actor_s16(block, pc + 1)))
    return refs


def actor_script_space(part) -> ActorScriptSpace:
    """Analyze the shared actor VM bytecode space for one level part.

    Actor records only contain state and entry pointers.  The bytecode itself is
    one shared address space inside the actor block, so this view is the source
    of truth for cross-actor jumps, shared routines and set_actor_mode refs.
    """
    block = _actor_block(part)
    count = _actor_count(block)
    record_end = 1 + count * ACTOR_RECORD_SIZE
    used_end = _actor_script_used_end(block)
    field_names = {0x0D: "script_pc", 0x0F: "saved_pc", 0x17: "restart_pc"}
    entries: list[ActorScriptEntryPoint] = []
    for index in range(count):
        rec = _actor_record_offset(index)
        for field, name in field_names.items():
            value = _read_actor_u16(block, rec, field)
            if name == "saved_pc" and value == 0:
                continue
            if record_end <= value < ACTOR_TABLE_SIZE:
                entries.append(ActorScriptEntryPoint(index, name, value))

    instructions: list[ActorScriptSpaceInstruction] = []
    jumps: list[ActorScriptJumpReference] = []
    actor_refs: list[ActorScriptActorReference] = []
    for pc in _reachable_actor_instruction_offsets(block):
        size = _actor_vm_size(block, pc)
        if size <= 0:
            continue
        opcode = block[pc]
        raw = bytes(block[pc:pc + size])
        target: int | None = None
        ref_actor: int | None = None
        if opcode in {0x01, 0x02, 0x04, 0x05, 0x06} and size >= 3:
            target = pc + size + _actor_s16(block, pc + 1)
            jumps.append(ActorScriptJumpReference(pc, opcode, size, target))
        if opcode in {0x0A, 0x0B} and size >= 2:
            ref_actor = block[pc + 1]
            actor_refs.append(ActorScriptActorReference(pc, opcode, ref_actor))
        instructions.append(
            ActorScriptSpaceInstruction(
                pc,
                opcode,
                size,
                raw,
                branch_target=target,
                referenced_actor=ref_actor,
                padding_end=_is_actor_padding_end(block, pc),
            )
        )
    return ActorScriptSpace(bytes(block), record_end, used_end, entries, instructions, jumps, actor_refs)


def actor_script_space_reachable_addresses(space: ActorScriptSpace, start: int, *, max_commands: int = 240) -> list[int]:
    by_address = space.instruction_by_address
    seen: set[int] = set()
    queue: deque[int] = deque([start])
    while queue and len(seen) < max_commands:
        pc = queue.popleft()
        if pc in seen:
            continue
        ins = by_address.get(pc)
        if ins is None:
            continue
        seen.add(pc)
        if ins.padding_end or ins.opcode == 0x03:
            continue
        if ins.opcode == 0x01:
            if ins.branch_target is not None:
                queue.append(ins.branch_target)
            continue
        if ins.opcode == 0x02:
            if ins.branch_target is not None:
                queue.append(ins.branch_target)
            queue.append(ins.next_address)
            continue
        if ins.opcode in {0x04, 0x05, 0x06}:
            if ins.branch_target is not None:
                queue.append(ins.branch_target)
            queue.append(ins.next_address)
            continue
        if 0x13 <= ins.opcode <= 0x1B:
            queue.append(ins.next_address)
            guarded = by_address.get(ins.next_address)
            if guarded is not None:
                queue.append(guarded.next_address)
            continue
        queue.append(ins.next_address)
    return sorted(seen)


def _map_actor_offset_after_patch(offset: int, start: int, old_end: int, delta: int) -> int | None:
    if offset < start:
        return offset
    if offset >= old_end:
        return offset + delta
    return None


def _adjust_actor_branch_refs(block: bytearray, refs: list[_ActorBranchRef], start: int, old_end: int, delta: int) -> None:
    if not delta:
        return
    new_end = start + (old_end - start) + delta
    for ref in refs:
        if start <= ref.source < old_end:
            continue
        source = _map_actor_offset_after_patch(ref.source, start, old_end, delta)
        target = start if ref.target == start else _map_actor_offset_after_patch(ref.target, start, old_end, delta)
        if source is None or target is None:
            raise ValueError(
                f"actor branch at 0x{ref.source:04X} targets edited/deleted script bytes at 0x{ref.target:04X}"
            )
        if start <= source < new_end:
            continue
        if source < 0 or source + ref.size > ACTOR_TABLE_SIZE:
            continue
        if block[source] != ref.opcode:
            continue
        _actor_write_s16(block, source + 1, target - (source + ref.size))


def actor_script_region_length(part, actor: ActorTableRecord, *, max_bytes: int = 192) -> int:
    from .actor_scripts import actor_script_bytes, decode_actor_script

    decoded = decode_actor_script(part, actor, max_bytes=max_bytes, max_segments=16)
    if not decoded.commands:
        _start, data = actor_script_bytes(part, actor, limit=max_bytes)
        return 1 if data else 0
    return max(cmd.offset + len(cmd.raw) for cmd in decoded.commands)


def patch_actor_script_region(part, *, script_offset: int, old_length: int, new_bytes: bytes) -> None:
    """Replace a contiguous region in the shared actor script space."""
    if old_length < 0:
        raise ValueError("old script length cannot be negative")
    if script_offset < 0 or script_offset + old_length > ACTOR_TABLE_SIZE:
        raise ValueError(f"actor script-space region out of range: offset={script_offset:#x} len={old_length}")
    block = _actor_block(part)
    refs = _actor_branch_refs(block)
    delta = len(new_bytes) - old_length
    if delta > 0 and _actor_script_used_end(block) + delta > ACTOR_TABLE_SIZE:
        raise ValueError("actor script space has no room for the larger region")

    old_end = script_offset + old_length
    for ref in refs:
        unsafe_target = script_offset <= ref.target < old_end if not new_bytes else script_offset < ref.target < old_end
        if unsafe_target and not (script_offset <= ref.source < old_end):
            raise ValueError(
                f"actor branch at 0x{ref.source:04X} jumps into the edited script region at 0x{ref.target:04X}"
            )
    block[script_offset:old_end] = new_bytes
    if len(block) < ACTOR_TABLE_SIZE:
        block.extend(b"\x00" * (ACTOR_TABLE_SIZE - len(block)))
    elif len(block) > ACTOR_TABLE_SIZE:
        del block[ACTOR_TABLE_SIZE:]

    if delta:
        count = _actor_count(block)
        for index in range(count):
            rec = _actor_record_offset(index)
            for field in (0x0D, 0x0F, 0x17):
                value = _read_actor_u16(block, rec, field)
                if value and value >= old_end:
                    _write_actor_u16(block, rec, field, value + delta)
    _adjust_actor_branch_refs(block, refs, script_offset, old_end, delta)
    _write_actor_block(part, block)


def add_actor_record(
    part,
    *,
    room_index: int,
    x: int,
    y: int,
    actor_type: int,
    frame: int,
    frame_variant: int,
    hidden: int,
    frame_min: int,
    frame_max: int,
    script_bytes: bytes | None = b"\x00",
    script_offset: int | None = None,
    restart_script_offset: int | None = None,
    saved_script_offset: int = 0,
) -> int:
    """Append an actor instance to the global actor table.

    Actors are instance/state records.  Their behavior is not owned by the
    record; ``script_offset``/``restart_script_offset`` are pointers into the
    shared actor bytecode space for the whole level part.

    If ``script_offset`` is provided, the new actor reuses an existing script
    entry and no bytecode is appended.  If it is omitted, ``script_bytes`` is
    appended to the end of the shared script space and the new actor points at
    that fresh routine.
    """
    block = _actor_block(part)
    count = _actor_count(block)
    if count >= (ACTOR_TABLE_SIZE - 1) // ACTOR_RECORD_SIZE:
        raise ValueError("actor table is full")
    if script_offset is not None and not (0 <= script_offset < ACTOR_TABLE_SIZE):
        raise ValueError(f"script offset out of range: 0x{script_offset:04X}")
    if restart_script_offset is not None and not (0 <= restart_script_offset < ACTOR_TABLE_SIZE):
        raise ValueError(f"restart script offset out of range: 0x{restart_script_offset:04X}")
    if not (0 <= saved_script_offset < ACTOR_TABLE_SIZE):
        raise ValueError(f"saved script offset out of range: 0x{saved_script_offset:04X}")

    script_offsets = []
    for index in range(count):
        rec_existing = _actor_record_offset(index)
        for field in (0x0D, 0x0F, 0x17):
            value = _read_actor_u16(block, rec_existing, field)
            if value:
                script_offsets.append(value)
    new_record_end = 1 + (count + 1) * ACTOR_RECORD_SIZE
    first_script = min(script_offsets) if script_offsets else ACTOR_TABLE_SIZE
    used_end = _actor_script_used_end(block)

    # Inserting a new actor record can push the script stream forward if there
    # is no pre-existing gap between actor records and script bytes.  Existing
    # actor entry pointers must be adjusted, and an explicitly shared target
    # must be mapped through the same shift.
    if new_record_end > first_script:
        gap = new_record_end - first_script
        if used_end + gap > ACTOR_TABLE_SIZE:
            raise ValueError("no free actor record slot before script data")
        block[first_script + gap:used_end + gap] = bytes(block[first_script:used_end])
        block[first_script:first_script + gap] = b"\x00" * gap

        def map_shifted(value: int | None) -> int | None:
            if value is None:
                return None
            return value + gap if value >= first_script else value

        for index in range(count):
            rec_existing = _actor_record_offset(index)
            for field in (0x0D, 0x0F, 0x17):
                value = _read_actor_u16(block, rec_existing, field)
                if value and value >= first_script:
                    _write_actor_u16(block, rec_existing, field, value + gap)
        script_offset = map_shifted(script_offset)
        restart_script_offset = map_shifted(restart_script_offset)
        saved_script_offset = map_shifted(saved_script_offset) or 0
        used_end += gap

    if script_offset is None:
        script_bytes = b"\x00" if script_bytes is None else script_bytes
        script_offset = max(used_end, new_record_end)
        if script_offset + len(script_bytes) > ACTOR_TABLE_SIZE:
            raise ValueError("actor script block is full")
    else:
        script_bytes = None
    if restart_script_offset is None:
        restart_script_offset = script_offset

    rec = _actor_record_offset(count)
    block[rec:rec + ACTOR_RECORD_SIZE] = b"\x00" * ACTOR_RECORD_SIZE
    block[rec + 0x00] = actor_type & 0xFF
    block[rec + 0x01] = room_index & 0xFF
    _write_actor_u16(block, rec, 0x02, x & 0xFFFF)
    _write_actor_u16(block, rec, 0x04, y & 0xFFFF)
    block[rec + 0x06] = frame & 0xFF
    block[rec + 0x07] = frame_variant & 0xFF
    block[rec + 0x08] = hidden & 0xFF
    block[rec + 0x0B] = frame_min & 0xFF
    block[rec + 0x0C] = frame_max & 0xFF
    _write_actor_u16(block, rec, 0x0D, script_offset)
    _write_actor_u16(block, rec, 0x0F, saved_script_offset)
    _write_actor_u16(block, rec, 0x17, restart_script_offset)
    if script_bytes is not None:
        block[script_offset:script_offset + len(script_bytes)] = script_bytes
    block[0] = count + 1
    _write_actor_block(part, block)
    return count



def set_actor_record_placement(part, actor_index: int, *, room_index: int | None = None, x: int | None = None, y: int | None = None) -> None:
    """Update an actor instance's room/x/y placement bytes in the global actor table."""
    block = _actor_block(part)
    count = _actor_count(block)
    if not 0 <= actor_index < count:
        raise ValueError(f"actor index out of range: {actor_index}")
    rec = _actor_record_offset(actor_index)
    if room_index is not None:
        if not 0 <= room_index < ROOM_COUNT:
            raise ValueError(f"actor room out of range: {room_index}")
        block[rec + 0x01] = room_index & 0xFF
    if x is not None:
        if not 0 <= x <= 0xFFFF:
            raise ValueError(f"actor x out of range: {x}")
        _write_actor_u16(block, rec, 0x02, x)
    if y is not None:
        if not 0 <= y <= 0xFFFF:
            raise ValueError(f"actor y out of range: {y}")
        _write_actor_u16(block, rec, 0x04, y)
    _write_actor_block(part, block)

def set_actor_record_flags(part, actor_index: int, *, frame_variant: int | None = None, hidden: int | None = None) -> None:
    block = _actor_block(part)
    count = _actor_count(block)
    if not 0 <= actor_index < count:
        raise ValueError(f"actor index out of range: {actor_index}")
    rec = _actor_record_offset(actor_index)
    if frame_variant is not None:
        block[rec + 0x07] = frame_variant & 0xFF
    if hidden is not None:
        block[rec + 0x08] = hidden & 0xFF
    _write_actor_block(part, block)


def _actor_refs_to_index(block: bytes | bytearray, actor_index: int) -> list[int]:
    refs: list[int] = []
    for pc in _reachable_actor_instruction_offsets(block):
        opcode = block[pc]
        size = _actor_vm_size(block, pc)
        if opcode in {0x0A, 0x0B} and size >= 2 and block[pc + 1] == actor_index:
            refs.append(pc)
    return refs


def _rewrite_actor_refs_after_delete(block: bytearray, actor_index: int) -> None:
    for pc in _reachable_actor_instruction_offsets(block):
        opcode = block[pc]
        size = _actor_vm_size(block, pc)
        if opcode not in {0x0A, 0x0B} or size < 2:
            continue
        ref = block[pc + 1]
        if ref >= 0x80:
            continue
        if ref == actor_index:
            raise ValueError(f"script at 0x{pc:04X} still references deleted actor A{actor_index}")
        if ref > actor_index:
            block[pc + 1] = ref - 1


def delete_actor_record(
    part,
    actor_index: int,
    *,
    script_offset: int | None = None,
    script_length: int = 0,
    delete_script_region: bool = False,
    neutralize_actor_refs: bool = False,
) -> None:
    block = _actor_block(part)
    count = _actor_count(block)
    if not 0 <= actor_index < count:
        raise ValueError(f"actor index out of range: {actor_index}")

    rec = _actor_record_offset(actor_index)
    actor_script = _read_actor_u16(block, rec, 0x0D)
    if script_offset is not None and script_offset != actor_script:
        raise ValueError("selected actor script offset changed; reload actor data before deleting")

    # The actor record is an instance/state object; the bytecode belongs to the
    # shared actor script space.  Deleting an actor must therefore remove stale
    # references to the actor index, but it must not assume that script_pc owns a
    # private byte range.
    script_start = actor_script if script_offset is None else script_offset
    script_end = script_start + max(0, script_length)
    refs_to_deleted = _actor_refs_to_index(block, actor_index)
    if refs_to_deleted and not neutralize_actor_refs:
        refs = ", ".join(f"0x{pc:04X}" for pc in refs_to_deleted[:8])
        more = "..." if len(refs_to_deleted) > 8 else ""
        raise ValueError(
            f"actor A{actor_index} is still referenced by set_actor_mode instructions at {refs}{more}; "
            "remove/retarget those references first, or use an explicit force-neutralize action"
        )
    if refs_to_deleted:
        for ref_pc in refs_to_deleted:
            # set_actor_mode_* is a 2-byte side-effect aimed at this actor.
            # Replacing it with two yields preserves script layout while removing
            # a stale reference before actor indexes are compacted.  This is only
            # used for an explicit force-neutralize delete; plain actor deletion
            # must not silently rewrite shared script space.
            block[ref_pc:ref_pc + 2] = b"\x00\x00"
        _write_actor_block(part, block)

    shared_script = False
    if delete_script_region and script_length > 0:
        for index in range(count):
            if index == actor_index:
                continue
            other_rec = _actor_record_offset(index)
            for field in (0x0D, 0x0F, 0x17):
                value = _read_actor_u16(block, other_rec, field)
                if script_start <= value < script_end:
                    shared_script = True
                    break
            if shared_script:
                break

    if delete_script_region and script_length > 0 and not shared_script:
        if script_offset is None:
            script_offset = actor_script
        patch_actor_script_region(part, script_offset=script_offset, old_length=script_length, new_bytes=b"")
        block = _actor_block(part)

    records_end = 1 + count * ACTOR_RECORD_SIZE
    rec_start = _actor_record_offset(actor_index)
    rec_end = rec_start + ACTOR_RECORD_SIZE
    block[rec_start:records_end - ACTOR_RECORD_SIZE] = block[rec_end:records_end]
    block[records_end - ACTOR_RECORD_SIZE:records_end] = b"\x00" * ACTOR_RECORD_SIZE
    block[0] = count - 1
    _rewrite_actor_refs_after_delete(block, actor_index)
    _write_actor_block(part, block)


@dataclass(frozen=True)
class RoomTransitionLinks:
    """One-based room links used when the player exits the visible screen."""

    room_index: int
    left: int
    right: int
    up: int
    down: int

    @property
    def label(self) -> str:
        def fmt(value: int) -> str:
            return "-" if value == 0 else str(value - 1)

        return f"L={fmt(self.left)} R={fmt(self.right)} U={fmt(self.up)} D={fmt(self.down)}"


def room_transition_links(part) -> list[RoomTransitionLinks]:
    raw = bytearray(getattr(part, "raw", b""))
    header = getattr(part, "header", b"")
    if header:
        raw[:len(header)] = header
    raw_part = bytes(raw)
    if len(raw_part) < 0x42:
        return []
    # AEPROG copies the level-part payload to DS:4374 with the two-byte level
    # magic/preamble skipped.  The four 10-byte link arrays are then addressed
    # from DS:438c/4396/43a0/43aa for left/right/up/down respectively.
    left = raw_part[0x1A:0x24]
    right = raw_part[0x24:0x2E]
    up = raw_part[0x2E:0x38]
    down = raw_part[0x38:0x42]
    count = min(len(left), len(right), len(up), len(down))
    return [
        RoomTransitionLinks(i, left[i], right[i], up[i], down[i])
        for i in range(count)
    ]


def transition_links_for_room(part, room_index: int) -> RoomTransitionLinks | None:
    links = room_transition_links(part)
    if 0 <= room_index < len(links):
        return links[room_index]
    return None



def _payload_xy_on_screen(x_raw: int, y: int, *, margin: int = 24) -> bool:
    x = x_raw * 2
    return -margin <= x <= ROOM_SCREEN_WIDTH_PX + margin and -margin <= y <= ROOM_SCREEN_HEIGHT_PX + margin


CONVEYOR_DIRECTORY_OFFSET = PAYLOAD_DIRECTORY_OFFSET
CONVEYOR_VISUAL_RECORD_SIZE = 4


def parse_conveyor_visual_records(room: Room) -> list[ConveyorVisualRecord]:
    """Read CV records from the room payload directory header.

    These four-byte records are separate from terrain tile codes 0x0F/0x1F:
    the terrain is the physical scrolling footprint, while the CV record is the
    visible belt object drawn by the game.
    """
    data = room.trailing
    base = CONVEYOR_DIRECTORY_OFFSET
    if base >= len(data):
        return []
    count = data[base]
    if count > 32 or base + 1 + count * CONVEYOR_VISUAL_RECORD_SIZE > len(data):
        return []
    out: list[ConveyorVisualRecord] = []
    for index in range(count):
        off = base + 1 + index * CONVEYOR_VISUAL_RECORD_SIZE
        raw = bytes(data[off:off + CONVEYOR_VISUAL_RECORD_SIZE])
        if len(raw) < CONVEYOR_VISUAL_RECORD_SIZE:
            break
        x_raw, y, code, props = raw
        out.append(ConveyorVisualRecord(off, index, x_raw, y, code, props, raw))
    return out


def _replace_trailing(room: Room, data: bytearray) -> None:
    room.trailing = bytes(data[:len(room.trailing)])


def set_conveyor_visual_record(room: Room, index: int, *, x_raw: int, y: int, code: int, props: int) -> None:
    records = parse_conveyor_visual_records(room)
    if not 0 <= index < len(records):
        raise ValueError(f"CV index out of range: {index}")
    off = records[index].source_offset
    room.set_trailing_bytes(off, [x_raw, y, code, props])


def _payload_padding_start(room: Room) -> int:
    directory = parse_exe_payload_directory(room)
    if directory and directory.sections:
        if directory.sections.animated_decor is not None:
            table = directory.sections.animated_decor
            return table.offset + 1 + table.count * ANIMATED_DECOR_RECORD_SIZE
        if directory.sections.after_visual is not None:
            return directory.sections.after_visual
    return len(room.trailing)


def _delete_padding_bytes_after_insert(data: bytearray, start: int, size: int, original_len: int) -> None:
    # Prefer consuming explicit zero padding right after the structured payload.
    # This avoids losing arbitrary non-zero bytes at the very end of the fixed
    # room record.
    start = max(0, min(len(data) - size, start))
    for off in range(start, max(start, len(data) - size + 1)):
        if data[off:off + size] == b"\x00" * size:
            del data[off:off + size]
            return
    del data[original_len:]


def add_conveyor_visual_record(room: Room, *, x_raw: int, y: int, code: int, props: int = 0x07) -> int:
    data = bytearray(room.trailing)
    base = CONVEYOR_DIRECTORY_OFFSET
    count = data[base]
    insert_at = base + 1 + count * CONVEYOR_VISUAL_RECORD_SIZE
    if count >= 32 or insert_at + CONVEYOR_VISUAL_RECORD_SIZE > len(data):
        raise ValueError("no room for another CV record")
    padding_start = _payload_padding_start(room)
    original_len = len(room.trailing)
    data[base] = count + 1
    data[insert_at:insert_at] = bytes([x_raw & 0xFF, y & 0xFF, code & 0xFF, props & 0xFF])
    # If padding was after the insert point, it moved by four bytes.
    shifted_padding_start = padding_start + CONVEYOR_VISUAL_RECORD_SIZE if padding_start >= insert_at else padding_start
    _delete_padding_bytes_after_insert(data, shifted_padding_start, CONVEYOR_VISUAL_RECORD_SIZE, original_len)
    _replace_trailing(room, data)
    return count


def delete_conveyor_visual_record(room: Room, index: int) -> None:
    records = parse_conveyor_visual_records(room)
    if not 0 <= index < len(records):
        raise ValueError(f"CV index out of range: {index}")
    original_len = len(room.trailing)
    data = bytearray(room.trailing)
    base = CONVEYOR_DIRECTORY_OFFSET
    off = records[index].source_offset
    del data[off:off + CONVEYOR_VISUAL_RECORD_SIZE]
    data[base] = max(0, data[base] - 1)
    # Temporarily parse the shortened structured payload to find where the new
    # padding should begin, then insert zero padding there and keep fixed size.
    old_trailing = room.trailing
    room.trailing = bytes(data[:original_len - CONVEYOR_VISUAL_RECORD_SIZE])
    padding_start = _payload_padding_start(room)
    room.trailing = old_trailing
    padding_start = max(0, min(len(data), padding_start))
    data[padding_start:padding_start] = b"\x00" * CONVEYOR_VISUAL_RECORD_SIZE
    del data[original_len:]
    room.trailing = bytes(data)


def first_conveyor_visual_touching(room: Room, cells: set[tuple[int, int]]) -> ConveyorVisualRecord | None:
    for record in parse_conveyor_visual_records(room):
        if record.cells & cells:
            return record
    return None


def cv_geometry_to_raw(start_x: int, y: int, length: int) -> tuple[int, int, int]:
    x_raw = max(0, min(0xFF, start_x * 4 + 2))
    y_raw = max(0, min(0xFF, y * 8 + 12))
    code = max(0, min(0xFF, length - 2))
    return x_raw, y_raw, code


def parse_conveyor_records(room: Room) -> list[ConveyorRecord]:
    """Read visible/runtime conveyor records from the first ten room triplets.

    Older editor builds inferred visible belts from terrain tile codes 0x0F/0x1F.
    Testing in the real game shows that is only the logical/physics side: adding
    those terrain bytes creates an invisible belt.  The visible belt object lives
    in the same ten 3-byte payload slots that the EXE iterates at room+0x2AC.

    The low nibble must be non-zero; it is the animation/state counter used by
    the EXE.  A loose on-screen coordinate filter avoids treating unrelated or
    unused payload bytes in placeholder rooms as editable belts.
    """
    out: list[ConveyorRecord] = []
    data = room.trailing
    for index in range(PLATFORM_TRIPLET_COUNT):
        off = index * PLATFORM_TRIPLET_SIZE
        raw = data[off:off + PLATFORM_TRIPLET_SIZE]
        if len(raw) < PLATFORM_TRIPLET_SIZE or raw == b"\x00\x00\x00":
            continue
        flags, x_raw, y = raw
        if not (flags & 0x0F):
            continue
        if not _payload_xy_on_screen(x_raw, y):
            continue
        out.append(ConveyorRecord(off, index, flags, x_raw, y, bytes(raw)))
    return out


def first_free_runtime_triplet_slot(room: Room) -> int | None:
    """Return the first empty 3-byte runtime object slot, if any."""
    data = room.trailing
    for index in range(PLATFORM_TRIPLET_COUNT):
        off = index * PLATFORM_TRIPLET_SIZE
        raw = data[off:off + PLATFORM_TRIPLET_SIZE]
        if len(raw) == PLATFORM_TRIPLET_SIZE and raw == b"\x00\x00\x00":
            return index
    return None


def set_conveyor_record(room: Room, slot: int, *, kind: BeltKind, x_raw: int, y: int) -> None:
    """Write one visible/runtime conveyor record into a room triplet slot."""
    if not 0 <= slot < PLATFORM_TRIPLET_COUNT:
        raise ValueError(f"conveyor slot out of range: {slot}")
    flags = DEFAULT_CONVEYOR_FLAGS[kind]
    room.set_trailing_bytes(slot * PLATFORM_TRIPLET_SIZE, [flags, x_raw, y])


def move_conveyor_record(room: Room, slot: int, *, x_raw: int, y: int) -> None:
    """Move an existing visible/runtime conveyor record without changing flags."""
    if not 0 <= slot < PLATFORM_TRIPLET_COUNT:
        raise ValueError(f"conveyor slot out of range: {slot}")
    off = slot * PLATFORM_TRIPLET_SIZE
    if len(room.trailing[off:off + PLATFORM_TRIPLET_SIZE]) < PLATFORM_TRIPLET_SIZE:
        raise ValueError(f"conveyor slot out of range: {slot}")
    room.set_trailing_bytes(off + 1, [x_raw, y])


def clear_runtime_triplet_slot(room: Room, slot: int) -> None:
    """Clear one of the ten 3-byte platform/conveyor runtime slots."""
    if not 0 <= slot < PLATFORM_TRIPLET_COUNT:
        raise ValueError(f"runtime slot out of range: {slot}")
    room.set_trailing_bytes(slot * PLATFORM_TRIPLET_SIZE, [0, 0, 0])

def parse_platform_triplets(room: Room) -> list[PlatformTriplet]:
    """Read the ten platform/control records at room+0x2AC."""
    out: list[PlatformTriplet] = []
    data = room.trailing
    for index in range(PLATFORM_TRIPLET_COUNT):
        off = index * PLATFORM_TRIPLET_SIZE
        raw = data[off:off + PLATFORM_TRIPLET_SIZE]
        if len(raw) < PLATFORM_TRIPLET_SIZE:
            break
        flags, x, y = raw
        if raw == b"\x00\x00\x00":
            continue
        # The first ten payload triplets are runtime platform/control slots.
        # Do not reinterpret low-nibble records as belts: visible belts are CV
        # records in the payload directory header, while 0x0F/0x1F tiles are
        # only the physics/scrolling footprint. Writing a low-nibble triplet can
        # show up in the real game as a moving platform.
        out.append(PlatformTriplet(off, index, flags, x, y, bytes(raw)))
    return out


def parse_counted_compact3_at(room: Room, off: int, *, max_count: int = 32, label: str = "compact3") -> Compact3Table | None:
    data = room.trailing
    if off < 0 or off >= len(data):
        return None
    count = data[off]
    if not 0 <= count <= max_count:
        return None
    start = off + 1
    end = start + count * 3
    if end > len(data):
        return None
    entries: list[ObjectTableEntry] = []
    for i in range(count):
        raw = bytes(data[start + i * 3:start + i * 3 + 3])
        entries.append(ObjectTableEntry(start + i * 3, i, raw[0], raw[1], raw[2], raw))
    return Compact3Table(off, count, entries, label)


def _skip_length_prefixed_records(data: bytes, ptr: int, count: int) -> tuple[int | None, list[LengthPrefixedControlRecord]]:
    records: list[LengthPrefixedControlRecord] = []
    for idx in range(count):
        if ptr >= len(data):
            return None, records
        length = data[ptr]
        if length <= 0:
            return ptr, records
        end = ptr + length
        if end > len(data):
            return None, records
        records.append(LengthPrefixedControlRecord(idx, ptr, length, bytes(data[ptr:end])))
        ptr = end
    return ptr, records


def parse_animated_decor_table_at(room: Room, off: int, *, max_count: int = ANIMATED_DECOR_MAX_COUNT) -> AnimatedDecorTable | None:
    """Parse the counted animated-decor table after the static visual table.

    Empty rooms often just have zero padding at this offset, so count=0 is
    treated as no table.  Non-empty tables are conservative: every 12-byte
    record must fit before the room-boundary runtime marker area and end with a zero sequence
    terminator.
    """
    data = room.trailing
    if off < 0 or off >= len(data) - 3:
        return None
    count = data[off]
    if count == 0:
        return None
    if not 0 < count <= max_count:
        return None
    start = off + 1
    end = start + count * ANIMATED_DECOR_RECORD_SIZE
    # Preserve the room-boundary runtime pickup area at the end of the record.
    if end > len(data) - 3:
        return None
    records: list[AnimatedDecorRecord] = []
    for i in range(count):
        rec_off = start + i * ANIMATED_DECOR_RECORD_SIZE
        raw = bytes(data[rec_off:rec_off + ANIMATED_DECOR_RECORD_SIZE])
        if len(raw) != ANIMATED_DECOR_RECORD_SIZE or raw[-1] != 0:
            return None
        seq = raw[3:]
        # At least one frame before the terminator; values should be small
        # theme-bank subimage ids, but do not over-constrain while RE is ongoing.
        if not any(seq[:-1]):
            return None
        records.append(AnimatedDecorRecord(rec_off, i, raw[0], raw[1], raw[2], seq, raw))
    return AnimatedDecorTable(off, count, records)


def _parse_record12_section(data: bytes, off: int, *, max_count: int = 16) -> tuple[int | None, int, list[bytes], int | None]:
    if off < 0 or off >= len(data):
        return None, 0, [], None
    count = data[off]
    if not 0 <= count <= max_count:
        return off, count, [], None
    start = off + 1
    end = start + count * 12
    if end > len(data):
        return off, count, [], None
    records = [bytes(data[start + i * 12:start + (i + 1) * 12]) for i in range(count)]
    return off, count, records, end


def parse_exe_payload_directory(room: Room) -> ExePayloadDirectory | None:
    """Parse the EXE-style directory at trailing+0x1E.

    Best current model from AEPROG:
      * base = current_room + 0x2CA = trailing + 0x1E
      * base[0] is a small directory count / mode selector
      * selected_record_count = base[base[0] * 4 + 1]
      * length-prefixed records start at base + base[0] * 4 + 2
      * after these records, the EXE walks compact3, record12, compact3,
        compact3. The last compact3 is the main visual table.
    """
    data = room.trailing
    base = PAYLOAD_DIRECTORY_OFFSET
    if base >= len(data):
        return None
    directory_count = data[base]
    selector_offset = base + directory_count * 4 + 1
    variable_start = base + directory_count * 4 + 2
    if selector_offset >= len(data) or variable_start > len(data):
        return None
    selected_index = data[selector_offset]

    records_end, records = _skip_length_prefixed_records(data, variable_start, selected_index)
    if records_end is None:
        return ExePayloadDirectory(base, directory_count, selected_index, variable_start, None, records, None)

    ptr = records_end
    section_a = parse_counted_compact3_at(room, ptr, max_count=32, label="section_a")
    if section_a is None:
        return ExePayloadDirectory(base, directory_count, selected_index, variable_start, ptr, records, None)
    ptr = section_a.offset + 1 + section_a.count * 3

    section_b_offset, section_b_count, section_b_records, ptr2 = _parse_record12_section(data, ptr, max_count=16)
    if ptr2 is None:
        sections = PayloadSections(records_end, section_a, section_b_offset, section_b_count, section_b_records, None, None, None, None)
        return ExePayloadDirectory(base, directory_count, selected_index, variable_start, ptr, records, sections)
    ptr = ptr2

    section_c = parse_counted_compact3_at(room, ptr, max_count=32, label="section_c")
    if section_c is None:
        sections = PayloadSections(records_end, section_a, section_b_offset, section_b_count, section_b_records, None, None, None, None)
        return ExePayloadDirectory(base, directory_count, selected_index, variable_start, ptr, records, sections)
    ptr = section_c.offset + 1 + section_c.count * 3

    visual = parse_counted_compact3_at(room, ptr, max_count=32, label="visual")
    after_visual = visual.offset + 1 + visual.count * 3 if visual is not None else None
    animated_decor = parse_animated_decor_table_at(room, after_visual) if after_visual is not None else None
    sections = PayloadSections(records_end, section_a, section_b_offset, section_b_count, section_b_records, section_c, visual, animated_decor, after_visual)
    return ExePayloadDirectory(base, directory_count, selected_index, variable_start, ptr, records, sections)




def section_a_symbol_table(room: Room) -> Compact3Table | None:
    """Return section_a, the compact3 table of event09 symbol buttons/emitters."""
    directory = parse_exe_payload_directory(room)
    if directory and directory.sections and directory.sections.section_a is not None:
        return directory.sections.section_a
    return None


def set_section_a_symbol_entry(room: Room, index: int, *, x_raw: int, y: int, code: int) -> None:
    table = section_a_symbol_table(room)
    if table is None or not 0 <= index < len(table.entries):
        raise ValueError(f"symbol index out of range: {index}")
    off = table.entries[index].source_offset
    room.set_trailing_bytes(off, [x_raw & 0xFF, y & 0xFF, code & 0xFF])


def add_section_a_symbol_entry(room: Room, *, x_raw: int, y: int, code: int) -> int:
    table = section_a_symbol_table(room)
    if table is None:
        raise ValueError("room has no editable symbol table")
    if table.count >= 32:
        raise ValueError("symbol table is full")
    original_len = len(room.trailing)
    data = bytearray(room.trailing)
    insert_at = table.offset + 1 + table.count * 3
    data[table.offset] = table.count + 1
    data[insert_at:insert_at] = bytes([x_raw & 0xFF, y & 0xFF, code & 0xFF])
    padding_start = _payload_padding_start(room)
    shifted_padding_start = padding_start + 3 if padding_start >= insert_at else padding_start
    _delete_padding_bytes_after_insert(data, shifted_padding_start, 3, original_len)
    _replace_trailing(room, data)
    return table.count


def delete_section_a_symbol_entry(room: Room, index: int) -> None:
    table = section_a_symbol_table(room)
    if table is None or not 0 <= index < len(table.entries):
        raise ValueError(f"symbol index out of range: {index}")
    original_len = len(room.trailing)
    data = bytearray(room.trailing)
    off = table.entries[index].source_offset
    del data[off:off + 3]
    data[table.offset] = max(0, data[table.offset] - 1)
    old_trailing = room.trailing
    room.trailing = bytes(data[:original_len - 3])
    padding_start = _payload_padding_start(room)
    room.trailing = old_trailing
    padding_start = max(0, min(len(data), padding_start))
    data[padding_start:padding_start] = b"\x00" * 3
    del data[original_len:]
    room.trailing = bytes(data)


def green_block_footprint_cells(raw_x: int, raw_y: int) -> set[tuple[int, int]]:
    """Invisible-solid (0x07) cells a green block occupies, per AEPROG 0x3132.

    The original fills a 6x2 region whose top-left cell is
    ``col = raw_x // 4 - 1`` (``raw_x`` is half-resolution, so /4 == /8 px) and
    ``row = raw_y // 8 - 1``.  Shared by the runtime collision build and the
    editor footprint preview so both stay in step with the EXE.
    """
    col = raw_x // 4 - 1
    row = raw_y // 8 - 1
    return {
        (col + dx, row + dy)
        for dy in range(2)
        for dx in range(6)
        if 0 <= col + dx < ROOM_COLUMNS and 0 <= row + dy < ROOM_ROWS
    }


def record12_green_block_records(room: Room) -> tuple[int | None, list[bytes]]:
    """Return the green-block record12 offset and records for editor support."""
    directory = parse_exe_payload_directory(room)
    if not directory or not directory.sections:
        return None, []
    return directory.sections.section_b_offset, list(directory.sections.section_b_records)


def set_record12_green_block(room: Room, index: int, raw: bytes) -> None:
    offset, records = record12_green_block_records(room)
    if offset is None or not 0 <= index < len(records):
        raise ValueError(f"green block index out of range: {index}")
    if len(raw) != 12:
        raise ValueError("green block record must be exactly 12 bytes")
    room.set_trailing_bytes(offset + 1 + index * 12, list(raw))


def add_record12_green_block(room: Room, raw: bytes) -> int:
    offset, records = record12_green_block_records(room)
    if offset is None:
        raise ValueError("room has no editable green block table")
    if len(raw) != 12:
        raise ValueError("green block record must be exactly 12 bytes")
    if len(records) >= 16:
        raise ValueError("green block table is full")
    original_len = len(room.trailing)
    data = bytearray(room.trailing)
    insert_at = offset + 1 + len(records) * 12
    data[offset] = len(records) + 1
    data[insert_at:insert_at] = raw
    padding_start = _payload_padding_start(room)
    shifted_padding_start = padding_start + 12 if padding_start >= insert_at else padding_start
    _delete_padding_bytes_after_insert(data, shifted_padding_start, 12, original_len)
    _replace_trailing(room, data)
    return len(records)


def delete_record12_green_block(room: Room, index: int) -> None:
    offset, records = record12_green_block_records(room)
    if offset is None or not 0 <= index < len(records):
        raise ValueError(f"green block index out of range: {index}")
    original_len = len(room.trailing)
    data = bytearray(room.trailing)
    off = offset + 1 + index * 12
    del data[off:off + 12]
    data[offset] = max(0, data[offset] - 1)
    old_trailing = room.trailing
    room.trailing = bytes(data[:original_len - 12])
    padding_start = _payload_padding_start(room)
    room.trailing = old_trailing
    padding_start = max(0, min(len(data), padding_start))
    data[padding_start:padding_start] = b"\x00" * 12
    del data[original_len:]
    room.trailing = bytes(data)

def animated_decor_table(room: Room) -> AnimatedDecorTable | None:
    """Return animated background decals stored after the visual table."""
    directory = parse_exe_payload_directory(room)
    if directory and directory.sections and directory.sections.animated_decor is not None:
        return directory.sections.animated_decor
    return None


def set_animated_decor_record(room: Room, index: int, *, phase: int, x_raw: int, y: int, sequence: bytes | None = None) -> None:
    table = animated_decor_table(room)
    if table is None or not 0 <= index < len(table.records):
        raise ValueError(f"animated decor index out of range: {index}")
    old = table.records[index]
    seq = bytes(sequence) if sequence is not None else old.sequence_raw
    if len(seq) != 9 or seq[-1] != 0:
        raise ValueError("animated decor sequence must be 9 bytes and end with 00")
    room.set_trailing_bytes(old.source_offset, [phase & 0xFF, x_raw & 0xFF, y & 0xFF, *seq])


def _animated_decor_insert_offset(room: Room) -> int:
    directory = parse_exe_payload_directory(room)
    if not directory or not directory.sections or directory.sections.after_visual is None:
        raise ValueError("room has no visual table to anchor animated decor")
    table = directory.sections.animated_decor
    if table is not None:
        return table.offset + 1 + table.count * ANIMATED_DECOR_RECORD_SIZE
    return directory.sections.after_visual + 1


def add_animated_decor_record(room: Room, *, phase: int, x_raw: int, y: int, sequence: bytes) -> int:
    directory = parse_exe_payload_directory(room)
    if not directory or not directory.sections or directory.sections.after_visual is None:
        raise ValueError("room has no editable animated decor area")
    if len(sequence) != 9 or sequence[-1] != 0:
        raise ValueError("animated decor sequence must be 9 bytes and end with 00")
    table = directory.sections.animated_decor
    count = 0 if table is None else table.count
    if count >= ANIMATED_DECOR_MAX_COUNT:
        raise ValueError("animated decor table is full")
    original_len = len(room.trailing)
    data = bytearray(room.trailing)
    count_off = directory.sections.after_visual if table is None else table.offset
    insert_at = count_off + 1 + count * ANIMATED_DECOR_RECORD_SIZE
    data[count_off] = count + 1
    data[insert_at:insert_at] = bytes([phase & 0xFF, x_raw & 0xFF, y & 0xFF]) + bytes(sequence)
    padding_start = _payload_padding_start(room)
    # If there was no table, the old zero count byte becomes real structure;
    # only the inserted 12-byte record needs to be paid for from padding.
    shifted_padding_start = padding_start + ANIMATED_DECOR_RECORD_SIZE if padding_start >= insert_at else padding_start
    _delete_padding_bytes_after_insert(data, shifted_padding_start, ANIMATED_DECOR_RECORD_SIZE, original_len)
    _replace_trailing(room, data)
    return count


def delete_animated_decor_record(room: Room, index: int) -> None:
    table = animated_decor_table(room)
    if table is None or not 0 <= index < len(table.records):
        raise ValueError(f"animated decor index out of range: {index}")
    original_len = len(room.trailing)
    data = bytearray(room.trailing)
    off = table.records[index].source_offset
    del data[off:off + ANIMATED_DECOR_RECORD_SIZE]
    data[table.offset] = max(0, table.count - 1)
    old_trailing = room.trailing
    room.trailing = bytes(data[:original_len - ANIMATED_DECOR_RECORD_SIZE])
    padding_start = _payload_padding_start(room)
    room.trailing = old_trailing
    padding_start = max(0, min(len(data), padding_start))
    data[padding_start:padding_start] = b"\x00" * ANIMATED_DECOR_RECORD_SIZE
    del data[original_len:]
    room.trailing = bytes(data)


def visual_compact3_table(room: Room) -> Compact3Table | None:
    """Return the main visual/decor table used by the renderer."""
    directory = parse_exe_payload_directory(room)
    if directory and directory.sections and directory.sections.visual and directory.sections.visual.count:
        return directory.sections.visual
    return None


def set_visual_compact3_entry(room: Room, index: int, *, x_raw: int, y: int, code: int) -> None:
    table = visual_compact3_table(room)
    if table is None or not 0 <= index < len(table.entries):
        raise ValueError(f"visual compact3 index out of range: {index}")
    off = table.entries[index].source_offset
    room.set_trailing_bytes(off, [x_raw, y, code])


def add_visual_compact3_entry(room: Room, *, x_raw: int, y: int, code: int) -> int:
    table = visual_compact3_table(room)
    if table is None:
        raise ValueError("room has no editable visual compact3 table")
    if table.count >= 32:
        raise ValueError("visual compact3 table is full")
    original_len = len(room.trailing)
    data = bytearray(room.trailing)
    insert_at = table.offset + 1 + table.count * 3
    data[table.offset] = table.count + 1
    data[insert_at:insert_at] = bytes([x_raw & 0xFF, y & 0xFF, code & 0xFF])
    padding_start = _payload_padding_start(room)
    shifted_padding_start = padding_start + 3 if padding_start >= insert_at else padding_start
    _delete_padding_bytes_after_insert(data, shifted_padding_start, 3, original_len)
    _replace_trailing(room, data)
    return table.count


def delete_visual_compact3_entry(room: Room, index: int) -> None:
    table = visual_compact3_table(room)
    if table is None or not 0 <= index < len(table.entries):
        raise ValueError(f"visual compact3 index out of range: {index}")
    original_len = len(room.trailing)
    data = bytearray(room.trailing)
    off = table.entries[index].source_offset
    del data[off:off + 3]
    data[table.offset] = max(0, data[table.offset] - 1)
    old_trailing = room.trailing
    room.trailing = bytes(data[:original_len - 3])
    padding_start = _payload_padding_start(room)
    room.trailing = old_trailing
    padding_start = max(0, min(len(data), padding_start))
    data[padding_start:padding_start] = b"\x00" * 3
    del data[original_len:]
    room.trailing = bytes(data)


def laser_crystal_table(room: Room) -> Compact3Table | None:
    """Return section_c, the rotating laser crystal / reflector table.

    A valid empty table (count=0) is still editable: adding the first reflector
    should grow this table instead of treating the room as unsupported.
    """
    directory = parse_exe_payload_directory(room)
    if directory and directory.sections and directory.sections.section_c is not None:
        return directory.sections.section_c
    return None

@dataclass(frozen=True)
class RoomTailMarker:
    """Three-byte runtime room-gated marker for the red apple pickup.

    AEPROG around 0x2e89 checks runtime room[0x3e7] against current_room+1 and,
    when it matches, draws AE000:045 using runtime room[0x3e5] and [0x3e6]
    as coordinates, and registers gameplay pickup id 7.
    """

    x_raw: int
    y_raw: int
    room_plus_one: int

    @property
    def active(self) -> bool:
        return self.room_plus_one != 0

    @property
    def label(self) -> str:
        return f"apple_marker gate={self.room_plus_one:02X} x={self.x_raw:02X} y={self.y_raw:02X}"


def _part_apple_offsets(part: LevelPart, room_index: int) -> tuple[int, int, int]:
    if not 0 <= room_index < ROOM_COUNT:
        raise ValueError(f"room index out of range: {room_index}")
    terrain_start = LEVEL_PART_HEADER_SIZE + room_index * ROOM_RECORD_SIZE + ROOM_TERRAIN_OFFSET
    return terrain_start + 0x3E5, terrain_start + 0x3E6, terrain_start + 0x3E7


def part_apple_marker(part: LevelPart, room_index: int) -> RoomTailMarker | None:
    """Return the runtime red apple marker for a room, if present.

    The EXE's room pointer starts at the terrain bytes, two bytes after the
    editor's 1000-byte room record begins.  Therefore the runtime marker at
    ``room+0x3E5..0x3E7`` is physically split across record boundaries:
    current record's final byte, then the first two bytes of the following
    record.
    """
    x_off, y_off, gate_off = _part_apple_offsets(part, room_index)
    if gate_off >= len(part.raw):
        return None
    marker = RoomTailMarker(part.raw[x_off], part.raw[y_off], part.raw[gate_off])
    if marker.room_plus_one != room_index + 1:
        return None
    return marker


def apple_marker_screen_xy(marker: RoomTailMarker) -> tuple[int, int]:
    """Return the apple sprite top-left in editor pixels.

    AEPROG 0x2e89 blits the apple via 0x3cc with x_arg = room[0x3e5]*2 and
    y_arg = room[0x3e6] + 0xb8 - the shared object anchor used by every other
    payload object.  Cropping at the view origin (8, 200) gives the universal
    (x_raw*2 - 8, y_raw - 16).  (This mirrors coordinates.object_screen_xy, which
    cannot be imported here without a cycle.)
    """
    return marker.x_raw * 2 - 8, marker.y_raw - 16


def apple_marker_raw_xy(marker: RoomTailMarker) -> tuple[int, int]:
    """Return the marker's logical x_raw/y coordinate pair."""
    return marker.x_raw, marker.y_raw


def set_part_apple_marker(part: LevelPart, room_index: int, *, x_raw: int, y: int) -> None:
    """Create or move the one real red apple pickup in this room."""
    x_off, y_off, gate_off = _part_apple_offsets(part, room_index)
    if gate_off >= len(part.raw):
        raise ValueError("level part is too short for an apple marker")
    part.set_part_bytes(x_off, bytes([x_raw & 0xFF]))
    part.set_part_bytes(y_off, bytes([y & 0xFF, (room_index + 1) & 0xFF]))


def clear_part_apple_marker(part: LevelPart, room_index: int) -> None:
    """Remove the runtime red apple marker from this room."""
    x_off, y_off, gate_off = _part_apple_offsets(part, room_index)
    if gate_off >= len(part.raw):
        raise ValueError("level part is too short for an apple marker")
    part.set_part_bytes(x_off, b"\x00")
    part.set_part_bytes(y_off, b"\x00\x00")


@dataclass(frozen=True)
class HeaderRoomObjectCandidate:
    """Room-gated diamond/artifact slot from the six-entry header arrays.

    Static analysis around 0x2e36 uses three six-byte arrays in globals
    0x437a/0x4380/0x4386 and draws AE000:044 when
    room_id == current_room+1.  The level-part blob is copied with a two-byte
    preamble skipped, so these arrays line up with header offsets 0x08/0x0e/0x14
    in the editor's sliced header view.
    """

    index: int
    room_plus_one: int
    x_raw: int
    y_raw: int

    @property
    def label(self) -> str:
        return f"diamond[{self.index}] room+1={self.room_plus_one} x={self.x_raw:02X} y={self.y_raw:02X}"


def header_object_candidates(header: bytes) -> list[HeaderRoomObjectCandidate]:
    if len(header) < 0x1a:
        return []
    room_ids = header[0x08:0x0e]
    xs = header[0x0e:0x14]
    ys = header[0x14:0x1a]
    out: list[HeaderRoomObjectCandidate] = []
    for i, (room_id, x, y) in enumerate(zip(room_ids, xs, ys)):
        if room_id:
            out.append(HeaderRoomObjectCandidate(i, room_id, x, y))
    return out


@dataclass(frozen=True)
class HeaderExitDoor:
    """Conditional exit door shown after all artifacts are collected.

    Header bytes 0x05..0x07 form a room-gated door slot:
      * 0x05 = zero-based room index
      * 0x06 = half-screen x anchor
      * 0x07 = bottom y anchor

    The artwork is theme-specific terrain-bank sprite 0, i.e.
    AE001:(021 + theme):0.
    """

    room_index: int
    x_raw: int
    y_raw: int

    @property
    def label(self) -> str:
        return f"exit_door room={self.room_index} x={self.x_raw:02X} y={self.y_raw:02X}"


def header_exit_door(header: bytes) -> HeaderExitDoor | None:
    if len(header) < 8:
        return None
    room_index, x_raw, y_raw = header[5], header[6], header[7]
    if room_index >= ROOM_COUNT:
        return None
    return HeaderExitDoor(room_index, x_raw, y_raw)


@dataclass(frozen=True)
class HeaderPlayerStart:
    """Player start stored in the level-part header.

    The original game always starts in room 0.  AEPROG.EXE reads raw
    header[0x03]/[0x04] as x/y and initializes the current room separately to 0;
    raw header[0x01] is not the start-room field.
    """

    room_index: int
    x_raw: int
    y_raw: int

    @property
    def label(self) -> str:
        return f"player_start room={self.room_index} x={self.x_raw:02X} y={self.y_raw:02X}"


def header_player_start(header: bytes) -> HeaderPlayerStart | None:
    if len(header) < 5:
        return None
    room_index = 0
    x_raw = header[3]
    y_raw = header[4]
    if x_raw == 0 and y_raw == 0:
        return None
    return HeaderPlayerStart(room_index, x_raw, y_raw)


def set_laser_crystal_entry(room: Room, index: int, *, x_raw: int, y: int, code: int) -> None:
    """Rewrite one entry in the section_c laser/reflector compact3 table."""
    table = laser_crystal_table(room)
    if table is None or not 0 <= index < len(table.entries):
        raise ValueError(f"laser reflector index out of range: {index}")
    off = table.entries[index].source_offset
    room.set_trailing_bytes(off, [x_raw & 0xFF, y & 0xFF, code & 0xFF])


def add_laser_crystal_entry(room: Room, *, x_raw: int, y: int, code: int) -> int:
    """Append an entry to section_c, the current reflector/crystal table.

    This mirrors add_visual_compact3_entry but targets section_c instead of the
    visual/decor table.  Controls can then point at the new item with R<n>
    (encoded as target byte 0x40|n).  M<n> remains accepted by the GUI only as
    an older shortcut for existing edited rooms.
    """
    table = laser_crystal_table(room)
    if table is None:
        raise ValueError("room has no editable laser/reflector table")
    if table.count >= 32:
        raise ValueError("laser/reflector table is full")
    original_len = len(room.trailing)
    data = bytearray(room.trailing)
    insert_at = table.offset + 1 + table.count * 3
    data[table.offset] = table.count + 1
    data[insert_at:insert_at] = bytes([x_raw & 0xFF, y & 0xFF, code & 0xFF])
    padding_start = _payload_padding_start(room)
    shifted_padding_start = padding_start + 3 if padding_start >= insert_at else padding_start
    _delete_padding_bytes_after_insert(data, shifted_padding_start, 3, original_len)
    _replace_trailing(room, data)
    return table.count


def delete_laser_crystal_entry(room: Room, index: int) -> None:
    """Delete one section_c laser/reflector entry."""
    table = laser_crystal_table(room)
    if table is None or not 0 <= index < len(table.entries):
        raise ValueError(f"laser reflector index out of range: {index}")
    original_len = len(room.trailing)
    data = bytearray(room.trailing)
    off = table.entries[index].source_offset
    del data[off:off + 3]
    data[table.offset] = max(0, data[table.offset] - 1)
    old_trailing = room.trailing
    room.trailing = bytes(data[:original_len - 3])
    padding_start = _payload_padding_start(room)
    room.trailing = old_trailing
    padding_start = max(0, min(len(data), padding_start))
    data[padding_start:padding_start] = b"\x00" * 3
    del data[original_len:]
    room.trailing = bytes(data)
