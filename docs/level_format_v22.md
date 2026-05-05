# Level format notes v22 — EXE-derived payload structures

This build incorporates a static disassembly pass over `AEPROG.EXE` around the room render/update code.

## Confirmed room record layout

The v16 room record structure still holds:

```text
level resource AE001 #0..19
  two parts / pages, each 0x330c bytes

part:
  0x40 header
  13 room records * 1000 bytes
  4 byte footer

room record:
  +0x000..0x001  preamble / room metadata
  +0x002..0x2AD  terrain grid, 38 * 18 bytes
  +0x2AE..0x3E7  payload / room control data
```

Internally, the EXE appears to keep a pointer to the terrain start rather than to the record start. Therefore the payload offsets below are relative to `room.trailing`, i.e. to `terrain + 0x2AC`.

## Payload prefix: ten platform/control triplets

AEPROG loaded-image offset `0x25b3` iterates exactly ten 3-byte records starting at current-room terrain pointer `+0x2AC`.

```text
payload +0x00:
  10 * 3-byte records:
    byte 0 = flags/state/timer
    byte 1 = x_raw
    byte 2 = y_px
```

The EXE coordinate calculation doubles `x_raw` and applies a small left bias:

```text
x_px ~= x_raw * 2 - 4
y_px ~= y_raw
```

This is now used for moving platform rendering. `0x07` in the terrain grid is treated as invisible collision/support, not as the visible platform sprite.

## Visual compact3 object/decor tables

The room payload also contains count-prefixed compact tables:

```text
count
count * (x_raw, y_px, code)
```

Static code around `0x2bf7..0x2d9f` draws these as visual room objects/decorations:

```text
x_px = x_raw * 2
y_px = y_px
code >= 0x80: first visual pass through an EXE sprite pointer table
code <  0x80: later visual/control passes
```

Confirmed / useful offsets so far:

```text
payload +0x23  common in level 1 room 2
payload +0x44  level 2 room 0 page B, contains vase/button/spider/laser-trigger cluster
payload +0x47  observed in level 20 room 0 page A
```

Known manual mappings used by the renderer:

```text
code 0x1A -> AE001:025:26   vase
code 0x0E -> AE000:039:0    button / switch family
code 0x80 -> AE000:041:0    laser-trigger / red pudding-like trigger
code 0x8E -> AE000:044:0    diamond / artifact
code 0x02 -> AE000:022:*    enemy family, contextual; L2 room 0 page B uses spider frame 12
```

## Remaining unknowns

The EXE contains more section navigation helpers at `0x2a2d` and `0x2a70`. They walk a small directory/variable-length section system after the platform triplets. The current parser knows enough to find likely compact3 visual tables, but the full grammar is not finalized yet.

Still unresolved:

- exact section directory format after `payload +0x1E`;
- exact sprite pointer table at EXE data `0x72b2`;
- exact code-to-sprite mapping for all compact3 codes;
- actor vs decoration split for `code 0x02` and other reused low codes;
- trigger wiring: buttons, moving platforms, and door/opening effects.

## Practical implication for the editor

The renderer now has two debug modes useful for continuing the RE work:

- `terrain_objects`: best current visual reconstruction;
- `exe_sections`: overlays EXE-derived platform triplets and compact3 tables with labels.

Use `exe_sections` when validating a screenshot against payload bytes.
