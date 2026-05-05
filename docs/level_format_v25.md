# Level format / renderer notes v25: terrain sprite anchors

This build fixes a long-standing visual alignment problem in the terrain renderer.

## Aha moment

The logical terrain grid is still `38 × 18` cells with an 8 px cell pitch, but the visible terrain sprites in the terrain banks are **not 8×8 bitmaps**.  The normal block/corner sprites in `AE001:021..024` are typically around `18×17` pixels and are meant to overlap neighbouring cells.

Earlier builds blitted terrain sprites at the cell top-left:

```text
x_px = cell_x * 8
y_px = cell_y * 8
```

That makes the foreground blocks look slightly shifted down/right compared with the background wall and with in-game screenshots.  The block art is effectively anchored about half a cell up/left.

The v25 renderer therefore uses this default terrain anchor:

```text
x_px = cell_x * 8 - 4
y_px = cell_y * 8 - 4
```

This applies only to normal terrain sprites from the terrain bank.  The background wallpaper is still tiled at `(0,0)`, and special object sprites from payload tables keep their own coordinate model.

## GUI controls

The GUI now has a `tile anchor -4,-4` checkbox.  It is enabled by default.  Disable it to compare against the old top-left blit behaviour.

The older `test +4,+4 align` checkbox is still present, but it is a global viewport experiment and should not be confused with the terrain sprite anchor fix.

## Current model

Known layers are now interpreted as:

1. background wall image from the current terrain bank,
2. terrain grid: logical codes mapped to overlapping terrain sprites with `(-4,-4)` terrain anchor,
3. special terrain codes such as rope and invisible collision/support,
4. payload objects/decorations/triggers with their own still-researched coordinate anchors.

## Important caution

If a renderer rule starts becoming very room-specific, it is probably masking a bad lower-level interpretation.  v25 moves the obvious alignment fix into a single terrain anchor instead of adding per-tile or per-room hacks.
