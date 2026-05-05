from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from .palette import dac6_to_pillow_palette, find_vga_palette_dac6
from .type47 import decode_type47, iter_type47
from .constants import (
    SPRITE_BANK_SCAN_END,
    SPRITE_BANK_SCAN_START,
    TERRAIN_BANK_COUNT,
    TERRAIN_BANK_RESOURCE_START,
)
from .dat_archive import DatArchive


@dataclass
class SpriteRef:
    resource_id: int
    subname: str
    image: Image.Image


class GraphicsSet:
    """Decoded VGA graphics banks used by the editor.

    The game uses type 0x47 images. In VGA mode each logical 4-bit pixel is
    mapped through the second 16-byte colour table to the custom 256-colour VGA
    palette embedded in AEPROG.EXE. Logical colour 0 is used as a transparent key
    for sprites.
    """

    def __init__(self, ae001: DatArchive, exe_path: Path | str):
        _, dac = find_vga_palette_dac6(Path(exe_path))
        self.vga_palette = dac6_to_pillow_palette(dac)
        self.banks: dict[int, list[Image.Image]] = {}
        self.refs: dict[int, list[SpriteRef]] = {}
        self.terrain_banks: list[list[Image.Image]] = []

        for rid in range(SPRITE_BANK_SCAN_START, min(SPRITE_BANK_SCAN_END, len(ae001))):
            bank, refs = self._load_bank(ae001, rid)
            if bank:
                self.banks[rid] = bank
                self.refs[rid] = refs

        for theme in range(TERRAIN_BANK_COUNT):
            rid = TERRAIN_BANK_RESOURCE_START + theme
            self.terrain_banks.append(self.banks.get(rid, []))

    def _load_bank(self, dat: DatArchive, resource_id: int) -> tuple[list[Image.Image], list[SpriteRef]]:
        res = dat[resource_id]
        images: list[Image.Image] = []
        refs: list[SpriteRef] = []
        if not res.ok:
            return images, refs
        for bitmap in iter_type47(res.decoded, res.rtype):
            try:
                decoded = decode_type47(bitmap.payload, "vga", self.vga_palette, transparent=True)
            except Exception:
                continue
            rgba = decoded.image.convert("RGBA")
            images.append(rgba)
            refs.append(SpriteRef(resource_id, bitmap.subname, rgba))
        return images, refs

    def terrain_sprite(self, theme: int, sprite_index: int) -> Image.Image | None:
        bank = self.terrain_banks[theme % len(self.terrain_banks)] if self.terrain_banks else []
        if 0 <= sprite_index < len(bank):
            return bank[sprite_index]
        return None

    def terrain_background(self, theme: int) -> Image.Image | None:
        bank = self.terrain_banks[theme % len(self.terrain_banks)] if self.terrain_banks else []
        # Empirically: the large background/wall image sits at index 11 in the
        # terrain banks. Fallback to the first image keeps the app usable if a
        # variant bank is shorter.
        if len(bank) > 11:
            return bank[11]
        return bank[0] if bank else None

    @staticmethod
    def make_bank_sheet(resource_id: int, bank: list[Image.Image], limit: int = 160) -> Image.Image:
        if not bank:
            return Image.new("RGB", (220, 80), "white")
        thumbs: list[Image.Image] = []
        for i, sprite in enumerate(bank[:limit]):
            scale = max(1, min(3, 64 // max(1, max(sprite.size))))
            sim = sprite.resize((sprite.width * scale, sprite.height * scale), Image.Resampling.NEAREST)
            cell = Image.new("RGBA", (max(84, sim.width), sim.height + 15), (255, 255, 255, 255))
            ImageDraw.Draw(cell).text((1, 1), f"{resource_id}:{i}", fill=(0, 0, 0, 255))
            cell.alpha_composite(sim, (0, 15))
            thumbs.append(cell.convert("RGB"))
        cols = 5
        cw = max(t.width for t in thumbs) + 8
        ch = max(t.height for t in thumbs) + 8
        sheet = Image.new("RGB", (cols * cw, ((len(thumbs) + cols - 1) // cols) * ch), "white")
        for n, thumb in enumerate(thumbs):
            sheet.paste(thumb, ((n % cols) * cw + 4, (n // cols) * ch + 4))
        return sheet
