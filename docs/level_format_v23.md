# Ancient Empires level format notes - v23 tile mapping correction

This build is mostly a cleanup/correction build.  A long-standing visual mismatch
was caused by treating some terrain bytes as direct sprite indexes or by using a
partially wrong lookup.

## Confirmed/strongly supported

### Terrain grid

Each room record still uses the v16 structure:

```text
room_record + 0x000..0x001  unknown room metadata
room_record + 0x002..0x2AD  38 x 18 terrain/control grid
room_record + 0x2AE..0x3E7  trailing payload/control/decor data
```

### Terrain byte is a logical code, not a raw sprite index

The renderer now has an explicit tile mapping table in:

```text
ae_editor/tile_mapping.py
```

Current best mapping for the normal terrain family:

```text
code 0 -> empty/background
code 1 -> AE001:021+theme : sprite 5
code 2 -> AE001:021+theme : sprite 6   <-- v23 fix
code 3 -> AE001:021+theme : sprite 7
code 4 -> AE001:021+theme : sprite 8
code 5 -> AE001:021+theme : sprite 9
code 6 -> AE001:021+theme : sprite 10
code 7 -> invisible solid/support/collision marker
```

The important user-observed correction was:

```text
dec 2 should render as AE001:021:6, not AE001:021:5
dec 5 should render as AE001:021:9
```

So the previous duplicate mapping `1 -> 5` and `2 -> 5` was wrong.

### `0x07` is not visible platform art

`0x07` should stay collision/support.  Visible moving-platform sprites are stored
in the room payload/control data and drawn on top from AE000 platform sprites.
Any attempt to classify a `0x07` run as horizontal/vertical/T-shaped platform was
probably a renderer hack trying to compensate for incomplete object parsing.

### Rope special codes

The rope is still special terrain/control data, drawn from AE000 sprites:

```text
0x90 -> rope top-ish marker, AE000:005
0xA0 -> rope middle, AE000:006
0xB0 -> short middle candidate, AE000:007
0xC0 -> bottom, AE000:008
0x80 -> continuation/filler marker
```

v23 applies a `-8 px` x-bias for rope sprites because the marker appears to be on
the right-hand cell of a 16px-wide rope blit.  This aligns the rope better in
level 1 room 1.

## Cleanup principle

When a renderer rule becomes complicated, assume the underlying interpretation is
wrong until proven otherwise.  v23 moves terrain lookup to a single module and
removes the idea that visible platforms can be inferred from terrain shape.

## Still unresolved

- exact EXE tile lookup table address
- exact room-payload object schemas and anchor rules
- actor/enemy Y coordinate anchoring
- trigger wiring between buttons, platforms, doors and lasers
- exact player spawn table
