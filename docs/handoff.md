# Handoff notes for the next developer

## Current mental model

The project can now reliably get from game files to a recognizable room preview:

```text
DAT archive -> decompressed resource -> level resource -> room tile bytes -> VGA sprite bank -> rendered terrain preview
```

The important distinction is that this is **not yet a complete game renderer**. It is a clean research harness for continuing the reverse engineering.

## Files to start with

- `ae_editor/compression.py` — known-good DAT decompression pipeline.
- `ae_editor/palette.py` — VGA palette extraction from `AEPROG.EXE`.
- `ae_editor/type47.py` — type 0x47 bitmap decoding.
- `ae_editor/level_format.py` — current level/room parser.
- `ae_editor/renderer.py` — current render hypothesis.
- `ae_editor/constants.py` — all magic numbers and the incomplete tile mapping.
- `docs/reverse_engineering_notes.md` — what is known, uncertain and deprecated.

## How to validate changes

Use real screenshots as ground truth. The most useful known references are:

- `level_01_room_00`: blue block border, brown cracked wall background, player near left, worm near bottom.
- `level_05_room_00`: green stone wall background, orange border blocks, large decorative/actor sprites.

When you change parser/rendering logic, export previews:

```bash
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT --export-previews previews
```

Then compare `previews/level_01_room_00.png` and `previews/level_05_room_00.png` against screenshots.

## Known traps

- Do not go back to the `136×64×3` map interpretation. It produced visually random output.
- Do not assume `low nibble = terrain` and `high nibble = object`; that was tried and made room 0 worse.
- Do not treat actor/object parsing as solved. The v12/v13 object-slot ideas were exploratory and are intentionally removed from canonical parsing.
- Do not use standard VGA palette; the game uses a custom palette embedded in `AEPROG.EXE`.
- Do not render type47 sprites as opaque; logical colour `0` should be transparent for sprites.

## Good next tasks

### Task 1: identify full terrain lookup

Search the EXE for tables or routines that map tile codes to indices in resources `21..24`.

Hints:

- room tile bytes visibly include small values like `0x02..0x06`,
- resources `21..24` look like the terrain banks for four themes,
- the current mapping is only a small subset.

### Task 2: identify object/chamber metadata

The level header and footer are preserved raw. They likely contain or point to room-specific state, actor placement, artifacts, triggers, and transitions.

The object system may be separated into categories:

- static background/decor,
- foreground decor,
- interactive world objects,
- actors/items,
- trigger/control relationships.

### Task 3: write tests around fixed binary expectations

Add tests that assert:

- `AE001.DAT` has the expected resource count,
- resources `0..19` parse as levels,
- each parsed level has 38 rooms,
- each room has 684 tile bytes,
- VGA palette extraction succeeds,
- terrain banks `21..24` contain images.

The project is currently small enough that tests would make future experimentation much safer.
