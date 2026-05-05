# Level format notes - v32 conveyor cleanup

This build deliberately uses v31 as the baseline for background/theme decorations,
because that version matched screenshots better than later experimental directory
rendering.

## Confirmed cleanup

### Terrain and theme art

Terrain still uses:

- room grid: 38 × 18 bytes
- cell size: 8 × 8 pixels
- terrain sprite anchor: `(-4, -4)`
- theme terrain banks: `AE001:021..024`
- theme decoration banks: `AE001:025..028`

The renderer no longer exposes legacy alignment/crop test switches.

### Difficulty pages

The two level parts are now named according to game behavior:

- part 0 = Explorer
- part 1 = Expert

They are not animation pages. Expert can have different room layout and object
placement, especially in later levels.

### Conveyors / belts

Conveyors are handled as their own control-object family, not as a direct sprite
id and not as terrain code.

Asset bank `AE000:038` is organized as segmented animation strips:

- grey frames: indexes `0..11`
- teal frames: indexes `12..23`
- each frame is `left, middle, right`

For static preview v32 draws frame 0 only:

- grey: `AE000:038:0,1,2`
- teal: `AE000:038:12,13,14`

Known control args currently interpreted as conveyors:

- `arg_b 0x10` / `0x12` -> teal conveyor
- `arg_b 0x11` / `0x13` -> grey conveyor

The exact width and exact command coordinate transform are still unresolved.  The
implementation keeps them centralized in `ae_editor/conveyors.py` and
`ae_editor/coordinates.py` so future EXE work can replace the guesses cleanly.

## Important unresolved parts

- Exact conveyor strip length field.
- Exact platform coordinate model.
- Actor layer: player spawn, spiders, ants and other enemies are not fully decoded.
- Trigger links: switches, laser crystals and puzzle state are visible but not yet
  semantically connected.
- Whether any conveyor information is duplicated in terrain tiles. Current evidence
  points to control records for visible belts, while terrain stores collision/support.

## Code organization

- `room_payload.py` parses room payload sections.
- `conveyors.py` knows how to compose AE000:038 strips.
- `coordinates.py` centralizes coordinate conversions.
- `object_mapping.py` contains the still-partial `code -> sprite` mapping.
- `renderer.py` should stay boring: it wires parsed structures to rendering helpers.
