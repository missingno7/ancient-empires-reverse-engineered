# Ancient Empires level format notes - v29 cleanup

This build is based on the v28 cleanup plus another pass over the EXE-derived
room payload model and screenshot comparison.

## Stable model

* `AE001.DAT` resources `0..19` are the 20 caverns/levels.
* Each level resource contains two difficulty variants:
  * part 0 = Explorer
  * part 1 = Expert
* Each variant contains 13 fixed 1000-byte room records.
* A room record layout is currently interpreted as:

```text
+0x000..0x001  room preamble / metadata
+0x002..0x2AD  terrain grid, 38 x 18 bytes
+0x2AE..0x3E7  trailing payload, 314 bytes
```

The 13 fixed records are not guaranteed to all be playable rooms. Early levels
appear to use only the first several rooms; later records can be empty,
placeholder, or non-room data. The GUI now labels rooms as `room`, `empty`, or
`data?` using a conservative heuristic instead of pretending all 13 records are
normal rooms.

## Renderer cleanup

Removed old experimental UI toggles and implicit hacks from previous builds:

* legacy crop-left-2 model
* test `+4,+4` global align
* user-facing terrain-anchor toggles
* random compact3 brute-force scanning

Terrain now always uses the confirmed 8x8 grid with a fixed sprite anchor
`(-4,-4)` for overlapping terrain sprites.

## Payload sections

The room payload is treated as several separate sections:

```text
trailing +0x00  ten 3-byte platform/control triplets
trailing +0x1E  EXE-style payload directory and variable sections
```

The parser then exposes:

* platform/control triplets
* length-prefixed control records
* `section_a` compact3 table
* record12 section
* `section_c` compact3 table, currently matching laser crystal candidates in
  known rooms
* visual compact3 table, currently matching theme decor/background sprites

v29 starts rendering `section_a` separately. Level 9 / Expert / Room 0 shows that
this section contains the three hanging round markers visible in the game. This
was previously ignored, which made that room look emptier than the real game.

## Coordinate fixes

Screenshot comparison showed that theme decorations in v27/v28 were slightly too
far right/down. The main visual compact3 transform is now globally adjusted a few
pixels up-left in `coordinates.py` instead of adding per-sprite hacks.

Rope cells are still terrain-special markers (`0x90..0xC0`), but their x-bias was
relaxed because screenshots show they should sit slightly farther right than the
v28 placement.

## Still unsolved

* Exact EXE lookup table for all `compact3 code -> sprite` mappings.
* Full actor/enemy system. Some actors appear in length-prefixed control records,
  but not all enemies are rendered yet.
* Exact platform coordinate/orientation rules in every cavern.
* Some section-specific coordinate transforms. `section_a`, visual decor,
  control records, and actors appear to use related but not identical anchors.

