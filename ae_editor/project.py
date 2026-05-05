from __future__ import annotations

from pathlib import Path

from .dat_archive import DatArchive
from .graphics import GraphicsSet
from .level_format import Level, load_levels
from .renderer import RoomRenderer


class AncientEmpiresProject:
    """Loaded game data bundle used by GUI and CLI."""

    def __init__(self, exe: Path | str, dat_paths: list[Path | str]):
        self.exe = Path(exe)
        self.archives = {Path(p).name.upper(): DatArchive(Path(p)) for p in dat_paths}
        if "AE001.DAT" not in self.archives:
            raise ValueError("AE001.DAT is required")
        self.ae001 = self.archives["AE001.DAT"]
        self.ae000 = self.archives.get("AE000.DAT")
        self.levels: list[Level] = load_levels(self.ae001)
        self.graphics = GraphicsSet(self.ae001, self.exe)
        self.renderer = RoomRenderer(self.graphics)
