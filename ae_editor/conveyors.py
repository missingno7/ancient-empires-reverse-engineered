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

This module composes AE000:038 art and exposes helpers for both sides of a belt.  The terrain codes 0x0F/0x1F are the physics/scrolling footprint.  Visible belts are CV records in the room payload directory header.  The first ten room payload triplets are platform/control runtime slots; the editor must not write them for belts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PIL import Image

from .constants import ROOM_COLUMNS, ROOM_ROWS

BeltKind = Literal["grey", "teal"]


@dataclass(frozen=True)
class ConveyorSpec:
    kind: BeltKind
    x: int
    y: int
    width: int
    frame: int = 0
    note: str = ""


@dataclass(frozen=True)
class ConveyorRecord:
    """Legacy experimental payload record decoder.

    Normal belts should not use this. Visible belts use ConveyorVisualRecord.

    It intentionally mirrors the three-byte records used by the EXE at the
    beginning of the room trailing payload.  The low nibble is an animation
    counter/state, while the high bits select the movement family.  The exact
    direction naming is still under research; for editing we preserve this as
    a compact object instead of pretending that terrain bytes are the visual.
    """

    source_offset: int
    index: int
    flags: int
    x_raw: int
    y: int
    raw: bytes

    @property
    def kind(self) -> BeltKind:
        return "teal" if (self.flags & 0x80) else "grey"

    @property
    def frame(self) -> int:
        return self.flags & 0x03

    @property
    def label(self) -> str:
        return f"belt[{self.index}] f={self.flags:02X} x={self.x_raw:02X} y={self.y:02X}"




@dataclass(frozen=True)
class ConveyorVisualRecord:
    """Visible conveyor object stored in the room payload directory.

    This is the CV object the game uses to draw the belt.  The terrain tile run
    0x0F/0x1F is only the physics/scrolling footprint; if the CV record is
    missing the player is pushed by an invisible belt.

    Layout at trailing+0x1E:
        count, then count records of four bytes: x_raw, y, code, props.

    Current confirmed coordinate model from original rooms:
        start_cell_x = (x_raw - 2) / 4
        cell_y       = (y - 12) / 8
        tile_length  = code + 2
    """

    source_offset: int
    index: int
    x_raw: int
    y: int
    code: int
    props: int
    raw: bytes

    @property
    def start_x(self) -> int:
        return max(0, min(ROOM_COLUMNS - 1, round((self.x_raw - 2) / 4)))

    @property
    def cell_y(self) -> int:
        return max(0, min(ROOM_ROWS - 1, round((self.y - 12) / 8)))

    @property
    def length(self) -> int:
        return max(1, min(ROOM_COLUMNS, int(self.code) + 2))

    @property
    def cells(self) -> set[tuple[int, int]]:
        return {(x, self.cell_y) for x in range(self.start_x, min(ROOM_COLUMNS, self.start_x + self.length))}

    @property
    def label(self) -> str:
        return f"CV{self.index} x={self.start_x} y={self.cell_y} len={self.length} raw={self.raw.hex(' ')}"

DEFAULT_CONVEYOR_FLAGS: dict[BeltKind, int] = {
    # Low nibble 6 matches the EXE initial/reset value seen around the belt
    # animation routine.  Bit 0x80 selects the second AE000:038 art family.
    "grey": 0x06,
    "teal": 0x86,
}


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


@dataclass(frozen=True)
class ConveyorRun:
    """Editable conveyor strip backed by terrain tile runs 0x0F/0x1F.

    Terrain codes 0x0F/0x1F are the physics/scrolling footprint.  They must be
    paired with a CV payload record to be visible in the original game.  The
    renderer uses tile runs only to identify the footprint and grey/teal family;
    it does not write platform/runtime triplets for belts.
    """

    index: int
    kind: BeltKind
    code: int
    start_x: int
    y: int
    length: int

    @property
    def cells(self) -> set[tuple[int, int]]:
        return {(x, self.y) for x in range(self.start_x, self.start_x + self.length)}

    @property
    def label(self) -> str:
        return f"belt[{self.index}] {self.kind} x={self.start_x} y={self.y} len={self.length}"


def iter_conveyor_runs(room) -> list[ConveyorRun]:
    """Return all visible/editable conveyor tile runs in a room."""
    runs: list[ConveyorRun] = []
    code_to_kind: dict[int, BeltKind] = {0x0F: "grey", 0x1F: "teal"}
    for y in range(ROOM_ROWS):
        x = 0
        while x < ROOM_COLUMNS:
            code = room.get(x, y)
            kind = code_to_kind.get(code)
            if kind is None:
                x += 1
                continue
            start = x
            while x < ROOM_COLUMNS and room.get(x, y) == code:
                x += 1
            runs.append(ConveyorRun(len(runs), kind, code, start, y, x - start))
    return runs
