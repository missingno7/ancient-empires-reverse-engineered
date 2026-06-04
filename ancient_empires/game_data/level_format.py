from __future__ import annotations

from dataclasses import dataclass

from ..constants import (
    LEVEL_PART_ACTOR_BLOCK_SIZE,
    LEVEL_MAGIC,
    LEVEL_PART_COUNT,
    LEVEL_PART_HEADER_SIZE,
    LEVEL_PART_SEPARATOR_SIZE,
    ROOM_COLUMNS,
    ROOM_COUNT,
    ROOM_RECORD_SIZE,
    ROOM_TERRAIN_OFFSET,
    ROOM_TILE_COUNT,
)
from .dat_archive import DatArchive


@dataclass
class Room:
    """One 38x18 visible room terrain grid plus unknown per-room data."""

    part_index: int
    index: int
    record_offset: int
    terrain_offset: int
    preamble: bytes
    tiles: list[int]
    trailing: bytes

    def get(self, x: int, y: int) -> int:
        return self.tiles[y * ROOM_COLUMNS + x]

    def set(self, x: int, y: int, value: int) -> None:
        self.tiles[y * ROOM_COLUMNS + x] = value & 0xFF

    def set_trailing_bytes(self, offset: int, values: list[int]) -> None:
        if offset < 0 or offset + len(values) > len(self.trailing):
            raise ValueError(f"room trailing write out of range: offset={offset} len={len(values)}")
        data = bytearray(self.trailing)
        for i, value in enumerate(values):
            data[offset + i] = value & 0xFF
        self.trailing = bytes(data)

    @property
    def nonzero_tile_count(self) -> int:
        return sum(1 for value in self.tiles if value)

    @property
    def looks_empty(self) -> bool:
        return self.nonzero_tile_count < 8

    @property
    def looks_like_room(self) -> bool:
        """All parsed records are real rooms; this only flags empty slots."""
        return not self.looks_empty

    @property
    def quality_label(self) -> str:
        if self.looks_empty:
            return "empty"
        return "room"


@dataclass
class LevelPart:
    """One of the two 0x330c-byte parts inside a level resource.

    Current best-known layout per part:

        0x40 header
        10 room records × 1000 bytes
            +0x000..0x001: unknown per-room bytes
            +0x002..0x2ad: 38×18 terrain bytes, row-major
            +0x2ae..0x3e7: unknown room payload, likely actors/triggers/decor
        4 byte separator
        0x0bb8 byte actor block

    The two parts are exposed as Explorer / Expert difficulty variants. Some
    rooms are shared/similar, while later caverns can diverge substantially.
    """

    index: int
    base_offset: int
    raw: bytes
    header: bytes
    rooms: list[Room]
    separator: bytes

    @property
    def theme(self) -> int:
        return self.header[2] & 0x03 if len(self.header) > 2 else 0

    @property
    def expected_size(self) -> int:
        return (
            LEVEL_PART_HEADER_SIZE
            + ROOM_COUNT * ROOM_RECORD_SIZE
            + LEVEL_PART_SEPARATOR_SIZE
            + LEVEL_PART_ACTOR_BLOCK_SIZE
        )

    def room(self, index: int) -> Room:
        return self.rooms[index]

    def _set_header_bytes(self, offset: int, values: list[int]) -> None:
        header = bytearray(self.header)
        for i, value in enumerate(values):
            header[offset + i] = value & 0xFF
        self.header = bytes(header)

    def set_player_start(self, x_raw: int, y_raw: int, room_index: int | None = None) -> None:
        # Static analysis of AEPROG.EXE shows the runtime load routine copies
        # the part header starting at raw header[0x02] into DS:4374.  The player
        # spawn routine then reads DS:4375/DS:4376, i.e. raw header[0x03]/[0x04],
        # for x/y and initializes current room separately to 0.  There is no
        # confirmed editable start-room byte in the level data.
        if room_index not in (None, 0):
            raise ValueError("player start room is hard-coded by the game to room 0")
        self._set_header_bytes(0x03, [x_raw, y_raw])

    def set_room_transition_links(
        self,
        room_index: int,
        *,
        left: int | None = None,
        right: int | None = None,
        up: int | None = None,
        down: int | None = None,
    ) -> None:
        if not 0 <= room_index < ROOM_COUNT:
            raise ValueError(f"room index out of range: {room_index}")

        def stored(value: int | None, current: int) -> int:
            if value is None:
                return current
            if value < 0:
                return 0
            if not 0 <= value < ROOM_COUNT:
                raise ValueError(f"linked room out of range: {value}")
            return value + 1

        # Room links are addressed in the level-part payload, not just in the
        # 0x40-byte header model.  The last two down-link bytes currently overlap
        # the first room preamble in this parsed layout, so write through the
        # generic part patcher to keep raw/header/room views in sync.
        for offset, value in (
            (0x1A + room_index, left),
            (0x24 + room_index, right),
            (0x2E + room_index, up),
            (0x38 + room_index, down),
        ):
            if offset >= len(self.raw):
                raise ValueError("level-part payload is too short for room links")
            current = self.raw[offset]
            self.set_part_bytes(offset, bytes([stored(value, current)]))


    def set_exit_door(self, room_index: int, x_raw: int, y_raw: int) -> None:
        self._set_header_bytes(0x05, [room_index, x_raw, y_raw])

    def set_artifact_slot(self, slot: int, room_index: int, x_raw: int, y_raw: int) -> None:
        if not 0 <= slot < 6:
            raise ValueError(f"artifact slot out of range: {slot}")
        self._set_header_bytes(0x08 + slot, [room_index + 1])
        self._set_header_bytes(0x0E + slot, [x_raw])
        self._set_header_bytes(0x14 + slot, [y_raw])

    def clear_artifact_slot(self, slot: int) -> None:
        if not 0 <= slot < 6:
            raise ValueError(f"artifact slot out of range: {slot}")
        self._set_header_bytes(0x08 + slot, [0])
        self._set_header_bytes(0x0E + slot, [0])
        self._set_header_bytes(0x14 + slot, [0])

    def _flush_rooms_to_raw(self) -> None:
        """Write the live header + room terrain/trailing back into ``self.raw``.

        ``self.raw`` and the parsed ``Room`` objects are two views of the same
        bytes.  Editing a ``Room`` (e.g. mirroring terrain) only updates the
        object, so ``self.raw`` can be stale.  ``set_part_bytes`` re-parses rooms
        from ``self.raw`` after patching, which would otherwise clobber those
        pending edits; flushing first keeps the two views consistent.
        """
        data = bytearray(self.raw)
        data[:LEVEL_PART_HEADER_SIZE] = self.header
        for room in self.rooms:
            record_start = LEVEL_PART_HEADER_SIZE + room.index * ROOM_RECORD_SIZE
            terrain_start = record_start + ROOM_TERRAIN_OFFSET
            data[terrain_start:terrain_start + ROOM_TILE_COUNT] = bytes(room.tiles)
            tail_start = terrain_start + ROOM_TILE_COUNT
            data[tail_start:tail_start + len(room.trailing)] = room.trailing
        self.raw = bytes(data)

    def set_part_bytes(self, offset: int, values: bytes | bytearray) -> None:
        """Patch bytes in this part and mirror them into serialized room fields."""
        payload = bytes(values)
        if offset < 0 or offset + len(payload) > len(self.raw):
            raise ValueError(f"part write out of range: offset={offset:#x} len={len(payload)}")
        self._flush_rooms_to_raw()
        data = bytearray(self.raw)
        data[offset:offset + len(payload)] = payload
        self.raw = bytes(data)

        header_end = LEVEL_PART_HEADER_SIZE
        if offset < header_end:
            self.header = self.raw[:header_end]

        for room in self.rooms:
            record_start = LEVEL_PART_HEADER_SIZE + room.index * ROOM_RECORD_SIZE
            record_end = record_start + ROOM_RECORD_SIZE
            if offset >= record_end or offset + len(payload) <= record_start:
                continue
            record = self.raw[record_start:record_end]
            terrain_start = ROOM_TERRAIN_OFFSET
            terrain_end = terrain_start + ROOM_TILE_COUNT
            room.preamble = record[:ROOM_TERRAIN_OFFSET]
            room.tiles = list(record[terrain_start:terrain_end])
            room.trailing = record[terrain_end:]

        separator_start = LEVEL_PART_HEADER_SIZE + ROOM_COUNT * ROOM_RECORD_SIZE
        separator_end = separator_start + LEVEL_PART_SEPARATOR_SIZE
        if offset < separator_end and offset + len(payload) > separator_start:
            self.separator = self.raw[separator_start:separator_end]


class Level:
    """Decoded AE001 level resource.

    Earlier prototypes treated a level as one linear list of 38×684-byte rooms.
    That was wrong: it accidentally made room 0 look almost correct, but room 1+
    were shifted because the real records are 1000 bytes and the terrain starts
    two bytes into each record. A full resource is two equal LevelPart blocks.
    """

    def __init__(self, index: int, decoded: bytes):
        if not decoded or decoded[0] != LEVEL_MAGIC:
            raise ValueError(f"resource {index} does not look like an AE level")
        if len(decoded) % LEVEL_PART_COUNT:
            raise ValueError(f"resource {index} has odd level size {len(decoded)}")
        self.index = index
        self.decoded = decoded
        self.part_size = len(decoded) // LEVEL_PART_COUNT
        self.parts: list[LevelPart] = []
        for part_index in range(LEVEL_PART_COUNT):
            self.parts.append(self._parse_part(part_index, part_index * self.part_size))

    def _parse_part(self, part_index: int, base: int) -> LevelPart:
        raw = self.decoded[base:base + self.part_size]
        if not raw or raw[0] != LEVEL_MAGIC:
            raise ValueError(f"level {self.index} part {part_index} missing magic")
        header = raw[:LEVEL_PART_HEADER_SIZE]
        rooms: list[Room] = []
        for room_index in range(ROOM_COUNT):
            record_start = LEVEL_PART_HEADER_SIZE + room_index * ROOM_RECORD_SIZE
            record = raw[record_start:record_start + ROOM_RECORD_SIZE]
            if len(record) < ROOM_RECORD_SIZE:
                record = record + bytes(ROOM_RECORD_SIZE - len(record))
            terrain_start = record_start + ROOM_TERRAIN_OFFSET
            terrain = record[ROOM_TERRAIN_OFFSET:ROOM_TERRAIN_OFFSET + ROOM_TILE_COUNT]
            rooms.append(
                Room(
                    part_index=part_index,
                    index=room_index,
                    record_offset=base + record_start,
                    terrain_offset=base + terrain_start,
                    preamble=record[:ROOM_TERRAIN_OFFSET],
                    tiles=list(terrain),
                    trailing=record[ROOM_TERRAIN_OFFSET + ROOM_TILE_COUNT:],
                )
            )
        separator_start = LEVEL_PART_HEADER_SIZE + ROOM_COUNT * ROOM_RECORD_SIZE
        separator_end = separator_start + LEVEL_PART_SEPARATOR_SIZE
        separator = raw[separator_start:separator_end]
        return LevelPart(part_index, base, raw, header, rooms, separator)

    @property
    def theme(self) -> int:
        # Backward-compatible default; UI/rendering uses the selected part theme.
        return self.parts[0].theme

    @property
    def header(self) -> bytes:
        return self.parts[0].header

    @property
    def rooms(self) -> list[Room]:
        return self.parts[0].rooms

    @property
    def expected_size(self) -> int:
        return LEVEL_PART_COUNT * (
            LEVEL_PART_HEADER_SIZE
            + ROOM_COUNT * ROOM_RECORD_SIZE
            + LEVEL_PART_SEPARATOR_SIZE
            + LEVEL_PART_ACTOR_BLOCK_SIZE
        )

    @property
    def size_is_expected(self) -> bool:
        return len(self.decoded) == self.expected_size

    def part(self, index: int) -> LevelPart:
        return self.parts[index]

    def room(self, index: int, part_index: int = 0) -> Room:
        return self.parts[part_index].room(index)

    def to_bytes(self) -> bytes:
        """Serialize the current editable level model back to decoded bytes."""
        data = bytearray(self.decoded)
        for part in self.parts:
            part_data = bytearray(part.raw)
            part_data[:LEVEL_PART_HEADER_SIZE] = part.header
            for room in part.rooms:
                record_start = LEVEL_PART_HEADER_SIZE + room.index * ROOM_RECORD_SIZE
                terrain_start = record_start + ROOM_TERRAIN_OFFSET
                part_data[terrain_start:terrain_start + ROOM_TILE_COUNT] = bytes(room.tiles)
                tail_start = terrain_start + ROOM_TILE_COUNT
                part_data[tail_start:tail_start + len(room.trailing)] = room.trailing
            data[part.base_offset:part.base_offset + self.part_size] = part_data
        return bytes(data)


def load_levels(ae001: DatArchive, count: int = 20) -> list[Level]:
    levels: list[Level] = []
    for i in range(min(count, len(ae001))):
        res = ae001[i]
        if not res.ok:
            continue
        try:
            levels.append(Level(i, res.decoded))
        except ValueError:
            continue
    return levels
