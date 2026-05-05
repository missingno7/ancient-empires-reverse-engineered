# v21 research notes — room payload objects and platforms

This version is still a research build, but it fixes several wrong assumptions from v18-v20.

## Important correction: terrain code `0x07`

`0x07` in the 38×18 terrain grid is **not** the visible moving-platform sprite.
It behaves better as an invisible solid/collision/support marker. Visible moving
platforms are drawn from the room payload.

This explains level 1 room 2: the central T-shaped support made of `0x07` cells
is not a platform. It is likely collision/support for the big statue.

## Leading payload triplets

At the start of the 314-byte trailing room payload there is a variable-length
prefix of 3-byte records:

```text
flag, x_unit, y_px
```

Earlier builds only parsed two triplets. Level 2 room 0 page B proves there can
be at least five:

```text
A0 80 60   vertical platform at x=0x80*2, y=0x60
40 30 48   horizontal platform/control at x=0x30*2, y=0x48
A0 70 60   vertical platform at x=0x70*2, y=0x60
A0 78 60   vertical platform at x=0x78*2, y=0x60
80 90 20   horizontal platform/control at x=0x90*2, y=0x20
00 ...     terminator/padding
```

The x coordinate is currently rendered as `x_unit * 2`, which lines up much
better with the screenshots than raw x.

## Compact3 visible object/decor tables

The room payload also contains count-prefixed compact tables:

```text
count, then count × (x_raw, y_px, code)
```

`x_raw` often behaves as a half-pixel center coordinate (`x_px = x_raw * 2`).
`y_px` often behaves as a bottom/baseline anchor. v21 renders known sprites with
that bottom-center anchor.

Example: level 2 room 0 page B has a visible table at payload `+0x44`:

```text
04
31 7B 1A   vase: AE001:025:26
12 58 0E   button/switch family: AE000:039:0
15 1E 02   enemy-family candidate
88 56 80   laser trigger / pudding: AE000:041:0
```

Known code mappings added in v21:

| code | current render | confidence |
| --- | --- | --- |
| `0x1A` | `AE001:025:26` vase | high, user-confirmed |
| `0x0E` | `AE000:039:0` ceiling/floor button family | medium |
| `0x80` | `AE000:041:0` laser trigger/pudding | high, user-confirmed |
| `0x02` | `AE000:022:12` spider in L2 room 0 page B, otherwise `AE000:022:20` crawler fallback | low/medium |
| `0x05` | `AE001:025:36` large statue | medium |
| `0x09`, `0x48`, `0x49`, `0x88` | `AE001:025` wall relief/plaque variants | medium |
| `0x8E` | `AE000:044:0` diamond | high, user-confirmed |

## Still unsolved

- The player start location is not yet parsed. The screenshot for level 20 room
  0 page B is useful because the player is at the start position, but v21 does
  not decode the start record yet.
- The spider/enemy table is not fully solved. Some enemies may be dynamic actor
  records rather than compact3 decorations.
- Button/trigger records probably also have a separate control table linking
  them to moving platforms, gates, lasers, etc. v21 only renders the visible art.
- Page A/B are not merely animation states. Some rooms have substantially
  different terrain/layout between pages.

## Renderer implication

The current visible room render is roughly:

1. background pattern by theme
2. terrain tile grid, skipping special collision cells such as `0x07`
3. rope cells from terrain codes `0x80..0xC0`
4. leading payload platform triplets
5. compact3 payload visible object/decor sprites

This is now much closer to the screenshots, but object semantics are still under
active reverse engineering.
