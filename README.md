# Super Solvers: Challenge of the Ancient Empires — research level editor

Research viewer/editor for the DOS game *Super Solvers: Challenge of the Ancient Empires*.

This repository does **not** contain original game assets or binaries. Users must provide their own `AEPROG.EXE`, `AE000.DAT` and `AE001.DAT`.

## v23 notes

This build fixes the normal terrain tile lookup: `dec 2` now maps to sprite index `6` in the active AE001 terrain bank instead of duplicating sprite `5`. The mapping is centralized in `ae_editor/tile_mapping.py` so future corrections are not hidden as renderer hacks. `0x07` remains invisible collision/support; visible platforms come from room payload records.


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

## v17 research update

The project now loads VGA sprite banks from both `AE000.DAT` and `AE001.DAT`.  Bank ids in the UI are source-qualified, for example `AE000:020` or `AE001:025`.  This is important because gameplay sprites are not limited to `AE001:021..028`.

New room payload modes:

- `terrain_payload` overlays suspected payload positions on top of terrain.
- `payload_probe` shows only payload candidate markers and ranked candidate tables.

A helper is available:

```bash
PYTHONPATH=. python tools/probe_room_payload.py --exe AEPROG.EXE --level 1 --page A --room 1 AE000.DAT AE001.DAT
```

See `docs/level_format_v17.md` for the current handoff notes.


## v18 update

This build promotes several gameplay graphics from the raw bank browser into the room renderer:

- AE000:005..008 are used for rope segments. Level tile codes `0x90`, `0xA0`, `0x80`, `0xB0`, `0xC0` are no longer treated as terrain-bank sprites. In level 1 room 1 this fixes the rope that previously looked like AE001:021 wall/door texture.
- AE000:047 and AE000:048 are used for moving platform graphics. Contiguous terrain code `0x07` runs are rendered as one horizontal or vertical platform sprite rather than repeated small terrain pieces.
- AE000:040/043 are drawn experimentally for typed6 payload entries with type `0x06`, which appear to be switch/control definitions. Exact anchors and trigger semantics are still research-grade.
- The default GUI mode is now `terrain_objects`; use `terrain` for terrain-only and `payload_probe` / `terrain_payload` for payload debugging.


## v20 research update

This build changes the interpretation of special terrain code `0x07`: it is treated as invisible solid/collision support, not as a visible moving platform. Moving platform sprites are now rendered from leading room-payload triplets where possible. This matches the observation that level 1 room 2 uses `0x07` as an invisible support under a statue, while actual platform graphics live in AE000 sprite banks.

See `docs/level_format_v20.md` for the current handoff notes.


## v21 status

Latest research build parses variable-length leading platform triplets, treats terrain code `0x07` as invisible collision/support, and renders several compact3 payload decorations/objects such as the vase (`AE001:025:26`) and laser trigger (`AE000:041:0`). See `docs/level_format_v21.md`.


## v22 research notes

This build adds EXE-derived parsing for the first ten platform/control triplets and count-prefixed compact3 visual object/decor tables. See `docs/level_format_v22.md`.


## v25 note: terrain sprite anchor

Normal terrain sprites from `AE001:021..024` are larger than the 8 px grid cells and overlap adjacent cells.  The current renderer blits them with a default `(-4,-4)` terrain anchor, exposed in the GUI as `tile anchor -4,-4`.  This fixes the long-standing half-tile-looking down/right shift of foreground blocks while leaving background and payload-object coordinates separate.  See `docs/level_format_v25.md`.
