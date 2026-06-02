"""Coordinate conversion helpers for Ancient Empires room rendering.

The game mixes several coordinate spaces:

* terrain cells: 38×18 cells, 8×8 pixels each;
* terrain art: usually larger than 8×8 and blitted with an anchor offset;
* platform/control records: 3-byte records at room+0x2AC;
* compact3 visual records: x is a half-pixel coordinate, y is near the screen
  baseline used by the EXE render routines.

Keep these transforms in one place so renderer-side hacks do not accumulate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PIL import Image

from ..constants import CELL_SIZE
from ..game_data.room_payload import ControlCommand, ObjectTableEntry, PlatformTriplet

AnchorMode = Literal[
    "terrain",
    "screen_exe",
]


# ───────────────────────────────────────────────────────────────────────────
# AEPROG room buffer geometry — the ONE shared model behind every position.
#
# The EXE renders a room into an offscreen buffer and scrolls a window of it to
# the screen.  EVERY sprite goes through the same top-left blitter
# (0x3cc -> 0x1a98): a pure top-left blit with no width/2, no height
# subtraction, and no per-sprite hotspot (the 0x47 graphics header is
# marker + ctrl + 16 EGA + 16 VGA + row_bytes + height = 36 bytes, no origin
# field).  The only thing that varies per object family is the BUFFER POSITION
# passed to that blitter:
#
#   background backdrop    (8, 200)                    AEPROG 0x2bc0
#   terrain tile (col,row) (col*8 + 4, row*8 + 196)    AEPROG 0x2c97  (0xc4=196)
#   rope tile (col,row)    (col*8 + 8, row*8 + 200)    AEPROG 0x2ccf  (0xc8=200)
#   payload object         (raw_x*2,  raw_y + 184)     AEPROG 0x2d8a  (0xb8=184)
#
# The editor renders the room flat and crops the buffer at the backdrop origin,
# so the background lands at editor (0,0).  Hence every editor position is just
# `buffer_pos - ROOM_VIEW_ORIGIN`.  Nothing below is screenshot-tuned: the
# -4/-8/-16 offsets are all consequences of these four ASM buffer origins.
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
    (0x3085), control buttons/switches/triggers (0x2f10) and platforms (0x338a).
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


# Derived aliases (no hand-tuned values).  object_screen_xy is preferred.
OBJECT_ORIGIN = (ROOM_VIEW_ORIGIN[0], ROOM_VIEW_ORIGIN[1] - _OBJECT_BUFFER_Y_BIAS)  # (8, 16)
DEFAULT_COMPACT3_ORIGIN = OBJECT_ORIGIN
BACKGROUND_COMPACT3_DELTA = (0, 0)
FOREGROUND_COMPACT3_DELTA = (0, 0)
LASER_CRYSTAL_DELTA = (0, 0)


@dataclass(frozen=True)
class TerrainAnchor:
    """Top-left offset of a terrain sprite from its logical 8x8 cell.

    Derived, not tuned: terrain buffer origin minus view origin,
    (4, 196) - (8, 200) = (-4, -4).
    """

    x: int = _TERRAIN_TILE_BUFFER[0] - ROOM_VIEW_ORIGIN[0]
    y: int = _TERRAIN_TILE_BUFFER[1] - ROOM_VIEW_ORIGIN[1]


TERRAIN_ANCHOR = TerrainAnchor()


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




# Moving platforms appear to use a small set of flag families that encode both
# orientation and the preferred travel direction.  The room payload does not
# store an explicit destination point next to the platform triplet, so keep the
# currently observed movement as a separate helper for overlay/debug purposes.
#
# The travel distance is intentionally centralized here so it can be replaced by
# a better EXE-derived value later without touching GUI/overlay code.
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
    """Best current platform travel vector for overlay visualization.

    The room triplet gives us start position and movement family, but not an
    obvious absolute destination.  Use the movement-family flag nibble as a
    direction selector and a shared travel constant for now.
    """
    return PLATFORM_TRAVEL_BY_FLAGS.get(p.flags & 0xF0, (0, 0))


def compact3_xy(
    entry: ObjectTableEntry,
    sprite: Image.Image,
    mode: AnchorMode = "screen_exe",
    *,
    origin: tuple[int, int] | None = None,
    delta: tuple[int, int] = (0, 0),
) -> tuple[int, int]:
    """Sprite top-left for a compact3 payload entry.

    Compact3 visuals use the shared object anchor like everything else; the
    `mode`/`origin`/`delta` parameters are retained only for call-site
    compatibility and no longer change the result.
    """
    return object_screen_xy(entry.x_raw, entry.y)


def control_xy(cmd: ControlCommand, *, mode: str = "button") -> tuple[int, int]:
    """Top-left for a control record, from the AEPROG control loop at 0x2f10.

    The loop reads X=record[2], Y=record[3] and blits ceiling buttons, floor
    switches and laser triggers all through the SAME shared anchor
    (x = record[2]*2, y = record[3] + 0xb8); only the sprite and the collision
    box differ per command, not the draw position.  `mode` is kept for the call
    sites but no longer changes the result.
    """
    return object_screen_xy(cmd.x_raw or 0, cmd.y_raw or 0)


def actor_xy(x: int, y: int, *, frame_min: int | None = None, origin: tuple[int, int] | None = None) -> tuple[int, int]:
    """Actor sprite top-left, from the AEPROG actor draw loop at 0x4ef8.

    The draw loop reads x at rec+0x02 (a full-resolution 16-bit X, NOT halved
    like the raw payload x) and y at rec+0x04, then blits via 0x3cc with
    x_arg = x and y_arg = vertical_base + y.  The steady-state room draw passes
    vertical_base = 0xb8 (AEPROG 0x399a/0x399e), so the actor buffer position is
    (x, y + 0xb8) - the same family as every other object, just with X already
    at full resolution.  Cropping at the view origin gives (x - 8, y - 16),
    uniform for every enemy; the old per-frame_min origins were screenshot
    fudges.  `frame_min`/`origin` are kept only for call-site compatibility.
    """
    if origin is not None:
        ox, oy = origin
        return x - ox, y - oy
    return buffer_to_view(x, y + _OBJECT_BUFFER_Y_BIAS)


def actor_origin(frame_min: int | None = None) -> tuple[int, int]:
    """Actor anchor inside the sprite; uniform (8, 16) per AEPROG 0x4ef8."""
    return OBJECT_ORIGIN


def header_object_xy(x_raw: int, y_raw: int) -> tuple[int, int]:
    """Six-slot header diamond top-left, from the AEPROG draw at 0x2e32."""
    return object_screen_xy(x_raw, y_raw)


def header_exit_door_xy(x_raw: int, y_raw: int, sprite: Image.Image) -> tuple[int, int]:
    """Exit-door top-left.  Same shared object anchor as everything else."""
    return object_screen_xy(x_raw, y_raw)
