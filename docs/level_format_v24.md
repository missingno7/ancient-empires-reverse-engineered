# Ancient Empires level research notes - v24

This build is mainly a cleanup/research step after the v23 terrain mapping fix.
The basic terrain mapping is now much more reliable, but object/decor/actor
coordinates are still the active research area.

## Confirmed / strong observations

### Terrain records

AE001 resources `0..19` are the twenty level resources.  Each resource is split
into two equal parts, currently exposed as **Page A** and **Page B**:

```text
part:
  0x40 header
  13 room records * 1000 bytes
    +0x000..0x001  room preamble / metadata
    +0x002..0x2AD  terrain grid: 38 * 18 bytes
    +0x2AE..0x3E7  room payload: controls/decor/actors/triggers
  4 byte footer
```

Terrain is row-major, 38 columns by 18 rows, with 8 px cells.

### Terrain code mapping

v23 fixed a long-standing off-by-one-ish mistake.  The main wall/platform tiles
are currently mapped as:

```text
0 -> empty/background only
1 -> AE001:021+theme:5
2 -> AE001:021+theme:6
3 -> AE001:021+theme:7
4 -> AE001:021+theme:8
5 -> AE001:021+theme:9
6 -> AE001:021+theme:10
7 -> invisible solid/support/collision marker, not a visible platform
```

This removed many renderer hacks that were attempts to compensate for the wrong
base lookup.

### Ropes and some special grid codes

Rope is encoded in the terrain grid, but rendered from AE000, not the terrain
bank:

```text
0x90 -> AE000:005:0 rope top
0xA0 -> AE000:006:0 long middle segment
0xB0 -> AE000:007:0 short middle segment
0xC0 -> AE000:008 rope bottom
0x80 -> continuation/filler, usually covered by neighbouring rope sprites
```

### `0x07` is collision/support

The earlier idea that `0x07` shape detection identifies moving platforms was
wrong.  It is better understood as invisible solid/support/collision.  Visible
moving platforms are room payload objects drawn over that collision layout.
This explains why `0x07` can form a T-shaped support for a statue in L1 room 2.

### Payload is not one single object list

The 314-byte trailing payload contains several sections, not one universal list.
Known/likely sections:

1. first ten 3-byte records: platform/control triplets
2. one or more count-prefixed compact3 tables: `count, count * (x, y, code)`
3. additional still-unknown control/trigger sections

The game can have more than two independent moving things even though the level
resource has only Page A and Page B, because the independent state/motion is in
payload/control records.  Page A/B are two stored room/layout parts; they should
not be interpreted as the complete set of possible platform states.

## v24 changes

### Coordinate model module

Coordinate conversions are now centralized in `ae_editor/coordinates.py`:

- platform triplets: `x = x_raw * 2 - 4`, `y = y_raw`
- compact3 top-left: `x = x_raw * 2`, `y = y_raw`
- compact3 bottom-center: `x = x_raw * 2 - sprite_width/2`, `y = y_raw - sprite_height`
- actor 2x candidate modes remain exposed for debugging

This is deliberately not hidden inside ad-hoc renderer hacks.

### Experimental +4,+4 viewport alignment

Some screenshots suggest the final game viewport may be blitted with a half-cell
(+4 px, +4 px) offset compared with the raw terrain grid.  v24 adds a GUI
checkbox **test +4,+4 align** and CLI flag `--test-align` for exports.  This is
only a visual experiment; it does not change decoded data.

### Object anchor probe

New render mode `object_anchors` draws candidate boxes for the same compact3
entry under several coordinate interpretations.  Use this for comparing rooms
where objects are close but still vertically or horizontally off.

## Known object/decor sprite hints

User-confirmed / screenshot-confirmed examples:

```text
AE000:004     player animation frames
AE000:005:0   rope top
AE000:006:0   rope middle long
AE000:007:0   rope middle short
AE000:008     rope bottom
AE000:022:12  spider animation start
AE000:039:0   ceiling button / switch, unpressed
AE000:041     laser trigger / red pudding-looking trigger
AE000:042:0   pressed ceiling button
AE000:044:0   diamond
AE000:047:0   horizontal moving platform
AE000:048:0   vertical moving platform
AE001:025:26  vase
```

## Still unknown / next work

- Exact compact3 section directory: the parser still scans canonical offsets
  (`0x23`, `0x44`, `0x47`) plus fallbacks.  The EXE likely has a room payload
  section directory or a more precise offset rule.
- Exact actor coordinate schema.  Actor entries are not just visual decorations;
  enemies such as the spider may be initialized from a different pass or use a
  different anchor/baseline than static decor.
- Trigger bindings: buttons, laser triggers and moving platform linkages are not
  decoded yet.
- Player start: player position is not necessarily in every room; for starting
  rooms it should be present in level or room metadata, but the exact field is
  still not confirmed.
