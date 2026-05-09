from __future__ import annotations

import shutil
from pathlib import Path

from .game_data.dat_archive import DatArchive
from .game_data.graphics import GraphicsSet
from .game_data.level_format import Level, load_levels
from .rendering.room_renderer import RoomRenderer


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
        self.graphics = GraphicsSet(self.ae001, self.exe, self.ae000)
        self.renderer = RoomRenderer(self.graphics)
        self.dirty_level_indices: set[int] = set()

    @property
    def dirty(self) -> bool:
        return bool(self.dirty_level_indices)

    def mark_level_dirty(self, level_index: int) -> None:
        self.dirty_level_indices.add(level_index)

    def save_ae001(self, path: Path | str | None = None, *, backup: bool = True) -> Path:
        """Write changed level resources to AE001.DAT.

        MVP1 editing stores modified level resources as plain uncompressed DAT
        resources and preserves untouched resources exactly.
        """
        target = Path(path) if path is not None else self.ae001.path
        replacements = {
            level.index: level.to_bytes()
            for level in self.levels
            if level.index in self.dirty_level_indices
        }
        if backup and target.exists():
            backup_path = target.with_suffix(target.suffix + ".bak")
            if not backup_path.exists():
                shutil.copy2(target, backup_path)
        target.write_bytes(self.ae001.build_blob_with_decoded_replacements(replacements))

        self.ae001 = DatArchive(target)
        self.archives["AE001.DAT"] = self.ae001
        self.levels = load_levels(self.ae001)
        self.dirty_level_indices.clear()
        return target
