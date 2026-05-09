"""Shared constants for the Ancient Empires reverse-engineering editor."""

LEVEL_COUNT = 20
LEVEL_MAGIC = 0x4D

# Current level layout: each AE001 level resource has two difficulty parts.
# Each half starts with a 0x40-byte header, then 10 fixed-size room records,
# a 4-byte separator, and a 3000-byte actor block. A room record is 1000 bytes.
# Its first two bytes are per-room metadata/unknown flags; the visible terrain
# grid starts at +2.
LEVEL_PART_COUNT = 2
LEVEL_PART_HEADER_SIZE = 0x40
LEVEL_PART_SEPARATOR_SIZE = 4
LEVEL_PART_ACTOR_BLOCK_SIZE = 0x0BB8
LEVEL_PART_FOOTER_SIZE = LEVEL_PART_SEPARATOR_SIZE  # Backward-compatible name.
ROOM_COUNT = 10
ROOM_RECORD_SIZE = 1000
LEVEL_PART_ACTOR_BLOCK_OFFSET = LEVEL_PART_HEADER_SIZE + ROOM_COUNT * ROOM_RECORD_SIZE + LEVEL_PART_SEPARATOR_SIZE
ROOM_TERRAIN_OFFSET = 2
ROOM_COLUMNS = 38
ROOM_ROWS = 18
ROOM_TILE_COUNT = ROOM_COLUMNS * ROOM_ROWS
ROOM_TRAILING_DATA_SIZE = ROOM_RECORD_SIZE - ROOM_TERRAIN_OFFSET - ROOM_TILE_COUNT
CELL_SIZE = 8
RUNTIME_TILE_VISIBLE_X_BIAS = 2

# The main timer cadence recovered from AEPROG.EXE.  Actor scripts advance once
# per 24 master ticks, so the room simulation defaults to the nearest integer
# rate while preserving the exact value for docs and future audio/runtime work.
GAME_MASTER_TICK_HZ = 236.69
ACTOR_TICK_DIVISOR = 24
ACTOR_TICK_HZ = GAME_MASTER_TICK_HZ / ACTOR_TICK_DIVISOR
DEFAULT_SIMULATION_TICK_HZ = round(ACTOR_TICK_HZ)

# The visible room viewport is the 38x18 tile grid. Runtime object coordinates
# can point slightly outside it; the final blit is clipped by the image bounds,
# matching what is visible in the game capture.
ROOM_SCREEN_WIDTH_PX = ROOM_COLUMNS * CELL_SIZE
ROOM_SCREEN_HEIGHT_PX = ROOM_ROWS * CELL_SIZE

from .rendering.tile_mapping import TERRAIN_CODE_TO_SPRITE as DEFAULT_TERRAIN_CODE_TO_SPRITE

TERRAIN_BANK_RESOURCE_START = 21
TERRAIN_BANK_COUNT = 4
