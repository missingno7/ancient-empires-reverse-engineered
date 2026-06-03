# Reverse-Engineering Notes

This file records what is known, what is partial, and where to continue.

## Known With High Confidence

### Archives And Compression

The DAT archive reader and decompression pipeline are shared by graphics and
level loading. Resource flags are interpreted as:

```text
0x02 = LZW-like stage
0x01 = RLE stage
```

The stages run in that order.

### Graphics

The editor decodes type `0x47` VGA images with the custom game palette from
`AEPROG.EXE`. Logical colour `0` is treated as the transparent blitter key.

Graphics are source-qualified because gameplay sprites are split across both
archives:

- `AE001:021..024`: terrain banks for the four themes;
- `AE001:025..028`: theme visual/decor banks;
- `AE000`: actors, UI, ropes, switches, pickups, projectiles and platforms.

### Level Structure

`AE001.DAT` resources `0..19` are the 20 caverns. Each level resource contains
two difficulty parts: Explorer and Expert. Each part has a 0x40-byte header,
10 fixed room records of 1000 bytes, a 4-byte separator, and a 3000-byte actor
block at part offset `0x2754`. Earlier notes that described 13 room records were
parsing the actor block as three garbage pseudo-rooms.

The room terrain grid is 38 by 18 cells. Rendering uses 8 px cells, producing a
304 by 144 px static room viewport before zoom.

Header bytes `0x05..0x07` store the conditional exit door that appears after
all artifacts are collected. It uses sprite 0 from the current theme terrain
bank (`AE001:021..024`) and the same doubled-x screen-space coordinate family
as several payload objects.

## Partially Solved

### Terrain Mapping

The current terrain mapping lives in `ae_editor/tile_mapping.py`. It is a small,
confirmed mapping from logical tile codes to sprite indexes in the active theme
terrain bank. It is intentionally incomplete until the EXE lookup table is
recovered.

Special terrain codes handled outside the direct mapping:

- `0x07`: invisible support/collision;
- `0x0F`, `0x1F`: conveyor physics tile runs; visible art comes from CV payload records;
- `0x80..0xC0`: rope-family markers.

### Room Payload

The trailing payload begins with ten platform triplets. The EXE-style payload
directory currently decodes:

- length-prefixed control records;
- puzzle marker compact3 table;
- record12 green-block mechanism records;
- laser crystal compact3 table;
- main visual compact3 table.

Buttons, floor switches and laser triggers are control commands. Actors are not
inferred from those commands; they come from the part actor table.

Control targets are currently typed as `P`, `CV` and `R`. Runtime switch
composition appears to be parity/XOR: two active switches aimed at the same
target cancel each other. The Simulation tab models this.

Green-block record12 entries have a default position, alternate position and
one-based symbol sequence. Simulation models the observed behavior: correct
symbols consume the visible sequence, wrong symbols reset it, and completing
the sequence toggles the block position and restores the sequence.

### Render Layering And The Shared Object Anchor

The room draw path has been disassembled in full. The EXE composes a room into
an offscreen buffer and scrolls a window of it to the screen. Every sprite goes
through one of two blitters: `0x3CC -> 0x1A98` (transparent, colour 0 keyed) for
objects and `0x3C9 -> 0x1930` (opaque block copy) for backgrounds. Both are pure
top-left blits — no width/2, no height subtraction, and the 36-byte `0x47`
graphics header carries no per-sprite hotspot.

Almost every payload object is placed with one shared anchor. The buffer
position is `(raw_x*2, raw_y + 0xB8)` and the editor crops the buffer at the
background backdrop origin `(8, 200)`, so the editor top-left is:

```text
object   buffer (raw_x*2,   raw_y + 0xB8=184)  -> editor (raw_x*2 - 8,  raw_y - 16)
terrain  buffer (col*8 + 4, row*8  + 0xC4=196) -> editor (col*8 - 4,    row*8 - 4)
rope     buffer (col*8 + 8, row*8  + 0xC8=200) -> editor (col*8,        row*8)
```

The shared object anchor covers compact3 background (`0x2BF7`, `code >= 0x80`,
before terrain) and foreground (`0x2D3E`, `code < 0x80`, after terrain), header
diamonds (`0x2E32`), the room-gated apple (`0x2E89`, runtime `room[0x3E5..0x3E7]`),
control buttons/switches/triggers (`0x2F10`), and puzzle symbols (`0x3085`, with
the symbol overlay nudged `+4` px in X). Rope tiles are drawn inside the terrain
loop (`0x2CCF`).

Moving platforms are the one exception. The static platform draw (`0x28AC`,
which also writes the `0x07` collision footprint from the room+0x2AC triplets)
uses `(x_raw*2 - 4, y + 0xB4=180)` -> editor `(x_raw*2 - 12, y - 20)`. The
per-frame moving redraw (`0x338A`) uses the shared anchor instead; the editor
previews the resting position, so it follows `0x28AC`.

Recovered static draw order (gameplay objects stack on top of decor):

```text
backdrop (0x2BC0)
compact3 background, code >= 0x80 (0x2BF7)
terrain + rope tiles (0x2C71)
compact3 foreground, code < 0x80 (0x2D3E)
laser crystals (0xD61C) / platforms (0x28AC)
header diamonds (0x2E32) / apple (0x2E89)
control buttons, switches, triggers (0x2F10)
puzzle symbols (0x3085) / green blocks (0x3132)
actors, drawn each frame on top (0x4EF8)
```

Animated decor still has two mechanisms in the EXE. Four-byte records at the
front of the payload directory are handled by routines around `0xD81C/0xD99C`;
the 12-byte table after the visual compact3 table is refreshed by a later
animation routine around `0xD586`. The static renderer keeps animated decal
previews behind the compact3 foreground pass, but the exact per-frame redraw
order of the animated mechanisms still deserves more capture-based verification.

### Actor Records

The actor table starts at part offset `0x2754`. Records are 0x20 bytes. The
editor maps the currently recognized frame ranges to actor names and renders
visible actors in normal previews while keeping hidden/start-state actors
available in debug overlays.

The actor draw loop (`0x4EF8`) reads a full-resolution 16-bit X at `rec+0x02`
(not the halved raw-x used by payload objects), Y at `rec+0x04`, frame at
`rec+0x06` and the facing/flip bit at `rec+0x07`. It blits via `0x3CC` with
`x_arg = x` and `y_arg = vertical_base + y`; the steady-state room draw passes
`vertical_base = 0xB8` (`0x399A/0x399E`). So actors share the universal anchor —
buffer `(x, y + 0xB8)`, editor `(x - 8, y - 16)` — uniformly for every enemy.

Record byte `0x00` behaves like the actor mode for runtime stepping. Stock
secondary actors and projectiles commonly start as mode `1`, hidden and asleep.
Shooter scripts use `set_actor_mode_0` to wake the projectile's stored PC;
projectile scripts use `set_actor_mode_1` plus `hide` to stop themselves. Stock
projectile scripts park that PC at the dormant `script_pc` after hiding. The
`restart_pc` remains a separate script entry, often used by death/collision
cleanup rather than as the normal wake address.

Actor script decoding is still partial. The overlay can show decoded movement
segments when the current subset recognizes them.

The Simulation tab steps the researched actor VM subset and dispatches
`emit_symbol` into the green-block mechanism. Actor bytecode stores
`emit_symbol` ids zero-based; raw `0` emits displayed `S1`.

### Audio

Audio previews are decoded from type `0x44` resources. The confirmed
`play_sound`/CAF1 bank is `AE000:065`; disassembly around `0xCAF1` shows that
it drives the PC speaker through PIT channel 2 (`0x42`) and port `0x61`.

Both music and one-shot SFX use the same low-nibble bytecode families:
`1..12` note/rest timing, `D` controls, `E` direct pitch/effect tone and `F`
terminator/loop. The music path uses global base-duration and bend words
(`ds:1788`/`ds:178a`) shared by all channels; the CAF1 one-shot path mirrors
that with `ds:1e84`/`ds:1e86`. MIDI/WAV export therefore needs to parse
multi-channel music on one shared timeline instead of decoding each channel in
isolation, otherwise later `4D`/`1D`/`2D` commands make channels drift.

For CAF1 direct-pitch effects (`?E` opcodes), `3D xx` sets the effect duration
word (`ds:1e92`). CAF1 initializes it to `1`, so streams such as `play_sound`
`0x06` and `0x07` are intentionally one-master-tick bursts, not sustained
notes. This produces a noisier/raspier PC-speaker effect when previewed.

## Still Unknown

- Complete terrain and theme visual lookup tables.
- Exact semantics for every control-command argument and VM event id.
- Full trigger graph behavior beyond current `P`/`CV`/`R` target classes.
- Complete actor script instruction set and cycle-exact runtime timing.
- Full collectible/item storage schema.
- `player_start` preview anchor (currently `x*2 - 4`) and the exact per-frame
  draw of laser crystals, conveyor belts and animated decals (`0xD61C/0xD818`)
  are not yet traced; every other object family's anchor is now EXE-derived.
- Safe write-back rules for non-terrain payload edits.

## Suggested Continuation

1. Add tests for parser invariants using local game files or small fixtures.
2. Trace the EXE tables for tile-code-to-sprite and compact3-code-to-sprite
   lookup.
3. Expand actor script decoding against rooms with obvious movement paths.
4. Add fixture tests for current payload write paths and Simulation behavior
   before broad automated editing.
