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

# The visible room viewport is the 38x18 tile grid. Runtime object coordinates
# can point slightly outside it; the final blit is clipped by the image bounds,
# matching what is visible in the game capture.
ROOM_SCREEN_WIDTH_PX = ROOM_COLUMNS * CELL_SIZE
ROOM_SCREEN_HEIGHT_PX = ROOM_ROWS * CELL_SIZE

# Kept for compatibility in docs/tools.
LEVEL_HEADER_SIZE = LEVEL_PART_HEADER_SIZE

# Terrain mapping lives in ae_editor.tile_mapping now.  It used to be embedded
# here, which made it too easy to hide renderer hacks that were actually mapping
# mistakes.  Keep the import for backward compatibility with older modules.
from .tile_mapping import TERRAIN_CODE_TO_SPRITE_V23 as DEFAULT_TERRAIN_CODE_TO_SPRITE

TERRAIN_BANK_RESOURCE_START = 21
TERRAIN_BANK_COUNT = 4
SPRITE_BANK_SCAN_START = 20
SPRITE_BANK_SCAN_END = 60
