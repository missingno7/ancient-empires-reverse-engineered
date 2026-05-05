# Level format notes v26 — EXE payload pass

This version is a step-back cleanup after comparing the editor with the full
AEPROG.EXE disassembly.

## Confirmed / stronger observations

### Current room pointer

The game uses a pointer at `DS:BFBC` as the current room terrain pointer. This
appears to point at the first byte of the 38×18 terrain grid, not at the two
unknown bytes before it in the 1000-byte record.

Therefore the editor's layout remains:

```text
room record
  +0x000..0x001  preamble / unknown
  +0x002..0x2AD  terrain 38×18 bytes
  +0x2AE..0x3E7  payload/trailing data
```

When translated to the editor's `Room.trailing`, EXE offsets become:

```text
EXE current_room + 0x2AC == trailing + 0x00   platform/control triplets
EXE current_room + 0x2CA == trailing + 0x1E   payload directory-ish block
```

### Platform/control triplets

The routine around `0x25B3` iterates exactly ten 3-byte records at
`current_room + 0x2AC`. It tests the low nibble of byte 0, decrements it as a
state/timer, uses bit `0x20` and `0x80` as behavior/orientation flags, and
writes `0x07` / `0x00` back into the terrain grid as collision support while
moving the visible platform.

This supports the current editor behavior:

* terrain code `0x07` is collision/support, not the platform sprite itself;
* visible moving platforms are payload-driven;
* the triplet layout is `(flags/state, x_raw, y_raw)`;
* `x_raw` is doubled before use; the editor keeps the current `x*2-4` bias as a
  working approximation.

### Payload directory at trailing +0x1E

The routines around `0x2A2D` / `0x2A70` do not scan arbitrary offsets. They treat
`current_room + 0x2CA` as a small directory/header and then walk variable-length
records.

Current model:

```text
base = trailing + 0x1E
base[0]               participates in a 4-byte directory area size
base[base[0]*4 + 1]   selected visual/section index
base + base[0]*4 + 2  start of length-prefixed control records
```

Skipping `selected_index` length-prefixed records reaches a candidate visual
`compact3` table. In many rooms this selected table is empty and the visible
compact3 table appears a few bytes later after zero padding. That is why v26
keeps a conservative fallback scan, but no longer treats all plausible byte
triplets as equal.

### compact3 rendering order

The routine around `0x2BF7` reads a count-prefixed `(x, y, code)` table. It draws
entries with `code >= 0x80` first, then terrain/foreground specials, then draws
entries with `code < 0x80`. This matters for background vs foreground ordering.

Coordinates from this routine:

```text
screen_x = x_raw * 2
screen_y = y_raw + screen_buffer_offset
sprite_index = code & 0x3F
sprite_flags = code & 0x40
```

The editor strips the screen buffer offset and uses `x_raw * 2` as the primary
pixel coordinate, with per-sprite anchors still under research.

## Cleanup in v26

* Added `parse_exe_payload_directory()` and explicit length-prefixed control
  records.
* `parse_visual_compact3_tables()` now prefers the EXE-derived table and only
  uses a narrower fallback when the EXE-selected table is empty.
* Removed the old typed6 switch-drawing hack from the renderer. Buttons,
  vases, enemies and similar visible objects should come from visual compact3
  tables; length-prefixed control records remain visible/debug data until their
  logic is mapped.
* Kept terrain tile anchor `(-4, -4)` from v25; this still matches the observed
  block overlap behavior.

## Remaining uncertain pieces

* Exact semantics of each length-prefixed control record. The records clearly
  connect to switches/platforms/triggers, but their fields are not fully named.
* Exact sprite pointer table used by `code & 0x3F`. The editor still uses a
  manual logical-code-to-sprite mapping for known objects.
* Actor coordinates and player start. Some enemy/player-like objects are not in
  the same visual table or use different anchors.
* The meaning of the directory count and its 4-byte directory area. It is not
  yet clear whether those four-byte entries are offsets, states, or per-page
  references.
