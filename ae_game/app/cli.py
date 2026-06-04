from __future__ import annotations

import argparse
from pathlib import Path
import sys

from ancient_empires.project import AncientEmpiresProject
from .main_window import GameWindow


_DAT_NAMES = ("AE000.DAT", "AE001.DAT")
_EXE_NAME = "AEPROG.EXE"


def default_game_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "game_data"
    return Path("game_data")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ancient Empires reverse-engineered source port",
        epilog="Without arguments the game looks for original assets in ./game_data/.",
    )
    parser.add_argument(
        "folder",
        nargs="?",
        default=str(default_game_data_dir()),
        help="Folder containing AEPROG.EXE and AE00x.DAT (default: game_data)",
    )
    parser.add_argument("--exe", default=None, help="Path to AEPROG.EXE (overrides folder lookup)")
    parser.add_argument("--scale", type=int, default=3, help="Integer display scale (default: 3)")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    folder = Path(args.folder)
    dat_paths = [folder / name for name in _DAT_NAMES if (folder / name).exists()]
    if not dat_paths:
        raise SystemExit(f"No DAT files found in {folder.resolve()}")
    exe_path = Path(args.exe) if args.exe else folder / _EXE_NAME
    project = AncientEmpiresProject(exe_path, dat_paths)
    GameWindow(project, scale=args.scale).run()
