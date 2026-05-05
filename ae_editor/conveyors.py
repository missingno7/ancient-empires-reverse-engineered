"""Conveyor belt rendering helpers.

AE000:038 stores conveyor art as strips, not as one sprite per object:

    grey frame 0:  0 left,  1 middle,  2 right
    grey frame 1:  3 left,  4 middle,  5 right
    grey frame 2:  6 left,  7 middle,  8 right
    grey frame 3:  9 left, 10 middle, 11 right
    teal frame 0: 12 left, 13 middle, 14 right
    teal frame 1: 15 left, 16 middle, 17 right
    teal frame 2: 18 left, 19 middle, 20 right
    teal frame 3: 21 left, 22 middle, 23 right

This module only knows how to compose AE000:038 art. The decision that terrain code 0x0F/0x1F means a belt lives in renderer.py until the EXE lookup table is fully named.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PIL import Image

BeltKind = Literal["grey", "teal"]


@dataclass(frozen=True)
class ConveyorSpec:
    kind: BeltKind
    x: int
    y: int
    width: int
    frame: int = 0
    note: str = ""



def frame_base(kind: BeltKind, frame: int = 0) -> int:
    """Return AE000:038 sprite index for the left cap of kind/frame."""
    frame = max(0, min(3, frame))
    family_base = 0 if kind == "grey" else 12
    return family_base + frame * 3


def compose_conveyor(parts: list[Image.Image | None], spec: ConveyorSpec) -> Image.Image | None:
    """Compose a left/middle/right conveyor strip into one RGBA image."""
    base = frame_base(spec.kind, spec.frame)
    if base + 2 >= len(parts):
        return None
    left, middle, right = parts[base], parts[base + 1], parts[base + 2]
    if left is None or middle is None or right is None:
        return None

    width = max(left.width + right.width, int(spec.width))
    height = max(left.height, middle.height, right.height)
    out = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    out.alpha_composite(left, (0, 0))
    xx = left.width
    middle_end = max(xx, width - right.width)
    while xx < middle_end:
        out.alpha_composite(middle, (xx, 0))
        xx += middle.width
    out.alpha_composite(right, (width - right.width, 0))
    return out
