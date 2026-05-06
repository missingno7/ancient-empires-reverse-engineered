# Handoff Notes

## Current State

The project is now a focused research editor rather than a pile of rendering
experiments. It can load the game files, decode graphics banks, parse the 20
level resources, render recognizable static rooms, and show native overlay
labels for the currently understood gameplay objects.

The editor is not yet a safe full level writer. Treat rendering and overlays as
the canonical read path, and add write-back only after the corresponding parser
data is proven.

## Start Here

- `ae_editor/level_format.py` parses levels, difficulty parts and room records.
- `ae_editor/room_payload.py` parses platform triplets, controls, compact3
  tables, actor records, room links, header pickups and player start data.
- `ae_editor/renderer.py` is the static room renderer.
- `ae_editor/overlay.py` builds editor overlay geometry and relationship lines.
- `ae_editor/gui.py` wires the Tk UI, tabs, object atlas and overlay presets.
- `docs/level_format.md` is the canonical current format note.

## Validation Loop

Compile all Python modules:

```bash
python -m compileall ae_editor tools run_editor.py
```

Export previews after parser or renderer changes:

```bash
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT --export-previews previews
```

Useful smoke rooms:

- Level 1, Explorer, room 0: border blocks, player start and early actors.
- Level 2, Explorer, room 0: laser trigger/crystal cases.
- Level 9, Expert, room 0: puzzle markers and progress panel.
- Level 20, both difficulties, room 0: platform and layout divergence.

## Rules Of Thumb

- Keep uncertain bytes visible as debug data instead of guessing sprite meaning.
- Real actors come from the part actor table at `0x2754`, not command-2 control
  records.
- Buttons and floor switches come from length-prefixed control commands.
- Conveyors are terrain special tiles `0x0F` and `0x1F`.
- Tile code `0x07` is invisible support/collision, not visible platform art.
- The two level parts are Explorer and Expert difficulties.
- Use the custom palette from `AEPROG.EXE`; standard VGA palettes do not match.
- Type47 logical colour `0` is transparent for sprites.

## Good Next Tasks

- Add binary fixture tests around parser invariants.
- Recover the full terrain/object lookup tables from `AEPROG.EXE`.
- Convert the current room model into an explicit editable data model.
- Add guarded write-back for terrain-only edits before broader payload editing.
- Decode more actor script opcodes and connect movement/path overlays to them.
