"""Best-known mapping from room payload visual codes to sprites.

This is intentionally isolated from the renderer. Some compact3 visual codes
index the current theme decoration bank directly, while some codes are routed
through global gameplay/object banks in AE000. The exact EXE lookup table has
not been fully reconstructed yet, so confirmed non-theme objects live here as a
small explicit table rather than being hidden as renderer hacks.
"""
from __future__ import annotations

from dataclasses import dataclass

from .room_payload import ObjectTableEntry


@dataclass(frozen=True)
class SpriteRef:
    archive: str
    resource_id: int
    sprite_index: int
    note: str = ""


def visual_sprite_ref(entry: ObjectTableEntry, *, theme: int, level_index: int | None = None, room_index: int | None = None, page_index: int | None = None) -> SpriteRef:
    code = entry.code

    # Confirmed global/gameplay objects from screenshots and asset browsing.
    if code == 0x0E:
        return SpriteRef("AE000", 39, 0, "ceiling/floor button")
    if code == 0x8E:
        return SpriteRef("AE000", 44, 0, "diamond/artifact pickup")
    if code == 0x7D:
        return SpriteRef("AE000", 19, 2, "rotating laser crystal candidate")

    # Code 0x02 is an actor family. It is not fully solved; these are the two
    # confirmed cases seen so far. Keeping this here makes the uncertainty
    # visible instead of spreading room checks through the renderer.
    if code == 0x02:
        if level_index == 1 and page_index == 1 and room_index == 0:
            return SpriteRef("AE000", 22, 12, "spider")
        return SpriteRef("AE000", 22, 20, "crawler/snake family")

    # Laser trigger / red pudding-looking trigger. In most rooms high-bit codes
    # index the theme decoration bank, but L2 Expert room 0 has a confirmed
    # AE000:041 trigger at this compact3 entry.
    if code == 0x80 and level_index == 1 and page_index == 1 and room_index == 0:
        return SpriteRef("AE000", 41, 0, "laser trigger")

    # Default EXE-style visual decor: current theme bank AE001:025..028 and
    # code masked to six bits. This covers AE001:026:0..5, :20, :23, etc.
    return SpriteRef("AE001", 25 + theme, code & 0x3F, "theme visual")
