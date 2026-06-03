# Project structure

The repository contains one shared reverse-engineered implementation and two
applications.

```text
ancient_empires/
  game_data/    DAT/EXE decoding, parsed binary models and guarded write-back.
  engine/       Shared deterministic gameplay rules and runtime state.
  rendering/    Shared visual interpretation, overlays and room rendering.
  audio/        Shared audio decoding, playback and export.
  exporters/    Shared PNG/CSV export helpers.
  constants.py  Shared recovered constants.
  project.py    Loaded original asset bundle.

ae_editor/
  app/          Editor command line and Tk window wiring.
  ui/           Tkinter editor tabs, widgets and interaction state.

ae_game/
  app/          Player-facing source-port application.

run_editor.py
run_game.py
```

Dependency direction:

```text
ancient_empires.game_data
          ↓
ancient_empires.engine / rendering / audio
          ↓
ae_editor / ae_game / tools
```

`ae_editor` and `ae_game` must not be imported by `ancient_empires`.

## Shared package

- `game_data/level_format.py` — level, difficulty part and room binary format.
- `game_data/room_payload.py` — room payload, control, platform and actor records.
- `game_data/actor_dsl.py` — lossless actor VM DSL and assembler-like IR.
- `game_data/actor_scripts.py` — actor bytecode disassembly and path summaries.
- `engine/runtime.py` — shared control-target and platform movement rules.
- `engine/room_simulation.py` — recovered room-local actor/control/puzzle runtime.
- `engine/player.py` — recovered room-local player walking, gravity and jump.
- `rendering/room_renderer.py` — static room rendering from decoded assets.
- `rendering/overlay.py` — diagnostic overlay geometry.
- `audio/core.py` — audio atlas, stream parsing and MIDI/WAV/VGM export.
- `audio/playback.py` — realtime playback and preview lifecycle.
- `project.py` — archive, executable asset, graphics, level and renderer bundle.

## Applications

- `ae_editor/app/cli.py` — editor startup and export commands.
- `ae_editor/app/main_window.py` — Tk editor window.
- `ae_editor/ui/` — editor-only interaction and presentation.
- `ae_game/app/cli.py` — game startup and first room-local gameplay slice.

See [Shared engine architecture](engine_architecture.md) and
[Gameplay reverse engineering](gameplay_reverse_engineering.md).
