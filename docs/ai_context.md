# AI Maintainer Context

This file is a compact orientation note for future AI agents and maintainers.
Use it as the first technical map, then follow the deeper documents linked
below.

## What This Project Is

This repository contains a shared reverse-engineered implementation, a Python/Tk
research editor, and a player-facing source-port application for *Super Solvers:
Challenge of the Ancient Empires*. It is not yet a playable game or a fully
proven level writer.

## Highest Value Files

- `ancient_empires/project.py`: project loader joining EXE palette data, DAT archives,
  graphics banks, levels and renderer.
- `ancient_empires/game_data/level_format.py`: level, difficulty part and room parsing.
- `ancient_empires/game_data/room_payload.py`: room payload tables, controls, actors, compact
  sections and write helpers.
- `ancient_empires/rendering/room_renderer.py`: conservative static room renderer.
- `ancient_empires/engine/room_simulation.py`: room-local actor/control/green-block runtime model,
  including actor mode activation for sleeping projectile/secondary actors.
- `ae_editor/app/main_window.py` and `ae_editor/ui/`: Tk tabs, editing surfaces, simulation canvas and property
  panels.
- `ancient_empires/game_data/actor_dsl.py` and `ancient_empires/game_data/actor_scripts.py`: actor bytecode
  decoding and editable DSL/instruction views.
- `ancient_empires/audio/`: audio atlas, PC-speaker/Sound Blaster stream parsing,
  WAV preview and MIDI export.

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
- The recovered master timer is about `236.69 Hz`; actor scripts advance every
  24 master ticks, so Simulation defaults to 10 ticks/s (`~9.862` exact).
- Audio bytecode uses the same master tick. Multi-channel music shares global
  base-duration/bend state across streams, and CAF1 direct `?E` PC-speaker
  effects default to one-tick bursts unless `3D` overrides the effect length.
- Render layering uses the EXE compact3 split: high-bit visual decor before
  terrain, rope markers inside the terrain tile pass, low-bit visual decor
  after terrain, then gameplay objects and actors.
- Unknown payload bytes should remain inspectable. Do not promote guessed bytes
  into editable objects without evidence.

## Validation Loop

Compile after code changes:

```bash
python -m compileall ancient_empires ae_editor ae_game tools run_editor.py run_game.py
```

Export room previews after parser or renderer changes (reads `game_data/` by
default; pass a folder to use another location):

```bash
python run_editor.py --export-previews previews
```

Regenerate public docs screenshots after visual UI changes:

```bash
python tools/capture_docs_screenshots.py --exe game_data/AEPROG.EXE --dat game_data/AE000.DAT game_data/AE001.DAT
```

## Deeper Docs

- `docs/quick_start.md`: human launch and first-use guide.
- `docs/screenshots.md`: public screenshot tour.
- `docs/level_format.md`: canonical current file-format model.
- `docs/simulation_mode.md`: runtime simulation behavior, actor-script debugger
  and known gaps.
- `docs/actor_script_space.md`: actor script-space model and safe edit rules.
- `docs/actor_dsl.md`: actor DSL syntax.
- `docs/handoff.md`: current state, validation rooms and good next tasks.
