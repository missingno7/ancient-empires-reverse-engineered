"""Room payload parsing for Super Solvers: Challenge of the Ancient Empires.

A room record is 1000 bytes:

    +0x000..0x001  room preamble / metadata
    +0x002..0x2AD  terrain grid, 38×18 bytes
    +0x2AE..0x3E7  trailing payload, 314 bytes

The trailing payload is not random data. Static analysis of AEPROG.EXE points to
this structure:

    trailing +0x00  ten 3-byte platform/control triplets
    trailing +0x1E  payload directory / control records / compact3 sections

This module intentionally avoids the old brute-force scanners. Anything still
unknown is represented explicitly as an unknown section rather than being drawn
as a guessed object.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .constants import CELL_SIZE, ROOM_COLUMNS, ROOM_COUNT, ROOM_ROWS, ROOM_SCREEN_HEIGHT_PX, ROOM_SCREEN_WIDTH_PX
from .conveyors import BeltKind, ConveyorRecord, ConveyorVisualRecord, DEFAULT_CONVEYOR_FLAGS
from .level_format import Room

PAYLOAD_DIRECTORY_OFFSET = 0x1E
PLATFORM_TRIPLET_COUNT = 10
PLATFORM_TRIPLET_SIZE = 3
ACTOR_TABLE_OFFSET = 0x2754
ACTOR_TABLE_SIZE = 0x0BB8
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

    Older renderer versions accidentally treated the length byte itself as the
    command/type.  The actual command body starts at raw[1:].  This small
    wrapper makes that explicit and prevents trigger ids from being confused
    with sprite ids.
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
    raw_part = getattr(part, "raw", b"")
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
    if directory and directory.sections and directory.sections.after_visual is not None:
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
        sections = PayloadSections(records_end, section_a, section_b_offset, section_b_count, section_b_records, None, None, None)
        return ExePayloadDirectory(base, directory_count, selected_index, variable_start, ptr, records, sections)
    ptr = ptr2

    section_c = parse_counted_compact3_at(room, ptr, max_count=32, label="section_c")
    if section_c is None:
        sections = PayloadSections(records_end, section_a, section_b_offset, section_b_count, section_b_records, None, None, None)
        return ExePayloadDirectory(base, directory_count, selected_index, variable_start, ptr, records, sections)
    ptr = section_c.offset + 1 + section_c.count * 3

    visual = parse_counted_compact3_at(room, ptr, max_count=32, label="visual")
    after_visual = visual.offset + 1 + visual.count * 3 if visual is not None else None
    sections = PayloadSections(records_end, section_a, section_b_offset, section_b_count, section_b_records, section_c, visual, after_visual)
    return ExePayloadDirectory(base, directory_count, selected_index, variable_start, ptr, records, sections)


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
    """Three-byte room-gated marker at the very end of the 1000-byte record.

    AEPROG around 0x2e89 checks record[0x3e7] against current_room+1 and,
    when it matches, draws the red apple pickup (AE000:045) using record[0x3e5]
    and record[0x3e6] as coordinates, and registers gameplay pickup id 7.
    """

    x_raw: int
    y_raw: int
    room_plus_one: int

    @property
    def active(self) -> bool:
        return self.room_plus_one != 0

    @property
    def label(self) -> str:
        return f"tail_marker room+1={self.room_plus_one} x={self.x_raw:02X} y={self.y_raw:02X}"


def room_tail_marker(room: Room) -> RoomTailMarker | None:
    if len(room.trailing) < 3:
        return None
    x_raw, y_raw, room_plus_one = room.trailing[-3], room.trailing[-2], room.trailing[-1]
    marker = RoomTailMarker(x_raw, y_raw, room_plus_one)
    return marker if marker.active else None


def room_apple_marker(room: Room) -> RoomTailMarker | None:
    """Return the real red apple pickup marker for this room, if present.

    The EXE draws AE000:045 and registers pickup id 7 when the last byte of
    the room record equals current_room + 1.  The preceding two bytes are the
    x_raw/y coordinates.  Other non-zero room ids are markers for a different
    room and should not be rendered/editable here.
    """
    marker = room_tail_marker(room)
    if marker is None or marker.room_plus_one != room.index + 1:
        return None
    return marker


def set_room_apple_marker(room: Room, *, x_raw: int, y: int) -> None:
    """Create or move the one real red apple pickup in this room."""
    if len(room.trailing) < 3:
        raise ValueError("room trailing payload is too short for an apple marker")
    room.set_trailing_bytes(len(room.trailing) - 3, [x_raw & 0xFF, y & 0xFF, (room.index + 1) & 0xFF])


def clear_room_apple_marker(room: Room) -> None:
    """Remove the real red apple pickup from this room."""
    if len(room.trailing) < 3:
        raise ValueError("room trailing payload is too short for an apple marker")
    room.set_trailing_bytes(len(room.trailing) - 3, [0, 0, 0])


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
    """Best-known player start candidate stored in the level-part header.

    The first two position-like bytes after the part magic/theme align with
    known starting-room screenshots: x is the same half-screen unit used by
    compact/control objects, while y is a screen-space baseline-ish value.
    This is still a static preview marker, not runtime player state.
    """

    x_raw: int
    y_raw: int

    @property
    def label(self) -> str:
        return f"player_start x={self.x_raw:02X} y={self.y_raw:02X}"


def header_player_start(header: bytes) -> HeaderPlayerStart | None:
    if len(header) < 5:
        return None
    x_raw = header[3]
    y_raw = header[4]
    if x_raw == 0 and y_raw == 0:
        return None
    return HeaderPlayerStart(x_raw, y_raw)


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
    a legacy alias.
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
