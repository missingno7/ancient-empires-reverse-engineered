# Level format notes - v18

This document records the current working interpretation after checking level 1 room 1 against in-game screenshots.

## Confirmed/strong observations

### Room records

The v16 record layout still holds:

```text
level resource AE001 #0..19
  2 pages/parts
    0x40-byte part header
    13 room records × 1000 bytes
      +0x000..0x001 room preamble/unknown
      +0x002..0x2AD 38×18 terrain/control grid
      +0x2AE..0x3E7 trailing payload, likely object/control/trigger tables
    4-byte footer
```

### Terrain/control grid

The 38×18 grid is not purely static terrain. Some byte values are control/special tiles that need AE000 gameplay sprites, not AE001 terrain-bank sprites.

Known examples in level 1 room 1:

| Code | Current interpretation | Sprite source | Notes |
|---:|---|---|---|
| `0x07` | moving platform occupancy/path/current position | `AE000:047:0` horizontal, `AE000:048:0` vertical | Page A/B can move a platform; renderer groups contiguous `0x07` runs. |
| `0x90` | rope top | `AE000:005:0` | Previously mis-rendered as terrain. |
| `0xA0` | 24px rope middle segment | `AE000:006:0` | Followed by `0x80` continuation/filler cells. |
| `0x80` | rope continuation/filler | none directly | Covered by the previous 24px segment. |
| `0xB0` | short rope middle candidate | `AE000:007:0` | Not fully verified. |
| `0xC0` | rope bottom | `AE000:008:0` | |

The exact general rule for high-bit grid codes is still unknown. Do not assume all `0x80+` values are ropes; this is only the verified early-room behavior added to the renderer.

### Sprite banks now known to be important

| Sprite | Meaning from user/game visual checks |
|---|---|
| `AE000:004:*` | player animation states |
| `AE000:005:0` | rope top |
| `AE000:006:0` | rope middle, 24 px |
| `AE000:007:0` | rope middle/short segment |
| `AE000:008:0` | rope bottom |
| `AE000:040:0`, `AE000:043:0` | red switch/lever candidates |
| `AE000:044:0` | artifact/diamond |
| `AE000:045:0` | apple |
| `AE000:047:0` | horizontal moving platform |
| `AE000:048:0` | vertical moving platform |

## Trailing room payload

The 314 bytes after terrain are not random. In level 1 room 1 a strong count-prefixed table appears at trailing offset `0x1F`:

```text
+0x1F: 04
+0x20: 06 01 21 48 00 00
+0x26: 06 01 56 90 00 01
+0x2C: 06 01 8B 48 00/01 01
+0x32: 06 00 8D 58 00 01
```

The current parser calls this `typed6`: `count, then N*(type, subtype, x, y, arg_a, arg_b)`. Type `0x06` looks like a switch/control/trigger definition, so v18 can draw AE000 switch sprites for these entries in `terrain_objects` mode. This is still experimental because the exact anchor and the meaning of args are unknown.

Another candidate compact table follows later in some rooms, but it is not rendered as real objects yet.

## Known limitations

- Player, artifact/diamond, apples, enemies, and complete trigger relationships are not fully parsed yet. The sprites are available, but their storage schema is not proven.
- Moving-platform logic probably combines the grid (`0x07` cells), page A/B differences, and trailing payload controls. v18 only renders the visible platform graphics from contiguous code `0x07` runs.
- Rope rendering is based on level 1 room 1 and should be validated across other rooms/levels.
