# Simulation Mode

The Simulation tab is an in-memory runtime preview. It is meant for testing
actor behavior, control targets, symbol/green-block puzzles and room navigation
without writing back to the level data.

## Scope

Simulation runs against the current level, difficulty part and room. Switching
rooms through the top room selector or through the Simulation room-link buttons
creates a fresh room simulation for that room.

The default speed is 10 simulation ticks/s. AEPROG's recovered master timer is
approximately `236.69 Hz`; actor scripts advance every 24 master ticks, which
gives an actor cadence of about `9.862 ticks/s`.

The simulation owns transient state for:

- actor VM program counters, positions, frames, hidden flags and small loop/call
  state;
- button/switch/jello pressed state;
- green-block position, sequence progress and remaining visible symbols;
- a runtime terrain map for the current room, including moved `0x07`
  collision/support footprints.

The base room renderer remains static. The Simulation tab disables static actor,
platform, puzzle-panel and player-start drawing and then draws the simulated
positions/states on top.

## Controls And Targets

Control command target bytes are decoded the same way as the editor overlay:

```text
00..0F  P0..P15 platform slots
10..1F  CV0..CV15 visible conveyor records
40..4F  R0..R15 section_c reflector records
```

`M0` remains a UI alias for `R0`, but the canonical label is `R0`.

Simulation treats active controls targeting the same object as parity/XOR. One
pressed control activates the target; two pressed controls on the same target
cancel it; three activate it again.

The side-panel Controls tree can toggle controls by double-click. Left-clicking
the visible control sprite in the room does the same.

## Platforms And Runtime Collision

Moving platforms are the first ten 3-byte room trailing payload triplets. The
current observed travel vector is centralized in `ae_editor.coordinates`:

```text
0x40  +48 px x
0x60  -48 px x
0x80  +48 px y
0xA0  -48 px y
```

When a simulated platform target is active, Simulation redraws the platform at
the moved position and moves its `0x07` collision footprint in the runtime tile
map. Actor tile-condition opcodes read this runtime tile map for the current
room, so moved platform collision affects actor branches.

## Symbols And Green Blocks

Wall symbols are section_a compact3 entries and are displayed as `S1..S7`.
Clicking a wall symbol in Simulation emits that one-based symbol id.

Actor VM opcode `0x09` (`emit_symbol`) stores a zero-based raw id. Simulation
converts it before dispatch:

```text
raw 0 -> S1
raw 1 -> S2
...
raw 6 -> S7
```

Green blocks are section_b 12-byte records. Bytes `0..1` are the default
position, bytes `2..3` are the alternate position, and bytes `5..9` hold the
one-based symbol sequence terminated by zero.

Runtime behavior modeled in Simulation:

- a correct next symbol advances progress and removes that symbol from the
  displayed block sequence;
- a wrong symbol resets progress and restores the original displayed sequence;
- completing the full sequence toggles the block between default and alternate
  positions;
- after a completed move, the sequence is restored for the next toggle;
- the block's `0x07` collision footprint follows the current simulated block
  position.

## Room Links

Room links use the part-header one-based link arrays described in
`docs/level_format.md`. Simulation exposes them as side-panel buttons:

```text
Up, Left, Right, Down
```

Buttons are disabled when the current room has no link in that direction. The
room canvas intentionally has no room-link overlay so gameplay controls near
screen edges remain clickable.

## Known Gaps

- Actor VM timing is a practical preview, not a cycle-exact DOS runtime.
- Calls use a small simulated stack, but all VM event side effects are not
  fully known.
- Control command byte semantics beyond currently typed target lists remain
  partial.
- Platform travel distance and origins are still based on observed behavior and
  shared editor constants, not a fully recovered EXE motion table.
- Runtime tile edits are modeled for the current room. Cross-room actor
  conditions fall back to static room terrain.
