"""Coordinate conversion helpers for Ancient Empires room rendering.

Every transform here is derived from the AEPROG room draw path, not from
screenshots.  The EXE renders a room into an offscreen buffer and scrolls a
window of it to the screen; the editor renders the room flat and crops that
buffer at the background backdrop origin.  So every editor position is just
`buffer_pos - ROOM_VIEW_ORIGIN`.
"""
from __future__ import annotations

from ..constants import CELL_SIZE
from ..game_data.room_payload import ControlCommand, ObjectTableEntry, PlatformTriplet


# ───────────────────────────────────────────────────────────────────────────
# AEPROG room buffer geometry — the ONE shared model behind every position.
#
# EVERY sprite goes through the same top-left blitter (0x3cc -> 0x1a98): a pure
# top-left blit with no width/2, no height subtraction, and no per-sprite
# hotspot (the 0x47 graphics header is marker + ctrl + 16 EGA + 16 VGA +
# row_bytes + height = 36 bytes, no origin field).  Only the BUFFER POSITION
# passed to that blitter varies per object family:
#
#   background backdrop    (8, 200)                    AEPROG 0x2bc0
#   terrain tile (col,row) (col*8 + 4, row*8 + 196)    AEPROG 0x2c97  (0xc4=196)
#   rope tile (col,row)    (col*8 + 8, row*8 + 200)    AEPROG 0x2ccf  (0xc8=200)
#   payload object         (raw_x*2,  raw_y + 184)     AEPROG 0x2d8a  (0xb8=184)
#
# The editor crops the buffer at the backdrop origin, so the background lands at
# editor (0,0) and every other position is `buffer_pos - ROOM_VIEW_ORIGIN`.
ROOM_VIEW_ORIGIN = (8, 200)        # = background backdrop blit (AEPROG 0x2bc0)
_TERRAIN_TILE_BUFFER = (4, 196)    # AEPROG 0x2c97
_ROPE_TILE_BUFFER = (8, 200)       # AEPROG 0x2ccf
_OBJECT_BUFFER_Y_BIAS = 184        # 0xb8; object buffer x is raw_x * 2


def buffer_to_view(bx: int, by: int) -> tuple[int, int]:
    """Map an AEPROG room-buffer position to an editor-view top-left pixel."""
    return bx - ROOM_VIEW_ORIGIN[0], by - ROOM_VIEW_ORIGIN[1]


def object_screen_xy(raw_x: int, raw_y: int) -> tuple[int, int]:
    """Top-left editor pixel for any payload object the EXE draws.

    Buffer position is (raw_x*2, raw_y + 184); cropping at the view origin gives
    (raw_x*2 - 8, raw_y - 16).  Shared by compact3 visuals (0x2bf7 / 0x2d3e),
    header diamonds (0x2e32), the exit/apple marker (0x2e89), puzzle symbols
    (0x3085) and control buttons/switches/triggers (0x2f10).
    """
    return buffer_to_view(raw_x * 2, raw_y + _OBJECT_BUFFER_Y_BIAS)


def terrain_tile_xy(col: int, row: int) -> tuple[int, int]:
    """Top-left editor pixel for a terrain tile sprite (AEPROG 0x2c97)."""
    bx, by = _TERRAIN_TILE_BUFFER
    return buffer_to_view(col * CELL_SIZE + bx, row * CELL_SIZE + by)


def rope_tile_xy(col: int, row: int) -> tuple[int, int]:
    """Top-left editor pixel for a rope tile sprite (AEPROG 0x2ccf)."""
    bx, by = _ROPE_TILE_BUFFER
    return buffer_to_view(col * CELL_SIZE + bx, row * CELL_SIZE + by)


def object_entry_xy(entry: ObjectTableEntry) -> tuple[int, int]:
    """Top-left editor pixel for a compact3 / object-table entry."""
    return object_screen_xy(entry.x_raw, entry.y)


def control_xy(cmd: ControlCommand) -> tuple[int, int]:
    """Top-left for a control record, from the AEPROG control loop at 0x2f10.

    The loop reads X=record[2], Y=record[3] and blits ceiling buttons, floor
    switches and laser triggers all through the SAME shared anchor; only the
    sprite and the collision box differ per command, not the draw position.
    """
    return object_screen_xy(cmd.x_raw or 0, cmd.y_raw or 0)


def actor_xy(x: int, y: int) -> tuple[int, int]:
    """Actor sprite top-left, from the AEPROG actor draw loop at 0x4ef8.

    The loop reads x at rec+0x02 (a full-resolution 16-bit X, NOT halved like
    the raw payload x) and y at rec+0x04, then blits via 0x3cc with x_arg = x
    and y_arg = vertical_base + y.  The steady-state room draw passes
    vertical_base = 0xb8 (AEPROG 0x399a/0x399e), so the actor buffer position is
    (x, y + 0xb8) - the shared family, just with X already full resolution.
    Cropping at the view origin gives (x - 8, y - 16), uniform for every enemy.
    """
    return buffer_to_view(x, y + _OBJECT_BUFFER_Y_BIAS)


def header_object_xy(x_raw: int, y_raw: int) -> tuple[int, int]:
    """Six-slot header diamond top-left, from the AEPROG draw at 0x2e32."""
    return object_screen_xy(x_raw, y_raw)


def header_exit_door_xy(x_raw: int, y_raw: int) -> tuple[int, int]:
    """Exit-door top-left.  Same shared object anchor as everything else."""
    return object_screen_xy(x_raw, y_raw)


def platform_xy(p: PlatformTriplet) -> tuple[int, int]:
    """Resting platform top-left, from the static platform draw at AEPROG 0x28ac.

    0x28ac walks the room+0x2AC triplets (flags, x_raw, y), writes the 0x07
    collision footprint, and blits the platform sprite at a buffer position that
    is NOT the universal object anchor - platforms are nudged (-4, -4) from it:

        x_buf = x_raw*2 - 4   (0x28ac: si = x_raw*2; sub si,4)
        y_buf = y + 0xb4      (0x28ac: add di,0xb4 = 180, not the usual 0xb8)

    Cropping at the view origin (8, 200) gives editor (x_raw*2 - 12, y - 20).
    (The 0x338a path is the per-frame *moving* redraw and uses the shared anchor;
    the editor previews the resting position, so it matches 0x28ac.)
    """
    return p.x_raw * 2 - 12, p.y - 20


# Moving platforms encode orientation and travel direction in their flag nibble.
# The room payload does not store an explicit destination next to the triplet,
# so use a shared travel constant for overlay/debug visualization.
PLATFORM_TRAVEL_DISTANCE = 48
PLATFORM_TRAVEL_BY_FLAGS: dict[int, tuple[int, int]] = {
    # Playtesting confirmed the horizontal flag families move opposite to the
    # original editor-side "left/right" labels.
    0x40: (+PLATFORM_TRAVEL_DISTANCE, 0),
    0x60: (-PLATFORM_TRAVEL_DISTANCE, 0),
    0x80: (0, +PLATFORM_TRAVEL_DISTANCE),
    0xA0: (0, -PLATFORM_TRAVEL_DISTANCE),
}


def platform_motion_delta(p: PlatformTriplet) -> tuple[int, int]:
    """Best current platform travel vector for overlay visualization."""
    return PLATFORM_TRAVEL_BY_FLAGS.get(p.flags & 0xF0, (0, 0))
