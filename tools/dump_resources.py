#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from ae_editor.game_data.dat_archive import DatArchive


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump decoded DAT resources")
    parser.add_argument("dat")
    parser.add_argument("outdir")
    args = parser.parse_args()

    archive = DatArchive(Path(args.dat))
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    for res in archive.resources:
        if res.ok:
            suffix = f"t{res.rtype:02X}_f{res.flags:02X}"
            (outdir / f"{archive.path.stem}_{res.index:03d}_{suffix}.bin").write_bytes(res.decoded)
        else:
            (outdir / f"{archive.path.stem}_{res.index:03d}_ERROR.txt").write_text(res.error, encoding="utf-8")


if __name__ == "__main__":
    main()
