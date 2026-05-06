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

from .constants import CELL_SIZE, ROOM_COLUMNS, ROOM_ROWS, ROOM_SCREEN_HEIGHT_PX, ROOM_SCREEN_WIDTH_PX
from .level_format import Room

ROOM_WIDTH_PX = ROOM_SCREEN_WIDTH_PX
ROOM_HEIGHT_PX = ROOM_SCREEN_HEIGHT_PX
PAYLOAD_DIRECTORY_OFFSET = 0x1E
PLATFORM_TRIPLET_COUNT = 10
PLATFORM_TRIPLET_SIZE = 3
ACTOR_TABLE_OFFSET = 0x2754
ACTOR_TABLE_SIZE = 0x0BB8
ACTOR_RECORD_SIZE = 0x20
CONFIRMED_ACTOR_FRAME_NAMES = {
    0x00: "ant",
    0x08: "bat",
    0x0F: "green_spitter",
    0x2B: "ladybug",
    0x32: "scorpion_shooter",
    0x37: "spider",
    0x3F: "snake",
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
        if high in {0x40, 0x60}:
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
    restart_script_offset: int

    @property
    def label(self) -> str:
        name = f"{self.confirmed_name} " if self.confirmed_name else ""
        return (
            f"actor[{self.index}] {name}room={self.room_index} x={self.x} y={self.y} "
            f"frame={self.frame:02X}:{self.frame_variant:02X} "
            f"range={self.frame_min:02X}-{self.frame_max:02X} hidden={self.hidden}"
        )

    @property
    def confirmed_name(self) -> str | None:
        return CONFIRMED_ACTOR_FRAME_NAMES.get(self.frame_min)


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
                restart_script_offset=rec[23] | (rec[24] << 8),
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


def laser_crystal_table(room: Room) -> Compact3Table | None:
    """Return the section currently matching rotating triangular laser crystals."""
    directory = parse_exe_payload_directory(room)
    if directory and directory.sections and directory.sections.section_c and directory.sections.section_c.count:
        return directory.sections.section_c
    return None

@dataclass(frozen=True)
class RoomTailMarker:
    """Three-byte room-gated marker at the very end of the 1000-byte record.

    AEPROG around 0x2e89 checks record[0x3e7] against current_room+1 and,
    when it matches, draws a small global sprite using record[0x3e5] and
    record[0x3e6] as coordinates.  The exact gameplay meaning is still under
    research, so the renderer exposes it only in payload_debug for now.
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
