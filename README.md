# Super Solvers: Challenge of the Ancient Empires — research level editor

This is a **research build** of a level viewer/editor for the DOS game *Super Solvers: Challenge of the Ancient Empires*.

It is not a finished editor yet. The current goal is to make the reverse-engineered data pipeline clean, testable and easy to continue from.

## Quick start

Put the original game files next to this project or pass explicit paths:

```bash
pip install -r requirements.txt
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT
```

Export all known room previews:

```bash
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT --export-previews previews
```

Export graphics-bank contact sheets:

```bash
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT --export-bank-sheets sheets
```

Export a CSV probe of non-zero tile values and raw level headers:

```bash
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT --export-csv ae_level_probe.csv
```

## Current features

- Reads `AE000.DAT` / `AE001.DAT` archives.
- Decompresses resources using the LZW-like + RLE pipeline used by the game.
- Extracts the custom VGA palette from `AEPROG.EXE`.
- Decodes type `0x47` VGA images with transparency.
- Loads the first 20 `AE001.DAT` resources as level candidates.
- Parses each level as 38 rooms of `38×18` tile bytes.
- Renders rooms using the currently known terrain tile mapping.
- Shows decoded sprite/tile banks in the side panel.
- Exports previews, bank sheets and CSV probes.

## Project layout

```text
ae_editor/
  cli.py             command-line entry point
  compression.py     DAT offset table + LZW-like/RLE resource decompression
  palette.py         MZ EXE parsing + custom VGA palette extraction
  type47.py          type 0x47 VGA/EGA bitmap decoder with transparency
  dat_archive.py     DAT archive reader and resource wrapper
  level_format.py    level and room parser
  graphics.py        type47 image-bank loader and bank-sheet generator
  renderer.py        room rendering pipeline
  gui.py             Tkinter UI
  exporters.py       PNG/CSV export helpers
  constants.py       format constants and current tile mapping

docs/
  reverse_engineering_notes.md
  handoff.md
  file_format_summary.md

tools/
  dump_resources.py
  export_previews.py
```

## Important status note

The VGA decoder logic is now absorbed into project modules instead of living as a copied script dependency. The terrain renderer is deliberately conservative. It uses the v11/v15 interpretation that best matched screenshots: each room cell is one full byte terrain code, placed on an 8px grid, and the terrain sprite itself may be larger than 8×8 and overlap neighbouring cells.

The following are **not solved yet**:

- exact `tile_code -> sprite` lookup for every theme and room,
- exact background/decor/front-layer split,
- actor/object records: player spawn, enemies, diamonds, apples, buttons, moving platforms and doors,
- write-back/recompression safe enough for editing the real game files.

Always test on copies of the game data.
