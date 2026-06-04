from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterator

from PIL import Image

from .palette import CGA_PALETTE_1_HIGH, GAME_EGA_RGB, cga_colour_from_table_byte


"""Decoder for Ancient Empires game graphics bitmap records.

These records store small EGA/VGA bitmap sprites and terrain/decor images used
by the game. The on-disk marker byte is ``0x47``.
"""


@dataclass(frozen=True)
class GameGraphicsRecord:
    subname: str
    payload: bytes


@dataclass(frozen=True)
class DecodedGameGraphic:
    image: Image.Image
    colour_table: list[int]
    row_bytes: int
    height: int


def decode_answer_symbol_bank(decoded: bytes) -> list[Image.Image]:
    """Decode the monochrome 40x29 symbol bank used by the exit-door puzzle.

    AE001 resource 34 is a type-1 offset table, but its entries are not normal
    0x47 graphics records. Each entry is four header bytes followed by a
    40x29, one-bit bitmap (five bytes per row). The game draws these symbols
    over the white question cells at AEPROG 0x9a0e.
    """
    if len(decoded) < 4:
        return []
    table_bytes = int.from_bytes(decoded[:2], "little")
    count = table_bytes // 2 - 1
    if count <= 0 or table_bytes > len(decoded):
        return []

    images: list[Image.Image] = []
    for index in range(count):
        offset = int.from_bytes(decoded[index * 2:index * 2 + 2], "little")
        payload = decoded[offset + 4:offset + 4 + 5 * 29]
        if len(payload) != 5 * 29:
            break
        image = Image.new("RGBA", (40, 29), (0, 0, 0, 0))
        pixels = image.load()
        for y in range(29):
            for x in range(40):
                if payload[y * 5 + x // 8] & (0x80 >> (x & 7)):
                    pixels[x, y] = (0, 0, 0, 255)
        images.append(image)
    return images


def iter_game_graphics_records(decoded: bytes, rtype: int) -> Iterator[GameGraphicsRecord]:
    """Yield game graphics bitmap payloads embedded in a decoded resource.

    The game stores both direct bitmaps and packed banks. Resource type 0x00 is
    a linear sequence of 0x47 records; resource type 0x01 starts with a 16-bit
    offset table pointing to 0x47 records.
    """
    if rtype == 0x47:
        yield GameGraphicsRecord("direct", decoded)
        return

    if rtype == 0x00:
        pos = 0
        n = 0
        while pos + 36 <= len(decoded) and decoded[pos] == 0x47:
            row_bytes = decoded[pos + 0x22]
            height = decoded[pos + 0x23]
            total = 0x24 + row_bytes * height
            if not row_bytes or not height or pos + total > len(decoded):
                break
            # Strip the leading 0x47 and one unused/control byte. The payload
            # starts with the 16-byte EGA table, then the 16-byte VGA table.
            yield GameGraphicsRecord(f"seq_{n:03d}_at_{pos:04x}", decoded[pos + 2 : pos + total])
            pos += total
            n += 1
        return

    if rtype == 0x01 and len(decoded) >= 2:
        table_bytes = struct.unpack_from("<H", decoded, 0)[0]
        count = table_bytes // 2 - 1
        if 0 < count < 10000 and table_bytes <= len(decoded):
            for i in range(count):
                off = struct.unpack_from("<H", decoded, i * 2)[0]
                if off + 36 <= len(decoded) and decoded[off] == 0x47:
                    row_bytes = decoded[off + 0x22]
                    height = decoded[off + 0x23]
                    total = 0x24 + row_bytes * height
                    if row_bytes and height and off + total <= len(decoded):
                        yield GameGraphicsRecord(f"table_{i:03d}_at_{off:04x}", decoded[off + 2 : off + total])


def decode_game_graphics_record(payload: bytes, mode: str, vga_palette: list[int] | None = None, transparent: bool = False, ega_palette: list[tuple[int, int, int]] | None = None) -> DecodedGameGraphic:
    """Decode one game graphics bitmap payload to a Pillow image.

    Game graphics pixels are two 4-bit logical colour indexes per byte. VGA mode maps
    logical colours through bytes 16..31 of the game graphics header into the custom
    256-colour palette. EGA mode maps through bytes 0..15 into RGBI colours.
    Logical colour 0 is used as the transparent blit key.
    """
    if len(payload) < 0x22:
        raise ValueError("short game graphics payload")

    ega_table = list(payload[:16])
    vga_table = list(payload[16:32])
    ega_rgb = ega_palette or GAME_EGA_RGB
    row_bytes = payload[0x20]
    height = payload[0x21]
    raw = payload[0x22 : 0x22 + row_bytes * height]
    if row_bytes <= 0 or height <= 0 or len(raw) < row_bytes * height:
        raise ValueError("truncated game graphics payload")

    logical: list[int] = []
    for byte in raw:
        logical.append((byte >> 4) & 0x0F)
        logical.append(byte & 0x0F)

    if mode == "vga":
        if vga_palette is None:
            raise ValueError("VGA decoding requires a Pillow palette")
        pixels = [vga_table[x] for x in logical]
        if transparent:
            rgba = []
            for palette_index, logical_colour in zip(pixels, logical):
                r, g, b = vga_palette[palette_index * 3 : palette_index * 3 + 3]
                rgba.append((r, g, b, 0 if logical_colour == 0 else 255))
            image = Image.new("RGBA", (row_bytes * 2, height))
            image.putdata(rgba)
        else:
            image = Image.new("P", (row_bytes * 2, height))
            image.putdata(pixels)
            image.putpalette(vga_palette)
        return DecodedGameGraphic(image, vga_table, row_bytes, height)

    if mode == "ega":
        table = [x & 0x0F for x in ega_table]
        pixels = [table[x] for x in logical]
        if transparent:
            rgba = []
            for ega_index, logical_colour in zip(pixels, logical):
                r, g, b = ega_rgb[ega_index]
                rgba.append((r, g, b, 0 if logical_colour == 0 else 255))
            image = Image.new("RGBA", (row_bytes * 2, height))
            image.putdata(rgba)
        else:
            image = Image.new("P", (row_bytes * 2, height))
            image.putdata(pixels)
            flat: list[int] = []
            for r, g, b in ega_rgb:
                flat.extend([r, g, b])
            image.putpalette(flat + [0] * (768 - len(flat)))
        return DecodedGameGraphic(image, ega_table, row_bytes, height)

    if mode == "cga":
        # CGA is encoded directly in the first 16-byte colour table.  The low
        # nibble is the EGA colour register, while the high nibble is half of
        # the repeated 2-bit CGA pixel pattern: 0, 5, A, F -> colours 0..3.
        # This is why a nearest-colour reduction from EGA/VGA is wrong: the
        # game artists already chose the four-colour mapping per image.
        cga_lookup = [cga_colour_from_table_byte(x) for x in ega_table]
        pixels = [cga_lookup[x] for x in logical]
        if transparent:
            rgba = []
            for cga_index, logical_colour in zip(pixels, logical):
                r, g, b = CGA_PALETTE_1_HIGH[cga_index]
                rgba.append((r, g, b, 0 if logical_colour == 0 else 255))
            image = Image.new("RGBA", (row_bytes * 2, height))
            image.putdata(rgba)
        else:
            image = Image.new("P", (row_bytes * 2, height))
            image.putdata(pixels)
            flat: list[int] = []
            for r, g, b in CGA_PALETTE_1_HIGH:
                flat.extend([r, g, b])
            image.putpalette(flat + [0] * (768 - len(flat)))
        return DecodedGameGraphic(image, cga_lookup, row_bytes, height)

    raise ValueError(f"unknown game graphics mode: {mode}")
