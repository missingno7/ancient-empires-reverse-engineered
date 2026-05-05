"""Coordinate conversion helpers for room payload research.

The game uses a visible 38x18 tile room. Terrain is on an 8px grid, while
payload records use byte coordinates that are not always a direct top-left
pixel.  Keeping the known conversions here makes renderer hacks easier to spot.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PIL import Image

from .constants import CELL_SIZE
from .room_payload import ObjectTableEntry, PlatformTriplet

AnchorMode = Literal[
    "top_exe",          # x = raw*2, y = raw y, top-left
    "bottom_center",    # x = raw*2 center, y = baseline/bottom
    "tile_top",         # x = raw*8, y = raw y
    "actor_top_2x",     # x = raw*2, y = raw y*2
    "actor_bottom_2x",  # x = raw*2 center, y = raw y*2 baseline
]


@dataclass(frozen=True)
class ScreenBias:
    """Optional global render bias.

    Some screenshots suggest the final VGA viewport may be blitted with a small
    sub-tile offset relative to the raw terrain grid.  The default is zero.  Use
    the GUI alignment controls to test +4/+4 without baking it into the format.
    """

    x: int = 0
    y: int = 0


def platform_xy(p: PlatformTriplet) -> tuple[int, int]:
    """EXE-derived moving-platform coordinate conversion.

    Static notes from the platform loop: byte1 is shifted left once and biased
    by -4.  byte2 is already a pixel-ish Y coordinate.
    """
    return p.x_raw * 2 - 4, p.y


def compact3_xy(entry: ObjectTableEntry, sprite: Image.Image, mode: AnchorMode) -> tuple[int, int]:
    """Convert a compact3 payload entry to a sprite top-left coordinate."""
    if mode == "top_exe":
        return entry.x_raw * 2, entry.y
    if mode == "bottom_center":
        return entry.x_raw * 2 - sprite.width // 2, entry.y - sprite.height
    if mode == "tile_top":
        return entry.x_raw * CELL_SIZE, entry.y
    if mode == "actor_top_2x":
        return entry.x_raw * 2, entry.y * 2
    if mode == "actor_bottom_2x":
        return entry.x_raw * 2 - sprite.width // 2, entry.y * 2 - sprite.height
    return entry.x_raw * 2, entry.y
