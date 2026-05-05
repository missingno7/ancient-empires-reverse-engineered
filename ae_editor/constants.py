"""Shared constants for the Ancient Empires reverse-engineering editor."""

LEVEL_COUNT = 20
LEVEL_MAGIC = 0x4D
LEVEL_HEADER_SIZE = 0x40
ROOM_COLUMNS = 38
ROOM_ROWS = 18
ROOM_COUNT = 38
ROOM_TILE_COUNT = ROOM_COLUMNS * ROOM_ROWS
CELL_SIZE = 8

# Current best terrain-code mapping. This is deliberately isolated because it is
# the least final piece of the renderer. The values are sequence indexes within
# the terrain sprite bank for the level theme.
DEFAULT_TERRAIN_CODE_TO_SPRITE = {
    0x00: None,
    0x02: 5,
    0x03: 7,
    0x04: 8,
    0x05: 9,
    0x06: 10,
}

TERRAIN_BANK_RESOURCE_START = 21
TERRAIN_BANK_COUNT = 4
SPRITE_BANK_SCAN_START = 20
SPRITE_BANK_SCAN_END = 60
