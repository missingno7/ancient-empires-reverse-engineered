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
from .room_payload import ObjectTableEntry, PlatformTriplet

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
    is in half-pixel-ish units, while y is already a screen-space pixel
    coordinate. Keep this transform boring and centralized; orientation and
    sprite choice are *not* inferred from collision tile 0x07.
    """
    return p.x_raw * 2 - 4, p.y


def compact3_xy(entry: ObjectTableEntry, sprite: Image.Image, mode: AnchorMode = "screen_exe") -> tuple[int, int]:
    """Convert a compact3 payload entry to sprite top-left coordinates."""
    if mode == "top_half":
        return entry.x_raw * 2, entry.y
    if mode == "bottom_center":
        return entry.x_raw * 2 - sprite.width // 2, entry.y - sprite.height
    # Best current model for EXE visual compact3 records. Screenshot matching
    # showed the v27/v28 decor was consistently a little too far right/down.
    # Use a small global anchor correction here instead of per-object hacks.
    return entry.x_raw * 2 - 12, entry.y - 20
