# Reverse-engineering notes

## What is known with high confidence

### Archive/decompression

The `.DAT` files use a simple offset table. The decompression pipeline is working and shared by both the image decoder and the level editor.

Resource flags are interpreted as:

```text
0x02 = LZW-like stage
0x01 = RLE stage
```

The stages are applied in that order.

### Graphics

The correct image decoder is the v9 VGA decoder:

- it reads the custom game palette from `AEPROG.EXE`,
- it decodes type `0x47` images,
- it uses the VGA colour substitution table, not just EGA RGBI,
- it supports alpha by treating logical colour `0` as transparent.

This fixed the earlier blue/garbage sprite-background problem.

### Room size

A room is `38×18` cells. That matches real gameplay screenshots much better than earlier whole-map guesses.

The renderer uses an 8px grid:

```text
38 * 8 = 304 px
18 * 8 = 144 px
```

This explains why terrain sprites can be around `18×17` but still form a grid: they are placed every 8 pixels and overlap.

### Level resource candidates

`AE001.DAT` resources `0..19` are level/cavern resources. They begin with magic-like byte `0x4D` and parse consistently into:

```text
0x40 + 38 * 684 + 80 bytes
```

The theme is currently read as:

```text
theme = header[2] & 3
```

This matches the presence of four terrain banks at `AE001` resources `21..24`, but the exact game logic should still be verified in disassembly.

## What is partially solved

### Terrain tile rendering

The best visual match so far is the v11/v15 approach:

```text
full room byte -> terrain code -> sprite index in theme terrain bank
```

Current mapping lives in `ae_editor/constants.py`:

```python
DEFAULT_TERRAIN_CODE_TO_SPRITE = {
    0x00: None,
    0x02: 5,
    0x03: 7,
    0x04: 8,
    0x05: 9,
    0x06: 10,
}
```

This is not complete. It exists because it makes real rooms start to look like the screenshots: repeated wall blocks, solid blocks, platform lips and room borders.

A previous low-nibble/high-nibble split looked plausible but made `level_01_room_00` worse. It is therefore not the default.

### Cropping / offscreen columns

Screenshots suggest that some previews have two extra columns on the left relative to the visible game area. The UI has a `crop left 2 cols` toggle. This is intentionally a presentation option, not baked into the parser.

## What is not solved yet

### Actors and gameplay objects

Objects are not yet correctly parsed.

The following are likely **not** simply terrain bytes:

- player start,
- enemies,
- diamond/artifact piece,
- apples/energy pickups,
- buttons,
- moving platforms,
- doors/passages/triggers,
- foreground decorations and background-only decorations.

Several failed hypotheses were tried:

1. `10 × 3 byte` object slots immediately after room terrain.
2. Scanning compact triples in the level header.
3. Treating high nibble of each terrain byte as an object/decor layer.

None matched screenshots well enough to keep as canonical.

Recommended next step: use disassembly to find the routine that initializes the visible room and actor list when entering a chamber. Look for constants `0x2AC`, `38`, `18`, sprite-bank resource IDs `25..28`, or calls to the type47 blitter shortly after room load.

### Exact tile lookup tables

The game probably has lookup tables that map a tile code to a sprite index depending on theme and/or room state. The current editor uses a small hand-discovered mapping. A complete editor needs to recover the actual lookup tables from `AEPROG.EXE` or infer them from game-rendered screenshots.

### Draw order

Terrain draw order is currently row-major top-to-bottom. This is close but not exact in every screenshot. Some elements may be background, terrain, foreground overlay, or actor sprites with different draw passes.

## Suggested continuation plan

1. Find the EXE function that loads a room from a level resource.
2. Identify where `38×18` bytes are copied/read.
3. Trace the tile-code-to-sprite lookup.
4. Trace the actor list initialization.
5. Split renderer into confirmed passes:
   - background,
   - terrain/metatiles,
   - decorations,
   - actors/items,
   - foreground/UI.
6. Only after the read path is confirmed, add safe write-back.

## v16 correction: room record stride

The old `38 rooms × 684 bytes` interpretation is wrong. The decoded level resource is two `0x330c` parts. Each part contains 13 room records of 1000 bytes. The 38×18 terrain grid begins two bytes into each room record.

Formula:

```text
part_base = 0 or 0x330c
room_record = part_base + 0x40 + room_index * 1000
terrain = room_record + 2
terrain_length = 38 * 18 = 684
unknown_room_payload = room_record + 2 + 684, length 314
```

This fixes the shift that made level 1 room 1 render as nonsense. The correct level 1 page A room 1 terrain offset is `0x042a`.
