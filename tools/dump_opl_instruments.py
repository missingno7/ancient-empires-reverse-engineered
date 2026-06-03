from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ae_editor.audio import load_opl_instrument_table, describe_opl_patch


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump Ancient Empires AdLib/OPL instrument table from AEPROG.EXE")
    parser.add_argument("exe", nargs="?", default=str(ROOT / "AEPROG.EXE"))
    parser.add_argument("--count", type=int, default=64)
    args = parser.parse_args()

    table = load_opl_instrument_table(args.exe, count=args.count)
    for index, patch in sorted(table.items()):
        print(describe_opl_patch(patch))


if __name__ == "__main__":
    main()
