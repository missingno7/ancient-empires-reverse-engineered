# Level format notes — v16

## Main correction

Each decoded level resource in `AE001.DAT` resources `0..19` has length `0x6618` bytes. It is **not** one linear array of 38 rooms.

It consists of two equal blocks:

```text
0x6618 / 2 = 0x330c
```

Each block has this layout:

```text
0x0000..0x003f  part header, 64 bytes
0x0040..        13 room records, 1000 bytes each
                room record +0x000..0x001: unknown two bytes
                room record +0x002..0x2ad: 38×18 terrain bytes
                room record +0x2ae..0x3e7: unknown 314-byte payload
last 4 bytes    part footer, usually zero
```

Therefore room terrain offsets inside a part are:

```text
terrain_offset = part_base + 0x40 + room_index * 1000 + 2
```

For level 1 page A:

```text
room 0 terrain = 0x0042
room 1 terrain = 0x042a
room 2 terrain = 0x0812
room 3 terrain = 0x0bfa
...
```

This explains the old bug. The previous parser used:

```text
0x40 + room_index * 684
```

That made room 0 look almost correct, but room 1 started at `0x02ec` instead of `0x042a`, so it mixed metadata/object payload into terrain.

## Two pages / halves

Both halves begin with magic byte `0x4d` and a similar header. Their exact in-game meaning is unknown. They are exposed in the UI as `Page A` and `Page B`.

Possibilities:

- two variants/states of the same chamber,
- alternate/object pass,
- separate room graph pages,
- data used by different modes or transitions.

Do not assume Page B is junk. Its first rooms often render like valid terrain and are similar but not identical to Page A.

## Terrain codes

Terrain is a full byte per cell, not just a nibble. Current empirical mapping is in `constants.py`.

Common low codes:

```text
0x00 empty/background
0x01/0x02/0x03/0x04/0x05/0x06/0x07 terrain edge/block pieces
```

High codes seen in valid terrain:

```text
0x80, 0x90, 0xA0, 0xB0, 0xC0
```

These appear to map to larger terrain/front pieces in the terrain bank, for example vertical strips/side pieces. Rendering them makes level 1 room 1 much closer to the real screenshot.

## Unknown 314-byte room payload

Each room record has 314 bytes after the terrain grid. This is the strongest candidate for:

- actors / enemies,
- player spawn,
- artifacts / diamonds / pickups,
- buttons,
- moving platform definitions,
- trigger links,
- foreground decorations.

The editor includes a `trailing_hex` debug mode and CSV export to inspect it.

## Next suggested reverse-engineering steps

1. Compare the 314-byte payload with screenshots for known rooms.
2. Search for object triples/quads: `type, x, y, flags`, or `x, y, type, state`.
3. Find EXE routines that start from `record + 0x2ae` or iterate over room payload after drawing terrain.
4. Identify the exact tile lookup table in `AEPROG.EXE` for all terrain codes/themes.
5. Separate render order into background terrain, foreground/decor, actors, and UI.
