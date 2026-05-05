# Super Solvers: Challenge of the Ancient Empires — research level editor

Research viewer/editor for the DOS game *Super Solvers: Challenge of the Ancient Empires*.

This repository does **not** contain original game assets or binaries. Users must provide their own `AEPROG.EXE`, `AE000.DAT` and `AE001.DAT`.

## Quick start

```bash
pip install -r requirements.txt
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT
```

Export all currently parsed room previews:

```bash
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT --export-previews previews
```

Export decoded graphics-bank contact sheets:

```bash
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT --export-bank-sheets sheets
```

Export a CSV probe of non-zero tile values and room metadata:

```bash
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT --export-csv ae_level_probe.csv
```

## Current status

The project can now correctly parse the terrain rooms much better than the older 38-room builds.

The important v16 correction is:

```text
AE001 level resource, decoded size 0x6618 / 26136 bytes

  2 equal parts, each 0x330c bytes:

    0x40 part header
    13 room records × 1000 bytes
      +0x000..0x001  unknown room preamble
      +0x002..0x2ad  terrain: 38×18 bytes, row-major
      +0x2ae..0x3e7  unknown room payload, probably actors/triggers/decor
    0x04 footer, usually zero
```

Older builds treated this as `0x40 + 38 × (38×18) + footer`. That was wrong: room 0 looked plausible by accident, but room 1+ were shifted. The correct room terrain start for page A room 1 in level 1 is `0x042a`, not the old `0x02ec`.

## Current features

- Reads `AE000.DAT` / `AE001.DAT` archives.
- Decompresses resources using the LZW-like + RLE pipeline used by the game.
- Extracts the custom VGA palette from `AEPROG.EXE`.
- Decodes type `0x47` VGA images with transparency.
- Loads the first 20 `AE001.DAT` resources as level candidates.
- Parses each level as two pages, each with 13 fixed room records.
- Renders the 38×18 terrain grid at 8-pixel cell spacing.
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
  level_format.py    level/part/room parser
  graphics.py        type47 image-bank loader and bank-sheet generator
  renderer.py        room rendering pipeline
  gui.py             Tkinter UI
  exporters.py       PNG/CSV export helpers
  constants.py       format constants and current tile mapping

docs/
  reverse_engineering_notes.md
  handoff.md
  file_format_summary.md
```

## Unsolved parts

The remaining big unknown is the 314-byte payload after each terrain grid. It likely contains gameplay and front/decor data: player spawn, enemies, diamonds, apples, buttons, moving platforms, doors and trigger links.

The `tile_code -> sprite` mapping is still partly empirical. The terrain renderer now maps the common low tile codes plus `0x80/0x90/0xA0/0xB0/0xC0` to the large terrain pieces because this matches screenshots better, but the exact EXE lookup tables still need to be fully identified.
