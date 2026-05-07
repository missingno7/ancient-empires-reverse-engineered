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

## Decor flip

Visual compact3 decor entries are `[x_raw, y, code]`. Code bit `0x40` is a horizontal flip/mirror flag for theme visual sprites. The lower six bits still select the sprite. The editor exposes this as a `flip` property while preserving the raw code.

## Actor script space

The uploaded branch used for this patch does not yet include a full actor creation/repacking UI. When that UI is present, actor creation should allow both:

- a start/current `script_pc` address
- a restart/reset `restart_pc` address

Deleting an actor must not delete bytecode from shared script space unless a separate reference analysis proves that a bytecode block is truly unreferenced and the user explicitly chooses to garbage-collect it.
