# Level format notes - v20 payload/platform research

This file records the current interpretation after comparing exported rooms with in-game screenshots.

## Confirmed / high-confidence

### Resource layout

`AE001.DAT` resources `0..19` are the 20 levels.

Each decoded level resource is currently parsed as two equal parts, exposed as **Page A** and **Page B**:

```text
level resource
  part A
  part B

part
  0x40-byte header
  13 room records × 1000 bytes
  4-byte footer

room record
  +0x000..0x001  room preamble / metadata, not fully decoded
  +0x002..0x2AD  38×18 terrain/collision grid, row-major
  +0x2AE..0x3E7  314-byte room payload
```

The `1000` byte room-record stride is important. Earlier builds used `684` byte strides and therefore room 0 looked plausible while later rooms were shifted into metadata/payload bytes.

### Terrain grid

The visible room grid is `38×18` cells. Each terrain cell is an 8×8 pixel grid unit, so the viewport is `304×144` pixels.

Terrain code `0x07` is no longer treated as visible platform art. The current best interpretation is:

```text
0x07 = invisible solid/collision/support cell
```

Visible moving platforms are drawn from room payload data, not inferred from runs of `0x07` cells. This explains why level 1 room 2 has a T-shaped `0x07` support under the statue: it behaves like a support/collision shape, not like a visible lift.

### Ropes in terrain grid

The rope in level 1 room 1 is stored directly in the grid using high codes such as `0x80`, `0x90`, `0xA0`, `0xB0`, `0xC0`. These are special terrain/object cells and must not be mapped through the normal `AE001:021` terrain bank.

Current sprite mapping:

```text
0x90 -> AE000:005:0 rope top
0xA0 -> AE000:006:0 rope middle/tall
0xB0 -> AE000:007:0 rope middle/short
0xC0 -> AE000:008:0 rope bottom
0x80 -> continuation covered by the tall segment, currently not drawn directly
```

## Room payload

The 314 bytes after the terrain grid are definitely structured. They contain moving platform positions, switches/control objects, decorations, enemies, pickups, and probably trigger logic.

### Leading triplets

The first bytes of the payload often behave like position/state triplets:

```text
flag, x_px, y_px
```

Examples:

```text
L20 room 0 Page B:
  A0 10 58
  A0 18 58
```

These match the two visible vertical blue platforms in the supplied in-game screenshot. Therefore v20 renders `A0` leading triplets as `AE000:048:0` vertical platforms.

Other observed flags:

```text
0x60, 0x80 -> likely horizontal/moving platform or related state
0xA0       -> vertical platform in observed L20 room 0 Page B
```

This is still a research interpretation: the flag probably also encodes state/direction/linkage.

### Count-prefixed object/decor tables

Some rooms have a clear count-prefixed 3-byte table in the payload. For example, level 1 room 2 contains:

```text
payload +0x23:
  0A
  82 25 09
  4D 67 05
  64 25 48
  29 25 49
  0C 24 88
  10 4F 02
  0E 81 02
  28 5E 02
  61 5D 02
  1A 2C 02
```

Current experimental schema:

```text
count
N × (x_raw, y_px, object_code)
```

For many wall decorations `x_px = x_raw * 2`. For some small/gameplay objects the x interpretation may differ; the renderer keeps raw data visible in `object_table` mode.

Known object/decor clues:

```text
AE000:004      player animation frames
AE000:005..008 rope pieces
AE000:044:0    diamond/artifact pickup
AE000:047:0    horizontal moving platform sprite
AE000:048:0    vertical moving platform sprite
AE001:025      early-level background/foreground decor bank, including plaques/statues
```

## Pages A/B

Pages A and B are not just moving-platform states. Level 20 room 0 shows Page A and Page B with substantially different terrain layouts. Keep both pages visible in the UI. Do not collapse them into a single “alternate platform state”.

Possibilities still under investigation:

- two chambers / two halves of a cavern,
- alternate room graph/state,
- different start/goal configurations,
- active/inactive puzzle state pages.

## Current renderer behavior

Default `terrain_objects` mode does this:

1. Draws the terrain background from the level theme.
2. Draws normal terrain cells through the theme terrain bank.
3. Skips `0x07` as invisible solid/collision support.
4. Draws ropes from `AE000:005..008`.
5. Draws leading-payload moving platform candidates.
6. Draws a small number of experimentally mapped object/decor entries.

Useful research modes:

- `collision_debug`: show invisible `0x07` cells as magenta boxes.
- `object_table`: draw labels for the currently selected 3-byte object/decor table.
- `payload_probe`: show candidate parsed payload tables.
- `trailing_hex`: raw visualization of the 314-byte payload.

## Still unknown / next work

1. Exact meaning of room preamble bytes.
2. Exact object/decor table schema across all levels.
3. Player start location encoding. Starting-position screenshots should help; it is probably in the level/part header or in a payload table, not as a normal room object.
4. Full mapping from object codes to sprite bank/subsprite.
5. Trigger/link format: buttons, moving platforms, doors/passages, conveyor belts.
6. Meaning of Page A/B and how the game transitions between them.
7. Exact draw order / sprite anchor rules. Current anchors are heuristic.
