# Shared engine architecture

`ancient_empires` is the shared reverse-engineered implementation. `ae_editor`
and `ae_game` are separate applications that consume it.

## Ownership rules

- `game_data/` owns original bytes: archives, decompression, executable tables,
  parsed records and guarded write-back.
- `engine/` owns deterministic gameplay state and rules: player state, actors,
  controls, platforms, collision, puzzles, room transitions and gameplay events.
- `rendering/` owns visual interpretation. It may read engine snapshots but must
  not advance gameplay state.
- `audio/` owns audio resource decoding and playback/export services. Engine code
  emits sound events; it does not open devices or create UI workers.
- `ae_editor/` owns Tkinter interaction, diagnostics, editing and editor state.
- `ae_game/` owns player input, the real-time loop, camera/presentation and menus.

The shared package must not import either application package.

## Current state

`engine/runtime.py` contains small shared rules. `engine/room_simulation.py`
contains the recovered room-local actor/control/puzzle behavior used by the
editor Simulation tab. It is not yet a complete game engine.

The player-facing game renders the first level screen through shared
`rendering/game_screen.py` and drives the room-local player slice in
`engine/player.py`. Room transitions and the remaining gameplay systems are
still being reconstructed from `Decompile notes/AEPROG_full_disasm.asm`.

## Engine API direction

The final API should be deterministic for a given initial state and input stream:

```python
engine = GameEngine(level, difficulty=0)
engine.apply_input(PlayerInput(left=True))
events = engine.tick()
snapshot = engine.snapshot()
```

Events should report sounds, room changes, puzzle changes and other side
effects. The editor may inspect every detail; the game may present only what
players need.

## Constraints

- Do not put Tkinter, dialogs, `sounddevice`, subprocess playback or application
  lifecycle code in `ancient_empires.engine`.
- Do not duplicate gameplay rules in editor and game code.
- Do not invent behavior to make `run_game.py` appear playable.
- Keep uncertain reverse-engineered values visible until their semantics are
  supported by executable evidence or repeatable observations.
