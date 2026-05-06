"""Terrain tile-code mapping research helpers.

Important distinction:
- Room terrain bytes are logical tile/collision codes.
- They are *not* guaranteed to be direct sprite indexes.

The current best-known mapping is intentionally small and data-driven.  Earlier
builds had several renderer-side special cases that were attempts to compensate
for an off-by-one/misread tile mapping.  Keep those rules here instead of hiding
translation in the renderer.
"""
from __future__ import annotations

# Code 0x00 = empty / background only.
# Code 0x07 = invisible solid/support, not a visible platform sprite.
# 0x80..0xC0 = rope-family special codes rendered from AE000 rope sprites.
#
# Confirmed by comparing room screenshots against AE001:021 sprites:
#   dec 2 should render as AE001:021:6, not AE001:021:5.
#   dec 5 should render as AE001:021:9.
# This implies the non-empty normal tile family is code + 4 for 1..6.
TERRAIN_CODE_TO_SPRITE: dict[int, int | None] = {
    0x00: None,
    0x01: 5,
    0x02: 6,
    0x03: 7,
    0x04: 8,
    0x05: 9,
    0x06: 10,
    # NOTE: 0x07 deliberately omitted/None in renderer logic.
}

# Small editor-side family for the smart brush.  These are the only normal
# terrain bytes with a confirmed sprite mapping, so auto-tiling deliberately
# stays inside this family until the full EXE lookup table is recovered.
AUTO_SOLID_TILE_CODES = frozenset(range(0x01, 0x07))
CONVEYOR_PHYSICS_TILE_CODES = frozenset({0x0F, 0x1F})
ROPE_TILE_CODES = frozenset({0x90, 0xA0, 0xB0, 0xC0})
