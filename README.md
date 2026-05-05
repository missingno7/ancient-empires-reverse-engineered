# Super Solvers: Challenge of the Ancient Empires — research level editor

Research viewer/editor for the DOS game *Super Solvers: Challenge of the Ancient Empires*.

This repository does **not** contain original game assets or binaries. Users must provide their own `AEPROG.EXE`, `AE000.DAT` and `AE001.DAT`.

## Quick start

```bash
pip install -r requirements.txt
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT
```

Export all rendered room previews:

```bash
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT --export-previews previews
```

Export decoded graphics-bank contact sheets:

```bash
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT --export-bank-sheets sheets
```

Dump one room payload:

```bash
PYTHONPATH=. python tools/probe_exe_payload.py --exe AEPROG.EXE --level 6 --page Explorer --room 5 AE000.DAT AE001.DAT
```

## Current known format

### DAT archives

`AE000.DAT` and `AE001.DAT` are resource archives with a 32-bit little-endian offset table. AEPROG addresses resources as packed ids:

```text
dat_index = resource_id >> 12
entry_id  = resource_id & 0x0fff
```

`AE000.DAT` mostly contains global gameplay/UI graphics: player frames, ropes, enemies, switches, diamonds, moving platforms, etc. `AE001.DAT` contains the first 20 level resources plus theme terrain/decor banks.

### Level resources

`AE001` resources `0..19` are the 20 caverns/levels. Each decoded level resource is split into two parts:

```text
part 0 = Explorer difficulty
part 1 = Expert difficulty
```

Each part is currently parsed as:

```text
0x40 part header
13 room records × 1000 bytes
  +0x000..0x001  room preamble / metadata
  +0x002..0x2AD  terrain: 38×18 bytes, row-major
  +0x2AE..0x3E7  room payload: platforms, controls, compact3 sections
0x04 footer
```

Some levels use fewer than all 13 room slots. For example, level 1 appears to use rooms `0..6`; later room slots can be blank placeholders or non-room/control data. The editor still exposes all 13 slots so contributors can inspect them.

### Rendering model

The cleaned-up renderer uses these layers:

1. theme background fill,
2. terrain cells from `AE001:021..024`, using an `(-4,-4)` sprite anchor,
3. rope special terrain codes via `AE000:005..008`,
4. moving platforms from the first ten payload triplets,
5. length-prefixed control records where confirmed,
6. laser crystal compact3 section,
7. main visual compact3 table.

Important caveats:

- terrain code `0x07` is treated as invisible solid/support, not visible platform art;
- `Page A/B` in old builds is now labelled `Explorer/Expert`;
- old experimental controls such as “crop left 2”, “test +4,+4 align” and runtime tile-anchor toggles were removed;
- object coordinates and the full `code -> sprite` lookup are still incomplete.

## Project layout

```text
ae_editor/
  cli.py             command-line entry point
  compression.py     DAT offset table + LZW-like/RLE decompression
  palette.py         MZ EXE parsing + custom VGA palette extraction
  type47.py          type 0x47 VGA/EGA image decoder with transparency
  dat_archive.py     DAT archive reader and resource wrapper
  level_format.py    level/part/room parser
  room_payload.py    EXE-style room payload parser
  object_mapping.py  confirmed compact3 code -> sprite overrides
  coordinates.py     terrain/platform/object coordinate transforms
  graphics.py        type47 image-bank loader and bank-sheet generator
  renderer.py        clean room rendering pipeline
  gui.py             Tkinter UI
  exporters.py       PNG/CSV export helpers

docs/
  level_format_v28.md
  handoff.md
  file_format_summary.md
  reverse_engineering_notes.md
```

## What is still unsolved

- exact EXE lookup table for visual/gameplay object codes;
- precise actor/enemy coordinate model;
- player spawn storage;
- trigger graph: buttons, moving platforms, doors/passages, laser reflectors;
- which room slots are active for each cavern and difficulty.

The current code is deliberately conservative: when the format is not known, it shows debug information instead of drawing guessed objects.


## v29 notes

This version keeps the v28 cleanup structure but adds another small payload pass:

- `Page A/B` is now consistently treated as `Explorer/Expert`.
- Rooms are labelled as `room`, `empty`, or `data?` in the selector; not every one of the 13 fixed records is necessarily a playable room.
- Theme decorations are globally shifted slightly up-left because v27/v28 were a bit right/down compared with screenshots.
- Rope x placement was adjusted slightly right.
- Payload `section_a` is now rendered separately; this makes Level 9 / Expert / Room 0 show the three round hanging markers that were missing before.

See `docs/level_format_v29.md` for the current handoff notes.
