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
    archive_name: str
    resource_id: int
    subname: str
    image: Image.Image


class GraphicsSet:
    """Decoded VGA graphics banks used by the editor.

    The game uses type 0x47 images. In VGA mode each logical 4-bit pixel is
    mapped through the second 16-byte colour table to the custom 256-colour VGA
    palette embedded in AEPROG.EXE. Logical colour 0 is used as a transparent key
    for sprites.

    v17 change: graphics are loaded from both AE001.DAT and AE000.DAT.  Earlier
    builds only showed AE001:21..28, which are terrain/decor banks.  Many actor,
    UI and gameplay sprites live in AE000 lower-numbered resources, so the bank
    browser now uses source-qualified bank ids such as "AE000:020".
    """

    def __init__(self, ae001: DatArchive, exe_path: Path | str, ae000: DatArchive | None = None):
        _, dac = find_vga_palette_dac6(Path(exe_path))
        self.vga_palette = dac6_to_pillow_palette(dac)
        self.banks: dict[str, list[Image.Image]] = {}
        self.refs: dict[str, list[SpriteRef]] = {}
        self.ae001_banks: dict[int, list[Image.Image]] = {}
        self.ae000_banks: dict[int, list[Image.Image]] = {}
        self.terrain_banks: list[list[Image.Image]] = []

        self._load_archive_banks("AE001", ae001)
        if ae000 is not None:
            self._load_archive_banks("AE000", ae000)

        for theme in range(TERRAIN_BANK_COUNT):
            rid = TERRAIN_BANK_RESOURCE_START + theme
            self.terrain_banks.append(self.ae001_banks.get(rid, []))

    def _load_archive_banks(self, archive_name: str, dat: DatArchive) -> None:
        # Scan the full DAT.  This is cheap for these small archives and avoids
        # hiding useful actor banks below resource 21.
        for rid in range(0, len(dat)):
            bank, refs = self._load_bank(dat, archive_name, rid)
            if bank:
                key = f"{archive_name}:{rid:03d}"
                self.banks[key] = bank
                self.refs[key] = refs
                if archive_name == "AE001":
                    self.ae001_banks[rid] = bank
                elif archive_name == "AE000":
                    self.ae000_banks[rid] = bank

    def _load_bank(self, dat: DatArchive, archive_name: str, resource_id: int) -> tuple[list[Image.Image], list[SpriteRef]]:
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
            refs.append(SpriteRef(archive_name, resource_id, bitmap.subname, rgba))
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


    def sprite(self, archive_name: str, resource_id: int, sprite_index: int = 0) -> Image.Image | None:
        """Return a decoded sprite by source-qualified DAT resource.

        Example: sprite("AE000", 44, 0) returns the artifact/diamond sprite.
        This helper keeps renderer code independent from the internal bank
        dictionaries and makes known gameplay-object rendering explicit.
        """
        key = f"{archive_name}:{resource_id:03d}"
        bank = self.banks.get(key, [])
        if 0 <= sprite_index < len(bank):
            return bank[sprite_index]
        return None

    @staticmethod
    def make_bank_sheet(resource_id: str | int, bank: list[Image.Image], limit: int = 160) -> Image.Image:
        if not bank:
            return Image.new("RGB", (220, 80), "white")
        label_prefix = str(resource_id)
        thumbs: list[Image.Image] = []
        for i, sprite in enumerate(bank[:limit]):
            scale = max(1, min(3, 64 // max(1, max(sprite.size))))
            sim = sprite.resize((sprite.width * scale, sprite.height * scale), Image.Resampling.NEAREST)
            cell = Image.new("RGBA", (max(96, sim.width), sim.height + 15), (255, 255, 255, 255))
            ImageDraw.Draw(cell).text((1, 1), f"{label_prefix}:{i}", fill=(0, 0, 0, 255))
            cell.alpha_composite(sim, (0, 15))
            thumbs.append(cell.convert("RGB"))
        cols = 5
        cw = max(t.width for t in thumbs) + 8
        ch = max(t.height for t in thumbs) + 8
        sheet = Image.new("RGB", (cols * cw, ((len(thumbs) + cols - 1) // cols) * ch), "white")
        for n, thumb in enumerate(thumbs):
            sheet.paste(thumb, ((n % cols) * cw + 4, (n // cols) * ch + 4))
        return sheet
