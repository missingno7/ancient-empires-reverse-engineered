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

from .constants import CELL_SIZE
from .room_payload import ControlCommand, ObjectTableEntry, PlatformTriplet

AnchorMode = Literal[
    "terrain",
    "screen_exe",
    "top_half",
    "bottom_center",
]


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
    return p.x_raw * 2 - 12, p.y - 12


def compact3_xy(entry: ObjectTableEntry, sprite: Image.Image, mode: AnchorMode = "screen_exe") -> tuple[int, int]:
    """Convert a compact3 payload entry to sprite top-left coordinates."""
    if mode == "top_half":
        return entry.x_raw * 2, entry.y
    if mode == "bottom_center":
        return entry.x_raw * 2 - sprite.width // 2, entry.y - sprite.height
    # Compact3 visual records store x in half-screen units. The EXE then
    # passes x*2 to the blitter. We subtract a small sprite-anchor correction
    # because the stored point is closer to a logical anchor than to bitmap
    # top-left.
    return entry.x_raw * 2 - 12, entry.y - 20


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
    if mode == "actor":
        # Kept for old debug overlays.  Normal enemy rendering now reads the
        # actor table at part+0x2754 instead of command-2 control records.
        return x_raw * 2 - 12, y_raw - 28
    if mode == "laser_trigger":
        return x_raw * 2 - 12, y_raw - 12
    if mode == "ceiling_button":
        return x_raw * 2 - 12, y_raw - 20
    if mode == "floor_switch":
        return x_raw * 2 - 12, y_raw - 12
    return x_raw * 2 - 12, y_raw - 16


def actor_xy(x: int, y: int) -> tuple[int, int]:
    """Convert actor-table screen coordinates to sprite top-left coordinates."""
    return x - 12, y - 12


def header_object_xy(x_raw: int, y_raw: int) -> tuple[int, int]:
    """Convert six-slot header object coordinates to sprite top-left coordinates."""
    return x_raw * 2 - 12, y_raw - 12
