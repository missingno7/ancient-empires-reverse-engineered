# Super Solvers: Challenge of the Ancient Empires research editor

Research viewer/editor for the DOS game *Super Solvers: Challenge of the
Ancient Empires*.

This repository does not ship original game assets. To run the editor, provide
your own copies of:

- `AEPROG.EXE`
- `AE000.DAT`
- `AE001.DAT`

## Quick Start

```bash
python -m pip install -r requirements.txt
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT
```

Use the same Python executable for installation and for `run_editor.py`. If you
see `ModuleNotFoundError: No module named 'PIL'`, Pillow was installed into a
different Python environment.

The package entry point is also available after installation:

```bash
ae-level-editor --exe AEPROG.EXE AE000.DAT AE001.DAT
```

## Useful Commands

Export all room previews:

```bash
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT --export-previews previews
```

Export decoded graphics-bank contact sheets:

```bash
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT --export-bank-sheets sheets
```

Export room/tile/payload probe data:

```bash
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT --export-csv ae_room_probe.csv
```

Dump one room payload:

```bash
python tools/probe_exe_payload.py --exe AEPROG.EXE --level 6 --difficulty Explorer --room 5 AE000.DAT AE001.DAT
```

## Current Model

`AE000.DAT` and `AE001.DAT` are resource archives with a 32-bit little-endian
offset table. `AE000.DAT` contains global gameplay/UI graphics, actors, pickups,
switches, projectiles, ropes and moving-platform sprites. `AE001.DAT` contains
the 20 level resources plus terrain and theme-decoration banks.

`AE001.DAT` resources `0..19` are levels. Each level resource contains two
difficulty parts:

```text
part 0 = Explorer
part 1 = Expert
```

Each difficulty part currently parses as:

```text
0x40-byte part header
13 room records * 1000 bytes
  +0x000..0x001  room preamble / metadata
  +0x002..0x2AD  terrain: 38 * 18 bytes, row-major
  +0x2AE..0x3E7  room payload: platforms, controls, compact3 sections
0x04 footer
```

Some caverns use fewer than all 13 fixed room slots. The editor still exposes
all slots and labels them as `room`, `empty`, or `data?` so research data is not
hidden.

See [docs/level_format.md](docs/level_format.md) for the current canonical
format notes.

## Editor Features

- Explorer/Expert difficulty browsing.
- Pixel-art room preview at 1x through 4x zoom.
- Terrain, background, ropes, conveyors, moving platforms, controls, puzzle
  markers, crystals, pickups, actors, player start and room exits.
- Native Tk overlay labels and relationship lines, separate from the scaled
  room bitmap.
- Overlay presets for minimal, logic and debug views.
- Object atlas for recognized actors, pickups, controls, puzzle objects and
  movement objects.
- Graphics-bank viewer and sheet exporter.
- CSV and PNG export helpers for regression checks.

## Project Layout

```text
ae_editor/
  cli.py             command-line entry point
  compression.py     DAT decompression
  dat_archive.py     DAT archive reader
  palette.py         AEPROG.EXE VGA palette extraction
  type47.py          type 0x47 image decoder
  level_format.py    level / difficulty / room parser
  room_payload.py    room payload and actor-table parser
  tile_mapping.py    current terrain code mapping
  coordinates.py     coordinate transforms
  object_mapping.py  compact3 visual code mapping
  renderer.py        static room renderer
  overlay.py         editor overlay model
  gui.py             Tkinter editor UI
  exporters.py       PNG/CSV export helpers

docs/
  level_format.md
  file_format_summary.md
  reverse_engineering_notes.md
  handoff.md
```

## Still Unsolved

- exact EXE lookup table for all terrain and visual object codes;
- full write-back model for editing rooms safely;
- exact gameplay semantics for every trigger/control byte;
- complete actor/enemy behavior scripts;
- collectible schemas beyond confirmed rendered cases.

The renderer is conservative by design: confirmed structures are drawn normally,
while uncertain data stays visible through overlay/debug tooling instead of
being promoted to guessed gameplay objects.
