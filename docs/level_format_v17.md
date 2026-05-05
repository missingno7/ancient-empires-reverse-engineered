# Ancient Empires level format notes - v17

This file documents the current, still-incomplete interpretation of `AE001.DAT` level resources.

## Confirmed container/decode path

`AE000.DAT` and `AE001.DAT` are DAT archives with a 32-bit little-endian offset table.  Each resource starts with `rtype, flags`, followed by compressed payload bytes.  Flags are composable:

- `0x02` = LZW-like decompression
- `0x01` = RLE decompression

The image pipeline is integrated into the project now: VGA palette is read from `AEPROG.EXE`, type `0x47` images are decoded with their VGA colour table, and logical colour `0` is treated as transparent.

## Graphics resources

Important correction from v17: actor and gameplay sprites are not all in `AE001:021..028`.

- `AE001:021..024` are the four terrain/theme banks used by the terrain renderer.
- `AE001:025..028` are sprite/decor banks, but not the whole actor set.
- `AE000` contains many lower-numbered sprite banks.  These are now loaded and shown in the bank browser as `AE000:xxx`.

The bank browser is intentionally broad now because the player, enemies, UI objects and tool sprites are likely spread across both DATs.

## Level resource layout

Each of `AE001` resources `0..19` is one level.  The decoded size is `26136` bytes and the resource splits into two equal pages of `0x330c` bytes.

Current best layout per page:

```text
0x0000..0x003f  page header, starts with 0x4d
0x0040..        13 room records
                each record is 1000 bytes:
                  +0x000..0x001  unknown/preamble
                  +0x002..0x2ad  terrain, 38*18 bytes
                  +0x2ae..0x3e7  room payload, 314 bytes
last 4 bytes    page footer
```

Room terrain offset:

```text
page_base + 0x40 + room_index * 1000 + 2
```

This fixed a major earlier bug where room `1+` was read at the wrong stride.

## Terrain and page A/B behaviour

The visible room is `38 x 18` tiles, with an 8-pixel grid.  Terrain rendering currently uses an empirical code-to-sprite mapping into theme banks.

Page A and Page B are not simply duplicate rooms.  For example, in level 1 room 1, tile code `0x07` describes a horizontal moving platform.  Switching page A/B moves the platform position.  This suggests the two pages may represent alternate/dynamic states, or a pair of room-state snapshots used by the engine for moving obstacles.

## Room payload after terrain

The 314 bytes after terrain are no longer treated as random footer data.  They contain object/control/trigger information.

Observed examples:

### Level 1, room 1

Payload begins:

```text
A: 80 3c 20 60 70 58 ...
B: 80 3c 20 40 58 58 ...
```

These two leading 3-byte triplets change between pages and line up with moving-platform related positions.  They are shown in the editor as orange `lead` markers.

Later in the same payload there is a strong count-prefixed 6-byte table candidate:

```text
+0x1f: count = 04
+0x20: 06 01 21 48 00 00
+0x26: 06 01 56 90 00 01
+0x2c: 06 01 8b 48 00 01
+0x32: 06 00 8d 58 00 01
```

Interpreted experimentally as:

```text
type, subtype, x_px, y_px, arg_a, arg_b
```

This fits visible gameplay items/triggers better than previous attempts.

### Level 1, room 0

Another room appears to use a compact 3-byte table candidate at `+0x23`:

```text
+0x23: count = 03
then N * (x_px, y_px, type)
```

So the payload likely contains multiple schemas, or the schema is chosen by a room/header flag that has not yet been identified.

## Current editor modes for this

- `terrain`: terrain only
- `terrain_payload`: terrain plus payload coordinate markers
- `payload_probe`: payload candidates only, with ranked table candidates
- `trailing_hex`: raw visualisation of the 314-byte payload

## Unknown / next work

1. Identify the real room-payload schema selector.
2. Map object/trigger type IDs to sprite banks and gameplay semantics.
3. Determine how page A/B is used at runtime for moving platforms and doors.
4. Disassemble the routine that parses room payload records; likely constants to look for are `0x03e8` room stride and `0x02ac` terrain byte count.
5. Fix exact terrain draw order and anchoring for large/tall sprites such as ropes and foreground pieces.
