# Reverse-Engineering Notes

This file keeps the current research posture: what is known, what is partial,
and where to continue. Historical false starts were removed from the main docs
so the editor has one current model.

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

### Render Layering

Static disassembly of the room draw path around `0x2CE2` shows that the main
visual compact3 table is rendered in two passes: entries with `code >= 0x80`
are drawn before terrain, while entries with `code < 0x80` are drawn after
terrain as foreground decor. Rope-family terrain markers are drawn inside the
terrain tile loop, not as a later overlay, which lets wall/terrain art cover
rope artwork according to the same row-major tile order.

Animated decor has two mechanisms in the EXE. Four-byte records at the front of
the payload directory are handled by routines around `0xD81C/0xD99C`; the
12-byte table after the visual compact3 table is refreshed by a later animation
routine around `0xD586`. The static renderer keeps animated decal previews
behind the normal compact3 foreground pass, but exact per-frame redraw order
still deserves more capture-based verification.

### Actor Records

The actor table starts at part offset `0x2754`. Records are 0x20 bytes. The
editor maps the currently recognized frame ranges to actor names and renders
visible actors in normal previews while keeping hidden/start-state actors
available in debug overlays.

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
- EXE-derived anchor/origin tables for all rendered object families.
- Safe write-back rules for non-terrain payload edits.

## Suggested Continuation

1. Add tests for parser invariants using local game files or small fixtures.
2. Trace the EXE tables for tile-code-to-sprite and compact3-code-to-sprite
   lookup.
3. Expand actor script decoding against rooms with obvious movement paths.
4. Add fixture tests for current payload write paths and Simulation behavior
   before broad automated editing.
