# Handoff Notes

## Current State

The project is now a focused research editor rather than a pile of rendering
experiments. It can load the game files, decode graphics banks, parse the 20
level resources, render recognizable static rooms, show native overlay labels
for understood gameplay objects, and run a room-local Simulation tab for actor,
control and puzzle behavior.

The editor is not yet a safe full level writer. Treat rendering and overlays as
the canonical read path. The Editor tab now writes terrain, known header object
slots, room links, controls, symbol markers, green blocks, visual decor,
animated decor, reflectors, actors, moving-platform triplets and composite
conveyor belts where the parser has an explicit model. Changed level resources
are stored back into `AE001.DAT` as plain uncompressed resources.

## Start Here

- `ae_editor/level_format.py` parses levels, difficulty parts and room records.
- `ae_editor/room_payload.py` parses platform triplets, controls, compact3
  tables, actor records, room links, header pickups, exit door and player start
  data.
- `ae_editor/renderer.py` is the static room renderer.
- `ae_editor/simulation.py` is the in-memory simulation runtime for actor VM
  stepping, controls, green blocks and runtime collision.
- `ae_editor/overlay.py` builds editor overlay geometry and relationship lines.
- `ae_editor/gui.py` wires the Tk UI, tabs, object atlas and overlay presets.
  The `Editor` tab is the active editing surface; `Simulation` is the active
  runtime preview; the level viewer stays mostly read-only/diagnostic.
- `docs/level_format.md` is the canonical current format note.
- `docs/simulation_mode.md` describes the runtime preview model and known gaps.
- `docs/quick_start.md` and `docs/screenshots.md` are the human-facing entry
  docs linked from the README.
- `docs/ai_context.md` is the compact technical map for future AI/maintainer
  handoffs.

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
- Level 9, Explorer, room 0: green-block sequence and runtime footprint tests.
- Level 9, Explorer, room 6: actor `emit_symbol` behavior.
- Level 20, both difficulties, room 0: platform and layout divergence.

Regenerate public README/docs screenshots after visible UI changes:

```bash
python tools/capture_docs_screenshots.py --exe AEPROG.EXE --dat AE000.DAT AE001.DAT
```

## Rules Of Thumb

- Keep uncertain bytes visible as debug data instead of guessing sprite meaning.
- Real actors come from the part actor table at `0x2754`, not command-2 control
  records.
- Buttons and floor switches come from length-prefixed control commands.
- Conveyors are composite: terrain special tiles `0x0F`/`0x1F` provide physics/scrolling, while CV records in the payload directory provide the visible belt.
- Moving platforms are the ten leading 3-byte room trailing payload triplets.
  Travel preview currently uses the shared `platform_motion_delta()` constants:
  `0x40` right, `0x60` left, `0x80` down, `0xA0` up, all 48 px.
- Tile code `0x07` is invisible support/collision, not visible platform art.
  It is shown through optional canvas overlays in both the viewer and Editor
  tab rather than as a separate renderer mode. Simulation moves runtime `0x07`
  footprints for active platforms and green blocks.
- Control targets are typed as `P`, `CV` and `R`. Multiple active controls on
  the same target combine by parity/XOR in Simulation.
- Wall symbols are one-based `S1..S7`; actor VM `emit_symbol` stores zero-based
  raw ids, so raw `0` emits `S1`.
- The two level parts are Explorer and Expert difficulties.
- The conditional exit door is stored in header bytes `0x05..0x07` and rendered
  from the current theme terrain bank sprite 0.
- Use the custom palette from `AEPROG.EXE`; standard VGA palettes do not match.
- Type47 logical colour `0` is transparent for sprites.

## Good Next Tasks

- Add binary fixture tests around parser invariants.
- Add behavioral fixtures for Simulation: control XOR, platform `0x07`
  footprint movement, green-block sequence progress/reset/toggle, and
  zero-based actor `emit_symbol`.
- Recover the full terrain/object lookup tables from `AEPROG.EXE`.
- Recover EXE-derived sprite anchor/origin tables and replace remaining
  screenshot-tuned offsets.
- Convert the current room model into an explicit editable data model.
- Add guarded round-trip tests around the existing payload write paths.
- Improve actor/enemy path editing now that actor placement and script-space
  editing exist.
- Decode remaining VM event side effects and make Simulation closer to the EXE.
