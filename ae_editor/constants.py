"""Shared constants for the Ancient Empires reverse-engineering editor."""

LEVEL_COUNT = 20
LEVEL_MAGIC = 0x4D

# New best-known level layout (v16): each AE001 level resource is two halves.
# Each half starts with a 0x40-byte header, then 13 fixed-size room records,
# then a 4-byte footer. A room record is 1000 bytes. Its first two bytes are
# per-room metadata/unknown flags; the visible terrain grid starts at +2.
LEVEL_PART_COUNT = 2
LEVEL_PART_HEADER_SIZE = 0x40
LEVEL_PART_FOOTER_SIZE = 4
ROOM_COUNT = 13
ROOM_RECORD_SIZE = 1000
ROOM_TERRAIN_OFFSET = 2
ROOM_COLUMNS = 38
ROOM_ROWS = 18
ROOM_TILE_COUNT = ROOM_COLUMNS * ROOM_ROWS
ROOM_TRAILING_DATA_SIZE = ROOM_RECORD_SIZE - ROOM_TERRAIN_OFFSET - ROOM_TILE_COUNT
CELL_SIZE = 8

# Kept for compatibility in docs/tools.
LEVEL_HEADER_SIZE = LEVEL_PART_HEADER_SIZE

# Current best terrain-code mapping. Values are sequence indexes within the
# terrain sprite bank for the level theme. 0x80/0x90/... are not ordinary tiles;
# they appear as tall foreground/edge pieces, but rendering them here makes the
# room previews much closer to the real game screenshots.
DEFAULT_TERRAIN_CODE_TO_SPRITE = {
    0x00: None,
    0x01: 5,
    0x02: 5,
    0x03: 7,
    0x04: 8,
    0x05: 9,
    0x06: 10,
    0x07: 6,
    0x80: 0,
    0x90: 1,
    0xA0: 2,
    0xB0: 3,
    0xC0: 4,
}

TERRAIN_BANK_RESOURCE_START = 21
TERRAIN_BANK_COUNT = 4
SPRITE_BANK_SCAN_START = 20
SPRITE_BANK_SCAN_END = 60
