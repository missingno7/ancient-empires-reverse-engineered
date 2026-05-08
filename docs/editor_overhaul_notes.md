# Editor overhaul notes

## Scope model

- Rooms shown in the editor are `0..9`. The physical 1000-byte records after that are actor-block bytes and should not be treated as normal rooms.
- Actors are level-part global. `A0`, `A1`, ... are indices in the actor table.
- Platforms, controls, reflectors, conveyors, decor, puzzle blocks and room links are room-local.

## Player start

The editor exposes player start as a header object with raw x/y only. Static analysis of AEPROG.EXE shows the game always initializes the current room to 0 and reads raw header[0x03]/[0x04] for start x/y; raw header[0x01] is not a start-room field.

## Room links

Room links are the navigation arrays at level-part offsets:

- left: `0x1A + room`
- right: `0x24 + room`
- up: `0x2E + room`
- down: `0x38 + room`

UI uses zero-based room numbers and `-` for no link. Stored values are one-based room numbers, with `0` meaning no link.

The Simulation tab exposes these links only as buttons in the right panel. Do
not draw room-link hitboxes over the room canvas; edge overlays can hide
gameplay switches and symbols that need to remain clickable.

## Simulation mode

Simulation is a runtime preview, not an editor write path. It layers simulated
state over the static renderer and keeps its own in-memory actor/control/puzzle
state for the current room.

Current modeled behaviors:

- actor VM stepping for the researched opcode subset;
- control target parity/XOR across active switches;
- platform travel and moved `0x07` support footprints;
- wall symbol clicks;
- actor `emit_symbol` raw id conversion (`raw 0 -> S1`);
- green-block sequence progress/reset/toggle and moved `0x07` footprint;
- side-panel room-link navigation.

Keep future simulation additions in `ae_editor/simulation.py` when they affect
runtime behavior. GUI code should only map clicks to simulation events and draw
the current simulated state.

## Decor flip

Visual compact3 decor entries are `[x_raw, y, code]`. Code bit `0x40` is a horizontal flip/mirror flag for theme visual sprites. The lower six bits still select the sprite. The editor exposes this as a `flip` property while preserving the raw code.

## Actor script space

Actor creation supports new tiny wait scripts, sharing an existing selected
script entry, or using an explicit script address. Keep both pointer concepts
visible:

- a start/current `script_pc` address
- a restart/reset `restart_pc` address

Deleting an actor must not delete bytecode from shared script space unless a separate reference analysis proves that a bytecode block is truly unreferenced and the user explicitly chooses to garbage-collect it.
