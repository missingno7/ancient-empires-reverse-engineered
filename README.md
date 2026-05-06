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


## v33 notes

- `Page A/B` is now treated as `Explorer/Expert`.
- Visual compact3 payloads are drawn in EXE order: high-bit entries before terrain, low-bit entries after terrain.
- Platform triplets with `0x80/0xA0` are rendered as vertical platforms; `0x40/0x60` as horizontal.
- Platform triplets use the same anchor correction as other screen-space objects (`x*2-12, y-12`), replacing the old `x*2-4, y` preview bias.
- Puzzle buttons use `AE000:009` plus symbols from `AE000:010..016`; the progress block uses `AE000:017`.
- Old alignment/crop experiments have been removed; terrain anchor `(-4,-4)` is part of the renderer.


## v33 note

Control records are now parsed as length-prefixed records; the old renderer accidentally treated the length byte as the command id.  This version also adds first-pass conveyor belt rendering from AE000:038.


## v33 notes

This build restores the v31 background decoration behavior and adds a dedicated conveyor renderer for `AE000:038`. Conveyors are now composed from left/middle/right strip sprites instead of treating payload bytes as direct sprite indexes. See `docs/level_format_v33.md`.


## v33 note

Conveyor belts are now rendered from terrain tile codes `0x0F` and `0x1F`, not from control records. This matches the observed behaviour where belts show up in `codes_hex` like ropes and have distinct grey/teal tile codes. Control records with conveyor-like arguments are kept as metadata/debug only until the trigger system is fully understood.

## v36 notes

v36 keeps the v33 discovery that conveyors are terrain special tiles, but fixes
the strip length by adding the right-cap cell. It also adds horizontal flip
support for theme visual entries: bit `0x40` in the compact3 visual code mirrors
the selected `AE001:(25+theme):(code&0x3f)` sprite. The old global mapping of
compact3 code `0x02` to an enemy sprite was removed because it broke ordinary
background decorations in some rooms.


## v36 note

This build fixes the legacy mistake where visual compact3 code `0x0E` was drawn as a button. Buttons are control records; `0x0E` in the visual table is normally theme decoration. Payload debug now also shows EXE-derived probes for still-unsolved actor/item storage.


## v36 button/control cleanup

This build keeps the v31/v34 visual layer model, but fixes a control-command mistake: command `0x00` records are trigger/button records even when their link id (`arg_b` or extra byte) is `0x00`, `0x01`, `0x10`, or `0x11`. Previous builds skipped some of those values as conveyor metadata, which is why rooms such as Level 1 Expert room 3 only showed one of three floor buttons. Conveyors remain terrain special tiles (`0x0F`/`0x1F`), so command records are no longer used to draw conveyor belts.

## v38 note

The v38 build fixes the v36 button regression: command records now distinguish
ceiling buttons, floor switches, and link metadata without using the old
`y >= threshold` heuristic.  See `docs/level_format_v38.md`.


## v38 note

Switch rendering was cleaned up: command `0` records are ceiling buttons, command `1` records are floor switches. The remaining command bytes are kept as trigger/link metadata rather than sprite IDs.


## v39 notes

- Switches are now decoded by command byte, with `arg_b & 0x40` treated as initial pressed state.
- Command 2 is isolated as an actor/control family. Confirmed preview mappings include spider (`AE000:022:12`), snake/crawler (`AE000:022:20`), and ant/crawler (`AE000:020:0`).
- Unknown command-2 subtypes are not drawn as decorations; use `payload_debug` to inspect them.
- See `docs/level_format_v39.md`.

## v40 notes

- Command 2 is now rendered as the visible laser-trigger/jello family (`AE000:041`); enemies are no longer inferred from these room payload records.
- Visual compact3 code `0x80` is no longer special-cased as laser jello; in Level 2 room 0 that was a false second trigger.
- The six header slots at `0x08/0x0e/0x14` are rendered as room-gated diamonds/artifacts (`AE000:044`).
- Runtime actor records are parsed from the part actor table at `0x2754`, with normal room enemies mapped through the gameplay frame runs `AE000:020..022`.
- Room exit links are decoded from the four 10-byte transition arrays; self-links explain rooms that wrap back into themselves.
- Static room renders use the visible 38x18 tile viewport again; actor/header object coordinates are converted through their sprite-anchor transform and clipped at the room edge.
- Actor record byte `0x08` is treated as hidden/start-state: normal game previews skip hidden actors, while `payload_debug` still shows them faintly.
- Confirmed enemy labels are now tied to actor frame ranges: ant, bat, green spitter, ladybug, scorpion shooter, spider, and snake.

## v41 notes

- The editor now defaults to 3x zoom for the DOS pixel-art viewport.
- Debug labels and relationship hints are drawn as native Tk canvas overlay items, not baked into the scaled pixel bitmap.
- Overlay layers show platform ids, trigger/control ids, raw trigger-to-platform links, actor start boxes, actor script offsets/byte previews, pickups, laser crystals, and room exit links.
- Pixel-renderer labels were removed. `codes_hex` and `trailing_hex` render coloured debug grids in the bitmap and draw readable hex values as native canvas text.
