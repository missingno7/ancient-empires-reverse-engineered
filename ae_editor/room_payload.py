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

from .constants import CELL_SIZE, ROOM_COLUMNS, ROOM_ROWS
from .level_format import Room

ROOM_WIDTH_PX = ROOM_COLUMNS * CELL_SIZE
ROOM_HEIGHT_PX = ROOM_ROWS * CELL_SIZE
PAYLOAD_DIRECTORY_OFFSET = 0x1E
PLATFORM_TRIPLET_COUNT = 10
PLATFORM_TRIPLET_SIZE = 3

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
