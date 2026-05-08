# AI Maintainer Context

This file is a compact orientation note for future AI agents and maintainers.
Use it as the first technical map, then follow the deeper documents linked
below.

## What This Project Is

This is a Python/Tk research editor for *Super Solvers: Challenge of the Ancient
Empires*. It loads user-supplied game files, decodes resources, renders rooms,
edits understood structures and simulates selected runtime behavior. It is not a
complete game engine or a fully proven level writer.

## Highest Value Files

- `ae_editor/project.py`: project loader joining EXE palette data, DAT archives,
  graphics banks, levels and renderer.
- `ae_editor/level_format.py`: level, difficulty part and room parsing.
- `ae_editor/room_payload.py`: room payload tables, controls, actors, compact
  sections and write helpers.
- `ae_editor/renderer.py`: conservative static room renderer.
- `ae_editor/simulation.py`: room-local actor/control/green-block runtime model.
- `ae_editor/gui.py`: Tk tabs, editing surfaces, simulation canvas and property
  panels.
- `ae_editor/actor_dsl.py` and `ae_editor/actor_scripts.py`: actor bytecode
  decoding and editable DSL/instruction views.

## Behavioral Invariants To Preserve

- Level resources contain two parts: `0 = Explorer`, `1 = Expert`.
- Each part exposes ten real rooms; the following 3000-byte block is actor data,
  not rooms 10..12.
- Moving platforms use ten leading room triplets and shared
  `platform_motion_delta()` semantics.
- Tile `0x07` is invisible support/collision. Simulation moves runtime `0x07`
  footprints for platforms and green blocks.
- Control targets are typed as `P`, `CV` and `R`; multiple active controls
  targeting the same object combine by XOR/parity.
- Wall symbols are user-facing `S1..S7`; actor VM `emit_symbol` raw id `0`
  emits `S1`.
- Green blocks consume the next expected symbol, reset on wrong symbols, and
  toggle between their two positions after the full sequence is entered.
- Unknown payload bytes should remain inspectable. Do not promote guessed bytes
  into editable objects without evidence.

## Validation Loop

Compile after code changes:

```bash
python -m compileall ae_editor tools run_editor.py
```

Export room previews after parser or renderer changes:

```bash
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT --export-previews previews
```

Regenerate public docs screenshots after visual UI changes:

```bash
python tools/capture_docs_screenshots.py --exe AEPROG.EXE --dat AE000.DAT AE001.DAT
```

## Deeper Docs

- `docs/quick_start.md`: human launch and first-use guide.
- `docs/screenshots.md`: public screenshot tour.
- `docs/level_format.md`: canonical current file-format model.
- `docs/simulation_mode.md`: runtime simulation behavior and known gaps.
- `docs/actor_script_space.md`: actor script-space model and safe edit rules.
- `docs/actor_dsl.md`: actor DSL syntax.
- `docs/handoff.md`: current state, validation rooms and good next tasks.
