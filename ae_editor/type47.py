from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterator

from PIL import Image

from .palette import EGA_RGBI


@dataclass(frozen=True)
class Type47Image:
    subname: str
    payload: bytes


@dataclass(frozen=True)
class DecodedType47:
    image: Image.Image
    colour_table: list[int]
    row_bytes: int
    height: int


def iter_type47(decoded: bytes, rtype: int) -> Iterator[Type47Image]:
    """Yield type 0x47 bitmap payloads embedded in a decoded resource.

    The game stores both direct bitmaps and packed banks. Resource type 0x00 is
    a linear sequence of 0x47 records; resource type 0x01 starts with a 16-bit
    offset table pointing to 0x47 records.
    """
    if rtype == 0x47:
        yield Type47Image("direct", decoded)
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
            yield Type47Image(f"seq_{n:03d}_at_{pos:04x}", decoded[pos + 2 : pos + total])
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
                        yield Type47Image(f"table_{i:03d}_at_{off:04x}", decoded[off + 2 : off + total])


def decode_type47(payload: bytes, mode: str, vga_palette: list[int] | None = None, transparent: bool = False) -> DecodedType47:
    """Decode one type47 payload to a Pillow image.

    Type47 pixels are two 4-bit logical colour indexes per byte. VGA mode maps
    logical colours through bytes 16..31 of the type47 header into the custom
    256-colour palette. EGA mode maps through bytes 0..15 into RGBI colours.
    Logical colour 0 is used as the transparent blit key.
    """
    if len(payload) < 0x22:
        raise ValueError("short type47 payload")

    ega_table = list(payload[:16])
    vga_table = list(payload[16:32])
    row_bytes = payload[0x20]
    height = payload[0x21]
    raw = payload[0x22 : 0x22 + row_bytes * height]
    if row_bytes <= 0 or height <= 0 or len(raw) < row_bytes * height:
        raise ValueError("truncated type47 payload")

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
        return DecodedType47(image, vga_table, row_bytes, height)

    if mode == "ega":
        table = [x & 0x0F for x in ega_table]
        pixels = [table[x] for x in logical]
        if transparent:
            rgba = []
            for ega_index, logical_colour in zip(pixels, logical):
                r, g, b = EGA_RGBI[ega_index]
                rgba.append((r, g, b, 0 if logical_colour == 0 else 255))
            image = Image.new("RGBA", (row_bytes * 2, height))
            image.putdata(rgba)
        else:
            image = Image.new("P", (row_bytes * 2, height))
            image.putdata(pixels)
            flat: list[int] = []
            for r, g, b in EGA_RGBI:
                flat.extend([r, g, b])
            image.putpalette(flat + [0] * (768 - len(flat)))
        return DecodedType47(image, ega_table, row_bytes, height)

    raise ValueError(f"unknown type47 mode: {mode}")
