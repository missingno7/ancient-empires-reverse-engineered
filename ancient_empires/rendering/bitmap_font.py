from __future__ import annotations

from dataclasses import dataclass

from PIL import Image


@dataclass(frozen=True)
class BitmapFont:
    """Decoded AEPROG 1bpp menu font resource.

    AEPROG loads AE000 font resources 0/1 at 0x21a9.  The blob layout recovered
    from 0x6ca6/0x6cf6/0x6d3c is:

        +1 glyph_count-1, +2 line_height,
        then width[], offset_lo[], offset_hi[], then packed glyph rows.

    Character codes index the tables directly.  Glyph rows are stored MSB-first,
    one row after another, with ``ceil(width / 8)`` bytes per row.
    """

    widths: tuple[int, ...]
    offsets: tuple[int, ...]
    line_height: int
    bitmap: bytes

    @classmethod
    def from_resource(cls, blob: bytes) -> "BitmapFont":
        if len(blob) < 6:
            raise ValueError("font blob is too short")
        count = blob[1] + 1
        line_height = blob[2]
        table_end = 3 + count * 3
        if len(blob) < table_end:
            raise ValueError("font blob table is truncated")
        widths = tuple(blob[3 : 3 + count])
        offset_lo = blob[3 + count : 3 + count * 2]
        offset_hi = blob[3 + count * 2 : table_end]
        offsets = tuple(lo | (hi << 8) for lo, hi in zip(offset_lo, offset_hi))
        return cls(widths=widths, offsets=offsets, line_height=line_height, bitmap=blob[table_end:])

    def char_width(self, ch: str) -> int:
        code = ord(ch)
        if 0 <= code < len(self.widths):
            return int(self.widths[code])
        return 0

    def measure(self, text: str) -> int:
        width = 0
        widest = 0
        for ch in text:
            if ch in "\n\r":
                widest = max(widest, width)
                width = 0
            else:
                width += self.char_width(ch)
        return max(widest, width)

    def draw(self, image: Image.Image, xy: tuple[int, int], text: str, color: tuple[int, int, int, int] | tuple[int, int, int]) -> None:
        """Draw text into an RGBA/RGB/L image using the original menu glyphs."""
        start_x, y = xy
        x = start_x
        for ch in text:
            if ch in "\n\r":
                x = start_x
                y += self.line_height
                continue
            self._draw_char(image, x, y, ch, color)
            x += self.char_width(ch)

    def draw_centered(self, image: Image.Image, y: int, text: str, color: tuple[int, int, int, int] | tuple[int, int, int]) -> None:
        self.draw(image, ((image.width - self.measure(text)) // 2, y), text, color)

    def _draw_char(self, image: Image.Image, x: int, y: int, ch: str, color) -> None:
        code = ord(ch)
        if not (0 <= code < len(self.widths)):
            return
        width = self.widths[code]
        if width <= 0:
            return
        offset = self.offsets[code]
        row_bytes = (width + 7) // 8
        for row in range(self.line_height):
            src = offset + row * row_bytes
            if src + row_bytes > len(self.bitmap):
                break
            py = y + row
            if not (0 <= py < image.height):
                continue
            for col in range(width):
                byte = self.bitmap[src + col // 8]
                if byte & (0x80 >> (col & 7)):
                    px = x + col
                    if 0 <= px < image.width:
                        image.putpixel((px, py), color)
