from __future__ import annotations

import argparse
from pathlib import Path

from .exporters import export_bank_sheets, export_probe_csv, export_room_previews
from .gui import LevelEditorApp
from .project import AncientEmpiresProject


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ancient Empires research level editor")
    parser.add_argument("dat", nargs="+", help="DAT files, usually AE000.DAT and AE001.DAT")
    parser.add_argument("--exe", default="AEPROG.EXE", help="Path to AEPROG.EXE")
    parser.add_argument("--export-previews", help="Export rendered room previews and exit")
    parser.add_argument("--export-bank-sheets", help="Export decoded graphics bank sheets and exit")
    parser.add_argument("--export-csv", help="Export room/tile/payload CSV and exit")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    project = AncientEmpiresProject(Path(args.exe), [Path(x) for x in args.dat])

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
