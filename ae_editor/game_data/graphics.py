from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from .palette import build_game_ega_palette, dac6_to_pillow_palette, find_vga_palette_dac6
from .game_graphics_records import decode_game_graphics_record, iter_game_graphics_records
from ..constants import (
    TERRAIN_BANK_COUNT,
    TERRAIN_BANK_RESOURCE_START,
)
from .dat_archive import DatArchive

GRAPHICS_DISPLAY_MODES = ("vga", "ega", "cga")


@dataclass
class SpriteRef:
    archive_name: str
    resource_id: int
    subname: str
    image: Image.Image


class GraphicsSet:
    """Decoded graphics banks used by the editor.

    The game uses type 0x47 images.  Each bitmap has one packed 4-bit pixel
    stream and per-sprite colour lookup tables.  VGA uses the second 16-byte
    table with the custom 256-colour DAC palette embedded in AEPROG.EXE.  EGA
    uses the first 16-byte table.  No separate CGA bitmap bank has been found in
    AE000/AE001, so the CGA view is decoded from the same pixels and reduced
    from the EGA colour table to a four-colour CGA palette.

    Graphics are loaded from both AE001.DAT and AE000.DAT. Terrain/decor banks
    live in AE001, while many actor, UI and gameplay sprites live in AE000. The
    bank browser therefore uses source-qualified ids such as "AE000:020".
    """

    def __init__(self, ae001: DatArchive, exe_path: Path | str, ae000: DatArchive | None = None):
        exe_path = Path(exe_path)
        _, dac = find_vga_palette_dac6(exe_path)
        self.vga_palette = dac6_to_pillow_palette(dac)
        self.ega_palette = build_game_ega_palette(exe_path)
        self.display_mode = "vga"
        self.banks_by_mode: dict[str, dict[str, list[Image.Image]]] = {mode: {} for mode in GRAPHICS_DISPLAY_MODES}
        self.refs_by_mode: dict[str, dict[str, list[SpriteRef]]] = {mode: {} for mode in GRAPHICS_DISPLAY_MODES}
        self.ae001_banks_by_mode: dict[str, dict[int, list[Image.Image]]] = {mode: {} for mode in GRAPHICS_DISPLAY_MODES}
        self.ae000_banks_by_mode: dict[str, dict[int, list[Image.Image]]] = {mode: {} for mode in GRAPHICS_DISPLAY_MODES}
        self.terrain_banks_by_mode: dict[str, list[list[Image.Image]]] = {mode: [] for mode in GRAPHICS_DISPLAY_MODES}

        self._load_archive_banks("AE001", ae001)
        if ae000 is not None:
            self._load_archive_banks("AE000", ae000)

        for mode in GRAPHICS_DISPLAY_MODES:
            for theme in range(TERRAIN_BANK_COUNT):
                rid = TERRAIN_BANK_RESOURCE_START + theme
                self.terrain_banks_by_mode[mode].append(self.ae001_banks_by_mode[mode].get(rid, []))

        # Backward-compatible attributes used by the bank browser and older code.
        self._refresh_mode_aliases()

    def set_display_mode(self, mode: str) -> None:
        mode = mode.lower()
        if mode not in GRAPHICS_DISPLAY_MODES:
            raise ValueError(f"unknown graphics display mode: {mode}")
        if self.display_mode != mode:
            self.display_mode = mode
            self._refresh_mode_aliases()

    def _refresh_mode_aliases(self) -> None:
        self.banks = self.banks_by_mode[self.display_mode]
        self.refs = self.refs_by_mode[self.display_mode]
        self.ae001_banks = self.ae001_banks_by_mode[self.display_mode]
        self.ae000_banks = self.ae000_banks_by_mode[self.display_mode]
        self.terrain_banks = self.terrain_banks_by_mode[self.display_mode]

    def _load_archive_banks(self, archive_name: str, dat: DatArchive) -> None:
        # Scan the full DAT.  This is cheap for these small archives and avoids
        # hiding useful actor banks below resource 21.
        for rid in range(0, len(dat)):
            by_mode = self._load_bank(dat, archive_name, rid)
            for mode, (bank, refs) in by_mode.items():
                if bank:
                    key = f"{archive_name}:{rid:03d}"
                    self.banks_by_mode[mode][key] = bank
                    self.refs_by_mode[mode][key] = refs
                    if archive_name == "AE001":
                        self.ae001_banks_by_mode[mode][rid] = bank
                    elif archive_name == "AE000":
                        self.ae000_banks_by_mode[mode][rid] = bank

    def _load_bank(self, dat: DatArchive, archive_name: str, resource_id: int) -> dict[str, tuple[list[Image.Image], list[SpriteRef]]]:
        res = dat[resource_id]
        out: dict[str, tuple[list[Image.Image], list[SpriteRef]]] = {
            mode: ([], []) for mode in GRAPHICS_DISPLAY_MODES
        }
        if not res.ok:
            return out
        for bitmap in iter_game_graphics_records(res.decoded, res.rtype):
            for mode in GRAPHICS_DISPLAY_MODES:
                images, refs = out[mode]
                try:
                    decoded = decode_game_graphics_record(bitmap.payload, mode, self.vga_palette, transparent=True, ega_palette=self.ega_palette)
                except ValueError:
                    continue
                rgba = decoded.image.convert("RGBA")
                images.append(rgba)
                refs.append(SpriteRef(archive_name, resource_id, bitmap.subname, rgba))
        return out

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
