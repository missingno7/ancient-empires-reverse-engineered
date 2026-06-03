# Shared engine architecture

The next stage is a real playable game alongside the research editor. The editor
and game should share recovered gameplay rules, but they should not share UI
code or depend on each other's application lifecycle.

## Target packages

```text
ae_editor/
  game_data/     Binary archive, resource and level decoding/editing.
  engine/        Shared deterministic runtime state and gameplay rules.
  rendering/     Shared visual interpretation and room rendering helpers.
  audio/         Shared audio resource decoding and playback/export services.
  ui/            Tkinter editor tabs and widgets.
  app/           Editor process startup and window wiring.

ae_game/         Future playable game application, input loop and presentation.
```

The package name `ae_editor` can remain during the migration. The important
boundary is that `engine/` does not import from `ui/`, `app/`, or Tkinter. A
later package rename can be mechanical once the shared API is stable.

## Ownership rules

- `game_data/` owns bytes: archive access, decompression, parsed records and
  guarded write-back helpers.
- `engine/` owns time and rules: world state, room transitions, collision,
  actors, controls, platforms, puzzle state and emitted gameplay events.
- `rendering/` owns visual interpretation. It may read engine snapshots, but it
  must not advance gameplay state.
- `audio/` owns audio decoding and playback services. Engine code emits sound
  events such as a sound id; it does not open devices or create Tk workers.
- `ui/` and `app/` own editor interaction, selection, dialogs, background work
  and presentation-specific state.
- `ae_game/` will own real-time input, the main loop, camera/presentation and
  player-facing menus.

## Migration path

1. Treat `ae_editor/simulation/room_simulation.py` as the main migration source,
   not as an editor feature to extend indefinitely.
2. Define small input and output contracts around it: immutable room/level
   inputs, explicit tick/input commands, snapshots, and gameplay events.
3. Move deterministic rules into `ae_editor/engine/` in tested slices. Keep the
   Simulation tab as the first consumer of each extracted slice.
4. Add the future game as a second consumer only after the shared rule has
   fixtures or regression tests.
5. Keep research-only diagnostics available through snapshots and events rather
   than exposing editor widgets or callbacks inside the engine.

## Engine API shape

The exact API should follow recovered behavior, but a useful direction is:

```python
engine = GameEngine(level, difficulty=0)
engine.apply_input(PlayerInput(left=True))
events = engine.tick()
snapshot = engine.snapshot()
```

`tick()` should be deterministic for a given initial state and command stream.
Events can report sounds, room changes, puzzle changes and other side effects.
The editor may inspect every detail; the game may present only what players
need.

## Avoid during cleanup

- Do not move parsers into the engine merely because gameplay uses them.
- Do not let the engine call Tkinter, `sounddevice`, file dialogs or subprocess
  playback.
- Do not create separate editor and game implementations of the same rule.
- Do not hide uncertain reverse-engineered behavior behind a confident gameplay
  abstraction; preserve raw values and diagnostics until the rule is proven.
