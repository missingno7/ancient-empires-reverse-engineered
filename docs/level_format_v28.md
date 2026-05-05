# Level format notes — v28 cleanup

This version is a cleanup/refactor, not a new speculative decoder.

## Removed legacy assumptions

The following old controls/paths were removed because later evidence showed they were compensating for earlier misinterpretations:

- `legacy crop left 2`
- `test +4,+4 align`
- runtime `tile anchor -4,-4` toggle
- brute-force payload scanners used for normal rendering
- renderer-side object-table guesses named `terrain_payload`, `payload_probe`, `object_anchors`

The terrain anchor is now a constant in `coordinates.py`, because it is a property of the 8px grid versus larger terrain sprites.

## Difficulty split

The two equal parts in each level resource are now labelled:

```text
part 0 = Explorer
part 1 = Expert
```

This matches gameplay observations: early levels are similar between the two parts, while later levels diverge much more.

## Room slots

Each difficulty part contains 13 fixed 1000-byte room records. Not every slot is necessarily an active playable room. Level 1 currently appears to use rooms 0..6; rooms 7..12 include blanks/placeholders or data that does not render like a normal room.

The editor still displays all 13 slots because the inactive slots may be useful for reverse engineering.

## Room payload

A room record layout is still:

```text
+0x000..0x001  preamble
+0x002..0x2AD  terrain 38×18
+0x2AE..0x3E7  trailing payload
```

The trailing payload is parsed as:

```text
trailing+0x00  ten 3-byte platform/control triplets
trailing+0x1E  EXE-style payload directory
```

The directory parser follows the current best reading of AEPROG:

1. length-prefixed control records,
2. compact3 section A,
3. count + 12-byte records,
4. compact3 section C,
5. compact3 visual table.

Only the main visual table is rendered as theme decorations by default. Section C is currently rendered as rotating laser crystals because that matches verified rooms. Control records are only rendered for confirmed cases such as buttons and one ant actor case.

## Rendering order

The normal `game` mode draws:

1. background wall texture,
2. terrain cells with anchor `(-4,-4)`,
3. rope cells from AE000 rope sprites,
4. moving platforms from platform triplets,
5. confirmed control-record sprites,
6. laser crystals from section C,
7. main visual compact3 objects/decorations.

## Current confirmed asset references

- player animation: `AE000:004`
- rope: `AE000:005..008`
- rotating crystal family: `AE000:019`
- ant enemy: `AE000:020:0`
- spider family: `AE000:022:12..15`
- ceiling button: `AE000:039:0`, pressed: `AE000:042:0`
- laser trigger / red “pudding”: `AE000:041`
- diamond: `AE000:044:0`
- horizontal platform: `AE000:047:0`
- vertical platform: `AE000:048:0`
- terrain banks: `AE001:021..024`
- theme decoration banks: `AE001:025..028`

Known theme decoration examples:

- theme 1 background tiles: `AE001:026:0..5`
- theme 1 picture: `AE001:026:20`
- theme 1 urns: `AE001:026:23`

## Current biggest risk

The biggest remaining source of wrong objects is the incomplete compact3 `code -> sprite` lookup. The current default assumes current theme bank `AE001:(25+theme):(code&0x3f)`, with a few confirmed global-object overrides isolated in `object_mapping.py`.
