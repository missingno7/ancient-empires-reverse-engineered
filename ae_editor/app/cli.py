from __future__ import annotations

import argparse
from pathlib import Path
import sys

from ancient_empires.exporters import export_bank_sheets, export_probe_csv, export_room_previews
from ancient_empires.project import AncientEmpiresProject
from .main_window import LevelEditorApp


_DAT_NAMES = ("AE000.DAT", "AE001.DAT")
_EXE_NAME = "AEPROG.EXE"


def default_game_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "game_data"
    return Path("game_data")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ancient Empires research level editor",
        epilog="Without arguments the editor looks for game files in ./game_data/.",
    )
    parser.add_argument(
        "folder",
        nargs="?",
        default=str(default_game_data_dir()),
        help="Folder containing AEPROG.EXE and AE00x.DAT (default: game_data)",
    )
    parser.add_argument("--exe", default=None, help="Path to AEPROG.EXE (overrides folder lookup)")
    parser.add_argument("--export-previews", help="Export rendered room previews and exit")
    parser.add_argument("--export-bank-sheets", help="Export decoded graphics bank sheets and exit")
    parser.add_argument("--export-csv", help="Export room/tile/payload CSV and exit")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    folder = Path(args.folder)
    dat_paths = [folder / name for name in _DAT_NAMES if (folder / name).exists()]
    if not dat_paths:
        raise SystemExit(f"No DAT files found in {folder.resolve()}")
    exe_path = Path(args.exe) if args.exe else folder / _EXE_NAME
    project = AncientEmpiresProject(exe_path, dat_paths)

    did_export = False
    if args.export_previews:
        export_room_previews(project, Path(args.export_previews))
        did_export = True
    if args.export_bank_sheets:
        export_bank_sheets(project, Path(args.export_bank_sheets))
        did_export = True
    if args.export_csv:
        export_probe_csv(project, Path(args.export_csv))
        did_export = True
    if did_export:
        return

    LevelEditorApp(project).mainloop()


if __name__ == "__main__":
    main()
