# Level format notes — v30 cleanup

This build is a cleanup on top of v29. The main point is to stop treating every
payload section as the same kind of object list.

## Confirmed / stronger assumptions

### Difficulty parts

Each AE001 level resource contains two equal parts:

- part 0 = Explorer
- part 1 = Expert

They are not animation pages. They are difficulty variants. Early caverns are
similar between them; later caverns can be substantially different.

### Room record

Each part has 13 fixed 1000-byte records:

```text
+0x000..0x001  room metadata/preamble
+0x002..0x2AD  terrain grid, 38×18 bytes
+0x2AE..0x3E7  room payload, 314 bytes
```

Not every fixed record is a real used room. Early levels often use fewer than 13
rooms; unused records may be empty or non-room data. The UI labels records as
`room`, `empty`, or `data?` but keeps them browsable.

### Render order from EXE

The EXE's room renderer draws the main compact3 visual table in two passes:

1. entries with `code >= 0x80` are drawn before the terrain pass;
2. terrain / special terrain markers are drawn;
3. entries with `code < 0x80` are drawn after terrain.

This matters for wall decorations versus foreground objects.

### Payload sections

The room payload starts with 10 platform/control triplets, followed by an
EXE-style directory and several sections:

```text
trailing +0x00  10 × 3-byte platform/control triplets
trailing +0x1E  directory / length-prefixed records / compact3 sections
```

Platform triplet orientation in this build:

- `0x80` and `0xA0` family: vertical platform
- `0x40` and `0x60` family: horizontal platform

The visible platform sprites are objects from the payload; terrain code `0x07`
is treated as invisible collision/support, not as a platform sprite.

### Puzzle buttons and symbols

Section A compact3 entries are now rendered as the puzzle-symbol buttons:

- button base: `AE000:009:0`
- symbol: `AE000:(010 + code):0`
- progress block / symbol cube: `AE000:017:0` from the 12-byte section

This explains the level 9 Expert room 0 hanging `I / II / ...` markers better
than the previous blank-medallion rendering.

### Known remaining gaps

- Actor start positions and dynamic actors are still incomplete. Player start,
  spider, ant, etc. probably use the control-record logic more deeply than the
  current viewer models.
- Some object coordinates still need per-section anchor refinement.
- The EXE lookup table for all compact3 `code -> sprite` mappings is not fully
  reconstructed yet. Known special cases live in `ae_editor/object_mapping.py`.
