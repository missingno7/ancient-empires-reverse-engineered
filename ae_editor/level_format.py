from __future__ import annotations

from dataclasses import dataclass

from .constants import (
    LEVEL_HEADER_SIZE,
    LEVEL_MAGIC,
    ROOM_COLUMNS,
    ROOM_COUNT,
    ROOM_ROWS,
    ROOM_TILE_COUNT,
)
from .dat_archive import DatArchive


@dataclass
class Room:
    index: int
    tiles: list[int]

    def get(self, x: int, y: int) -> int:
        return self.tiles[y * ROOM_COLUMNS + x]

    def set(self, x: int, y: int, value: int) -> None:
        self.tiles[y * ROOM_COLUMNS + x] = value & 0xFF


class Level:
    """Decoded level resource.

    Current best-supported layout:

        0x40-byte header
        38 room records, each exactly 38*18 tile bytes
        80-byte footer/trailing data

    The header/footer are preserved raw because actor/trigger semantics are not
    solved yet. Earlier experiments that treated bytes after each room as object
    slots did not match screenshots reliably, so this parser intentionally keeps
    gameplay objects separate/unknown for now.
    """

    def __init__(self, index: int, decoded: bytes):
        if not decoded or decoded[0] != LEVEL_MAGIC:
            raise ValueError(f"resource {index} does not look like an AE level")
        self.index = index
        self.decoded = decoded
        self.header = decoded[:LEVEL_HEADER_SIZE]
        self.theme = decoded[2] & 0x03 if len(decoded) > 2 else 0
        self.rooms: list[Room] = []
        offset = LEVEL_HEADER_SIZE
        for room_index in range(ROOM_COUNT):
            chunk = decoded[offset:offset + ROOM_TILE_COUNT]
            if len(chunk) < ROOM_TILE_COUNT:
                chunk = chunk + bytes(ROOM_TILE_COUNT - len(chunk))
            self.rooms.append(Room(room_index, list(chunk)))
            offset += ROOM_TILE_COUNT
        self.footer = decoded[offset:]

    @property
    def expected_size(self) -> int:
        return LEVEL_HEADER_SIZE + ROOM_COUNT * ROOM_TILE_COUNT + 80

    @property
    def size_is_expected(self) -> bool:
        return len(self.decoded) == self.expected_size

    def room(self, index: int) -> Room:
        return self.rooms[index]


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
