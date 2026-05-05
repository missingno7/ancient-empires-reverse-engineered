# Level format notes - v34 visual-table cleanup

This build is a small cleanup after the v33 conveyor-tile discovery.

## Confirmed / improved

### Conveyor belts are terrain special tiles

Belts are not payload/control sprites. They are stored in the 38x18 terrain grid,
like ropes. The visible strip is composed from AE000:038 left/middle/right pieces.

Current known tile codes:

```text
0x0F -> grey conveyor, AE000:038 frame 0 pieces 0,1,2
0x1F -> teal conveyor, AE000:038 frame 0 pieces 12,13,14
```

The visible right cap extends one 8px cell beyond the final terrain marker. v34
therefore composes width `(run_length + 1) * 8`, fixing the previous one-cell
short belt endings.

### Visual compact3 code bit 0x40 mirrors theme decorations

Level 14 Expert room 2 contains paired statue/lion decorations as codes `0x05`
and `0x45`. Both refer to the same theme sprite index `code & 0x3f == 5`, but
`0x45` must be horizontally flipped. v34 adds `SpriteRef.flip_h` and treats bit
`0x40` as a horizontal mirror flag for default theme visuals.

### compact3 code 0x02 is not a global actor id

Older builds treated visual compact3 code `0x02` as a snake/crawler/spider actor.
That was a bad global rule. Some rooms use code `0x02` as ordinary theme visual
art, for example wall cracks/decorations. Actors should come from their own
control/actor records; the main visual table now falls back to AE001:(25+theme)
for code `0x02`.

## Still open

* Exact actor records for player spawn, spiders, ants, etc.
* Exact trigger/link fields for buttons and puzzle controls.
* Whether bit `0x40` has other meanings for non-theme/global objects. For now it
  is only applied to the default theme visual path.
