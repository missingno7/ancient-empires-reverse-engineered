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
    "top_half",
    "bottom_center",
]


# Compact visual objects do not all share the exact same top-left anchor.
# Keep the defaults close to the older renderer, but allow small family-level
# nudges so screenshots can be matched without scattering magic numbers across
# renderer.py.
DEFAULT_COMPACT3_ORIGIN = (12, 20)
BACKGROUND_COMPACT3_DELTA = (3, 2)
FOREGROUND_COMPACT3_DELTA = (0, 2)
LASER_CRYSTAL_DELTA = (0, 2)


@dataclass(frozen=True)
class TerrainAnchor:
    """Top-left offset for terrain sprites relative to their 8×8 cell."""

    x: int = -4
    y: int = -4


TERRAIN_ANCHOR = TerrainAnchor()


def platform_xy(p: PlatformTriplet) -> tuple[int, int]:
    """EXE-derived moving platform/control coordinate conversion.

    The first payload area stores visible platform/control records. The x byte
    uses the same doubled screen-space coordinate family as other room payload
    objects, while y is already a screen-space pixel coordinate. The stored
    point is an object anchor, not bitmap top-left; orientation and sprite
    choice are *not* inferred from collision tile 0x07.
    """
    # Screenshot calibration: the previous global anchor placed every visible
    # platform 8 px too low.
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
    """Convert a compact3 payload entry to sprite top-left coordinates."""
    if mode == "top_half":
        return entry.x_raw * 2, entry.y
    if mode == "bottom_center":
        return entry.x_raw * 2 - sprite.width // 2, entry.y - sprite.height
    # Compact3 visual records store x in half-screen units. The EXE then
    # passes x*2 to the blitter. The stored point is near a logical object
    # anchor rather than the bitmap top-left, so we keep a configurable origin
    # and apply small family-specific deltas from the renderer.
    ox, oy = origin or DEFAULT_COMPACT3_ORIGIN
    dx, dy = delta
    return entry.x_raw * 2 - ox + dx, entry.y - oy + dy


def control_xy(cmd: ControlCommand, *, mode: str = "button") -> tuple[int, int]:
    """Convert a length-prefixed control command body to screen coordinates.

    Important: cmd.x_raw/cmd.y_raw are body bytes, not the length prefix.
    Control commands are not one coordinate family:
    * ceiling buttons are anchored by the hanging cord/trigger point;
    * floor switches are anchored close to their base on the floor;
    * runtime actors are stored in the part actor table and use direct x/y words.
    """
    x_raw = cmd.x_raw or 0
    y_raw = cmd.y_raw or 0
    if mode == "laser_trigger":
        # Trigger pads were consistently a little too low in captured rooms.
        return x_raw * 2 - 8, y_raw - 18
    if mode == "ceiling_button":
        return x_raw * 2 - 12, y_raw - 14
    if mode == "floor_switch":
        return x_raw * 2 - 12, y_raw - 16
    return x_raw * 2 - 12, y_raw - 16


# Actor-table coordinates are logical anchors, not necessarily bitmap top-lefts.
# The values below intentionally preserve the old default (-12, -12), but make
# it data-driven so individual enemy families can be calibrated against real
# screenshots without adding one-off renderer hacks.  Keys are actor frame_min
# values, i.e. the stable start of the enemy animation range.
ACTOR_ORIGIN_BY_FRAME_MIN: dict[int, tuple[int, int]] = {
    0x00: (12, 12),  # ant
    0x08: (12, 12),  # bat
    0x0F: (12, 12),  # green spitter
    0x2B: (12, 14),  # ladybug - slightly too low with the generic anchor
    0x32: (12, 12),  # scorpion shooter
    0x37: (12, 12),  # spider
    0x3F: (12, 20),  # snake
}


def actor_xy(x: int, y: int, *, frame_min: int | None = None, origin: tuple[int, int] | None = None) -> tuple[int, int]:
    """Convert actor-table anchor coordinates to sprite top-left coordinates.

    `origin` is the pixel inside the sprite that sits on the actor-table x/y.
    When unknown, use the historically best global anchor.  This is separate
    from player_start because the player preview already aligns well and comes
    from the level header, not from the runtime actor table.
    """
    ox, oy = origin or ACTOR_ORIGIN_BY_FRAME_MIN.get(frame_min if frame_min is not None else -1, (12, 12))
    return x - ox, y - oy


def actor_origin(frame_min: int | None = None) -> tuple[int, int]:
    return ACTOR_ORIGIN_BY_FRAME_MIN.get(frame_min if frame_min is not None else -1, (12, 12))


def header_object_xy(x_raw: int, y_raw: int) -> tuple[int, int]:
    """Convert six-slot header object coordinates to sprite top-left coordinates."""
    # Collectibles sat a touch low compared with real screenshots.
    return x_raw * 2 - 8, y_raw - 16


def header_exit_door_xy(x_raw: int, y_raw: int, sprite: Image.Image) -> tuple[int, int]:
    """Convert the header exit-door anchor to sprite top-left coordinates."""
    return x_raw * 2 - 12, y_raw - 16
