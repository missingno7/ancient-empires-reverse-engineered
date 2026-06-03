# Gameplay reverse engineering

Playable gameplay is the major missing part of the source port. The repository
already has asset decoding, room rendering, actor VM stepping, controls,
platforms, puzzle state and audio. `run_game.py` now opens the first recovered
gameplay screen: level 1, Explorer, room 0, the player, ordinary walking,
gravity, normal jump and the `AE000:063` HUD. The following systems still need
to be reconstructed from the original executable before it becomes a complete
playable game.

## Primary source

- `Decompile notes/AEPROG_full_disasm.asm` — full disassembly and the source of
  truth for runtime behavior.
- `Decompile notes/AEPROG_decompilation_notes.md` — startup, DOS services,
  keyboard/timer handling and initial C-like reconstruction notes.
- `Decompile notes/AEPROG_6200_6660.asm` — focused disassembly slice.

## Recovered first-screen presentation

- `0x6FCA` loads resource `0x3F` (`AE000:063`) for the HUD.
- `0x6FDA` blits HUD sprite 0 at `(6, 162)`.
- `0x7202` draws collected artifact-piece segments using `AE000:063:1`,
  starting at `(16, 176)` and advancing 18 px for each piece.
- `0x7298` blits selected tool sprites 3..5 at `(152, 166)`.
- `0x7417` blits region sprites 11..15 at `(244, 175)`.
- `0x7443` blits cavern sprites 16..19 at `(244 + cavern*16, 186)`.
- `0x471A..0x473C` initializes player runtime X/Y from header bytes
  `0x03..0x04`; Explorer player frames decode as `AE000:004`.
- `0x3CC -> 0x1A98` is a transparent top-left blit. Player placement still
  passes through the offscreen room buffer mapping documented in
  `reverse_engineering_notes.md`.

Most HUD labels are pixels in `AE000:063`, not font text. Text-driven gameplay
UI remains intentionally absent until the game font/text path is recovered.

The game does have a bitmap font system. `0x21A9` loads font resources 0 and 1
through `0x68AA`, `0x6CA6` selects a font, `0x6D3C` walks a zero-terminated
string, and `0x17A4` draws each glyph from width/offset/bitmap tables. The exact
archive mapping and which font is active for each gameplay text call still need
to be confirmed before this is exposed as a shared renderer.

## Player movement trace

The main player loop starts at `0x3A75`. It polls the BIOS keyboard wrappers at
`0x6B4A/0x6B1A`, then updates these core state words:

- `DS:0736` player X
- `DS:0738` player Y
- `DS:073A` facing direction
- `DS:072E` animation frame
- `DS:0730` jump counter
- `DS:0734` horizontal movement amount

The horizontal branches at `0x3DC1..0x3E60` move by `DS:0734`, normally 4
pixels, after collision query `0x1F91`. The grounded jump branch at
`0x410C..0x4137` sets jump counter 5, frame 9 and plays SFX `0x0C`. The
alternate branch at `0x40B3..0x40D8` sets jump counter 8 and plays SFX `0x10`.
`DS:0740` is the jump delta table; normal jump consumes `8, 8, 8, 4, 2` pixels.
`0x1F17` ORs a horizontal tile span and `0x1F91` ORs a vertical tile span.
Both routines derive their cell *count* from the un-offset coordinate
(`cap - x/8 + 1`) but index from the border-shifted start (`x/8 - 1`,
`y/8 - 2`), so the last cell carries the same border shift. The Python port
must apply that shift to the span end too; otherwise the vertical wall probe
bleeds two rows past the body into the floor and blocks all walking.

Live enemies are drawn each frame from the actor VM positions (`0x4ef8`,
buffer base `0xb8`). `GameScreenRenderer` suppresses the static record pass and
blits each active simulation actor through `RoomRenderer.actor_sprite`.

The keyboard IRQ handler around `0x69F5` maps scan code `0x4B` to left,
`0x4D` to right and `0x48` to the shared action/jump state. Home and Page Up
set diagonal movement plus action. `0x3AA5` schedules the next player loop
after `0x18` master timer ticks.

The ladder branch at `0x3e60..0x3f85` handles climbing. With up held it probes
the ladder column at `x+0x10-facing*4` via `0x1F91`; the first grab snaps the
player onto the ladder centre, then it ascends 4 or 2 pixels per tick. With down
held and already on a ladder (`0x3f41`) it descends 4 pixels until the ladder
ends. Climb frames alternate `0x14/0x15`, `move_amount` becomes 8 and the
`or si,si` test at `0x3f85` makes climbing bypass the jump and gravity branches.

`ancient_empires.engine.player.PlayerController` implements the verified
room-local slice: ordinary left/right walking, frames 0..11, gravity, floor
snapping, normal jump and ladder climbing against the Simulation runtime
collision tiles.

## Room transitions

Screen-edge transitions are recovered at `0x4240..0x4372`. The current room is
`DS:bfba`; four 10-byte link arrays (`0x438c` left, `0x4396` right, `0x43a0` up,
`0x43aa` down, indexed by room, 1-based, 0 = none) decide where each edge leads.
Crossing an edge with a link swaps rooms and re-enters from the opposite side
(`x=0x120` from the left, `x=0` from the right, `y=0x90` from the top, `y=0` from
the bottom); without a link the player is clamped at the boundary. The Python
port is `ancient_empires.engine.transitions.resolve_room_edge`, fed by the
existing `room_transition_links`, and wired through `ae_game` `_change_room`.

The original keeps every room's actors/controls in one persistent table and only
re-initialises a room the first time it is entered (`load_room` at `0x4517`
returns early when `DS:073c` already equals the requested room).  Revisiting a
room therefore resumes its paused state rather than restarting.  `ae_game` mirrors
this by caching one `RoomSimulation` per room (`_rooms`) instead of rebuilding it
on every transition.

## Buttons, switches and levers

Control records (`control_commands`) carry a command byte — 0 ceiling button,
1 floor button, 2 lever — drawn through the shared object anchor at `0x2f10`
(buffer x = `x_raw*2`, y = `y_raw`, the player's coordinate space). The pressed
sprite is selected by the live record flag (`0x9b6e` vs `0x9ae0`).
There are two real activation paths, both now in `RoomSimulation` (the standalone
`ControlInteractor` heuristic was removed):

1. **Walk-onto-button** (`0x3b05`/`0x3c50`): each frame the player loop probes the
   object box list via `0x1d89a` with the player body box (`x=X/2+1`, `y=Y+1`,
   `w=14`, `h=39`); control records sit in that list with code `index+8`. When the
   probed code *changes* (debounced), `0x338a` toggles the control — but only for
   buttons (command 0/1). `RoomSimulation.apply_player_object_interaction()` ports
   this; `ae_game` calls it after `set_player_position`.
2. **Actor-VM trigger** (`0x4cfa`): a trigger-zone actor whose script reaches
   opcode `0x08` calls `0x338a` for a control index, gated by the player-position
   condition opcodes `0x17..0x1A`. This already runs inside `RoomSimulation.step()`.

Command-2 levers are deliberately excluded from the walk path in the EXE
(`0x3c67`) and rely on path 2. The controls literally on the floor are the
command-1 floor buttons (y≈144), which path 1 now activates by walking over.

## Tools (Enter to change, Space to use)

The selected tool is `DS:0b7e` (0..2), drawn as AE000:063 sprite `3 + tool`:

| Tool | Index | HUD sprite | Space action |
|------|-------|-----------|--------------|
| Flashlight / laser | 0 | AE000:063:3 | fire laser (`0x5a3b`), SFX `0x14` |
| Jumping boots | 1 | AE000:063:4 | high jump, SFX `0x10` |
| Immortality | 2 | AE000:063:5 | temporary invulnerability |

- **Enter** (key `0x0d`) calls `0x727d`: `inc DS:0b7e`, wrap at 3, redraw the HUD
  tool sprite at (152, 166).  `PlayerController` cycles `state.tool` once per
  keypress.
- **Space** activates the current tool.  `0x7277` returns the selected tool and
  the player loop dispatches on it.
- **Boots** (`0x408a`): when grounded with the boots tool, Space sets jump
  counter **8** (rises ~48 px via `JUMP_DELTAS[8..1]`), double the normal up-jump
  counter 5 (~24 px), and plays SFX `0x10`.  Implemented and tick-accurate.
- **Flashlight** (`0x5a3b`): Space starts the laser only when the active flag
  `DS:08fe` is clear; otherwise the game plays blocked-action SFX `0x17`
  (`0x4214..0x422c`).  `0x5a3b` seeds two `0x18`-word coordinate arrays
  (`DS:c050..c07f` / `DS:c080..c0af`) with `(player_x+0x10, player_y+4)`, sets
  ring index `DS:c04e = 0x17`, direction row `DS:c0b8` (`3` right, `9` left),
  inactive-tail countdown `DS:c0c0 = 0x18`, and raises `DS:08fe = 1`.  It does
  **not** create an instant full-room beam, and `DS:c0c0` is not a range limit.

  The updater (`0x5ac3`) advances only eight 1-pixel substeps per tick through
  the 24-slot coordinate ring, so the visible laser is a short **1-pixel**
  yellow line that grows and moves through space.  While `SI != 0`, `DS:c0c0`
  is not decremented; it only counts down at `0x5d80` after the head has died,
  so range is effectively limited by solid terrain, room edge, or collision, not
  by the initial `0x18` value.  It checks room edges every pixel, but checks
  solid terrain only when the 1-pixel head crosses an 8-pixel tile boundary;
  it activates command-2 **jello/levers** through the `0x5c2f..0x5c67`
  object-probe path using the registered command-2 object box
  (`8` raw-X units by `16` pixels).  The jello probe
  is allowed to fire at the sampled point before a solid-tile boundary kill at
  that same point, which is important for beams reflected back into a sensor
  from the opposite side.  The object probe converts the full-pixel laser X to
  raw-X space with the same `x >> 1` shift for both left- and right-moving
  beams.  It can also freeze actors during the actor pass.  That path sets
  one pending trigger (`DS:c0be`) and clears `SI`, so a single moving beam toggles
  a jello/lever only once; the visible historical trail must not retrigger it on
  later ticks.  The freeze
  check at `0x4c7a` copies actor byte `[di+0x9]` into freeze timer `[di+0xa]`.
  Records with `[di+0x9] == 0` therefore do not stop; this matches
  projectile/secondary records such as fireballs, energy orbs and pill
  projectiles.  A frozen actor skips its script and counts down at
  `0x4b39`/`0x4b70`.  Jello light-sensors / reflectors (object codes
  `0x30-0x4f`) **reflect** the beam via the 12-way direction rows at `DS:0900`.
  The collision path copies the reflector compact3 bytes, masks the runtime
  frame with `0x1f` (`DS:c0c2`), then `0x5f3c` returns one of three reflector
  classes.  The follow-up formulas are `new_dir = frame - old_dir`,
  `frame - old_dir - 8`, or `frame - old_dir + 8`, normalized back into
  `0..11`, and play hit/reflect SFX `0x0f` (`0x5c69..0x5d7c`).  The object
  collision/classification branch is only entered when the local substep counter
  satisfies `(counter & 3) == 0` (`0x5c07`), so the triangular face is sampled at
  the same 4-pixel cadence as the original instead of every pixel along the
  entering edge.  Reflection sets `DS:c0b6` as a collision latch so the beam
  does not repeatedly reclassify the same reflector while still inside its
  object box; the latch is cleared after leaving that reflector, so the same
  beam can reflect from later reflectors.  It also keeps `DS:c0b0`, the
  `DS:0900` dither-table phase, instead of resetting phase after reflection.
  `0x5f3c`
  does not reflect from the whole rectangular object box: it subtracts the
  raw section-C reflector anchor (`local_x = laser_x - x_raw*2`,
  `local_y = laser_y - y`), indexes the current 30x30 packed 4bpp sprite
  nibble, and only specific logical colours return classes.  In the normal branch logical
  colours `2/3/4` map to classes `1/2/3`; the alternate branch maps
  `0x0b/0x09/0x08` to the same classes.  This is why the crystal behaves as a
  triangular reflector rather than a square mirror.  The object-list box is
  still 0x0f raw-x units by 0x1e pixels (`0x6036`), i.e. a 30x30 broad-phase
  footprint; transparent/background pixels inside that box return class 0 and
  do not deflect.

  Reflector orientation uses only the low five bits (`code & 0x1f`), not
  `0x3f`.  Bit `0x80` marks self-rotating reflectors (`0x60d2`), bit `0x40`
  reverses the step direction, and controlled reflectors advance one frame per
  button/switch trigger via the targeted `R0..R15` command bytes (`0x6181`).
  Self-rotation is intentionally slow: `0x60a9` returns immediately while
  `DS:08fe` says a laser is active, otherwise it decrements `DS:0a20`; only
  when that counter reaches zero does it reset it to `10` and advance all
  `0x80` reflectors by one frame.

  Ported: `RoomSimulation.fire_laser`/`_step_laser` now uses the 24-slot moving
  trail and cooldown instead of an instant beam, with wall stop, lever trip,
  actor freeze from each actor record's byte `0x09`, one-shot jello/lever
  triggering from the moving head, projectile exclusion when
  that byte is zero, 1-pixel yellow-line render, runtime reflector rotation
  every ten non-laser ticks, low-five-bit reflector frames, raw-anchor 30x30
  reflector broad-phase plus 4-pixel-cadence triangular sprite-nibble face reflection, unlimited
  moving range until wall/edge, and reflector deflection into 12-way directions without resetting the dither phase.  The preview tests all head
  substep positions from the current tick for freezing so the Python simulation
  does not miss sprites between 8-px tick advances.

- **Immortality** uses are limited to 4 per level (`DS:0b80`, shown by the
  overlay AE000:063:6..10 for counts 0..4); activating decrements the count via
  `0x7313`, sets the invulnerability timer `DS:072c = 0x3a`, and plays SFX `0x11`
  when the count is already 0.  Immortality is recovered in the ASM but not yet
  ported.

## Missing engine systems

1. Main game state machine and level/room lifecycle. (Edge-based room
   transitions are recovered; doorway exit-zones at `0x3cc8` are not yet.)
2. Remaining keyboard actions and tool use.
3. Special jump (counter 8 via scancode `0x20`), conveyors and other player
   movement modes. (Ladder climbing is recovered.)
4. Terrain/object collision and hazard response.
5. Room transition rules, camera behavior and spawn placement.
6. Collectibles, inventory/progress, lives, damage and completion conditions.
7. Full actor interaction with the player and projectiles.
8. Exact moving-platform motion and player/platform coupling.
9. Timing integration across player, actor VM, audio and presentation.

## Workflow

Recover one rule at a time into `ancient_empires.engine`, add a focused fixture
or regression test, then expose it through both the editor Simulation tab and
the game application. Keep asset/table extraction in `game_data`; keep input and
presentation in `ae_game`.

Keep extending `PlayerController` only from executable evidence. In particular,
do not approximate conveyors, hazards or room transitions.
