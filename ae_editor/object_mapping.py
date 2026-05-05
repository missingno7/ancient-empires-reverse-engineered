"""Best-known mapping from room payload visual codes to sprites.

The EXE draws the main compact3 visual list in two passes:

* entries with code >= 0x80 are drawn before the terrain pass;
* entries with code < 0x80 are drawn after the terrain pass.

Most high-bit entries are background/theme decorations. A few known gameplay
objects use high-bit codes too; those are marked as foreground exceptions here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .room_payload import ObjectTableEntry

RenderLayer = Literal["background", "foreground"]


@dataclass(frozen=True)
class SpriteRef:
    archive: str
    resource_id: int
    sprite_index: int
    note: str = ""
    flip_h: bool = False


def visual_sprite_ref(entry: ObjectTableEntry, *, theme: int, level_index: int | None = None, room_index: int | None = None, page_index: int | None = None) -> SpriteRef:
    code = entry.code

    # Confirmed global/gameplay objects from screenshots and asset browsing.
    if code == 0x0E:
        return SpriteRef("AE000", 39, 0, "button")
    if code == 0x8E:
        return SpriteRef("AE000", 44, 0, "diamond/artifact pickup")
    if code == 0x7D:
        return SpriteRef("AE000", 19, 2, "rotating laser crystal candidate")

    # Do not treat compact3 code 0x02 as a global actor.  Several confirmed
    # rooms use low visual codes as ordinary theme decorations; actors appear
    # to live in control/actor records, not in the main theme visual table.

    # Laser trigger / red pudding-looking trigger in level 2 Expert room 0.
    if code == 0x80 and level_index == 1 and page_index == 1 and room_index == 0:
        return SpriteRef("AE000", 41, 0, "laser trigger")

    # Default EXE-style visual decor: current theme bank AE001:025..028 and
    # code masked to six bits. Bit 0x40 behaves as a horizontal mirror flag for
    # at least the paired statue/lion decorations (for example code 0x45 is the
    # mirrored variant of code 0x05 in level 14 Expert room 2).
    return SpriteRef("AE001", 25 + theme, code & 0x3F, "theme visual", flip_h=bool(code & 0x40))


def visual_render_layer(entry: ObjectTableEntry, *, level_index: int | None = None, room_index: int | None = None, page_index: int | None = None) -> RenderLayer:
    """Return the EXE-style render pass for a visual compact3 entry.

    The generic rule is code>=0x80 before terrain, code<0x80 after terrain.
    Known gameplay exceptions stay foreground so they are not buried under
    terrain.
    """
    code = entry.code
    if code in {0x0E, 0x7D, 0x8E}:
        return "foreground"
    if code == 0x80 and level_index == 1 and page_index == 1 and room_index == 0:
        return "foreground"
    return "background" if code >= 0x80 else "foreground"
