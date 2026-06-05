# Menu HUD, dialogs and the bitmap-font system

This documents how the original game draws its text chrome — the top menu bar
(`Help F1 / File F2 / Options F3`), the dialog windows (`Hall of Fame`, `Start
New Game`, `Esc to Go Back`, …) and the bitmap fonts behind them.  The goal is a
faithful-but-extensible reimplementation: a shared text renderer that can drive
both an original-looking menu and new custom features (e.g. a developer cheat
menu such as "switch to next level").

## Background rendering

The play field is **not** a flat colour.  The room draw at `0x2bc0` blits a
backdrop image resource `0x656c(0x101e + region)` = **AE001 resource
`30 + region`** at the view origin over a blue clear, then lays terrain and
objects on top.  The clear colour is **VGA index 1 = RGB(0, 0, 170)** (the
backdrop's transparent palette index).

Resource layout of the AE001 backdrops (rtype `0x47`, ~304x131 each):

- `030..033` — region 0..3
- `034` is a map, `035..062` are level scripts (rtype `0x68`) — **not** backdrops
- `063..114` — regions 33..84

`region` comes from the level data (`byte & 0x7f`), set by `load_room` at
`0x4517` from `DS:4374`.  **The exact byte offset that yields the region is not
yet pinned** — naive guesses (level payload `[0]`/`[2]`) select the wrong
resource (e.g. AE001:030, which is a different area's backdrop and whose black
fill hides the pattern).  Until the region byte is confirmed, `game_screen` only
fixes the clear colour (`BACKGROUND_COLOR` = index 1 blue) and leaves the room's
existing background; `GraphicsSet.room_backdrop(region)` and
`RenderOptions.draw_background` are in place for when the selector is resolved.
(The earlier solid index-137 blue was also wrong — that is the brighter
HUD-frame blue, not the play-field clear.)

## Buttons / levers: real trigger path

Controls are **not** toggled by the player record-overlap our `ControlInteractor`
approximates.  The control records live at `DS:bfc0` (`[+1]`=command, `[+2]`=x,
`[+3]`=y, `[+4]`=pressed); `0x32fa` toggles a control's terrain effect (XOR bit
`0x10`) and `0x338a` activates one (flips `[+4]`, plays SFX `0x167`).  The
*trigger* is the **actor VM**: `0x4b0c` tests the player's box against each actor
in the `0xb3ae` table, and a triggered actor runs a script whose opcode at
`0x4cfa` calls `0x2a2d`/`0x338a` to activate the linked control by index.  So a
floor lever is a trigger-zone **actor**, and its hitbox is the actor's
frame-based bounds — not the control record's position.

There are two activation paths, both now in `RoomSimulation` (see
`docs/gameplay_reverse_engineering.md`):

- **Walk-onto-button** — the player loop probes the object box list (`0x1d89a`)
  and `0x338a`-toggles a button (command 0/1) when the probed code changes.
  Ported as `apply_player_object_interaction()`.
- **Actor-VM trigger** — opcode `0x08` (already in `step()`) toggles a control
  for command-2 levers / scripted triggers, gated by player-position conditions.

The standalone `ControlInteractor` overlap heuristic was removed in favour of
these real paths.

## Bitmap-font format

Fonts are ordinary compressed resources loaded through `0x68aa` -> `0x656c`
(resource fetch) -> `0xf348` (decompress).  `0x21a9` loads font resources 0 and
1 at startup.  A decoded font is a flat blob:

```
+0  unused
+1  glyph_count - 1            ; byte
+2  line_height                ; byte (pixels; stored to DS:c0e8)
+3  width[count]               ; per-glyph advance width, indexed by char code
    offset_lo[count]           ; low byte of each glyph's bitmap offset
    offset_hi[count]           ; high byte of each glyph's bitmap offset
    bitmap[...]                ; packed 1bpp glyph rows
```

`0x6ca6` `select_font(index)` resolves the font header from the table at
`DS:[index*4 - 0x3f2a]` and caches the derived pointers:

| Global     | Meaning                              |
|------------|--------------------------------------|
| `DS:c0ea`  | current font index                   |
| `DS:c0e0`  | font segment                         |
| `DS:c0e4`  | width table pointer                  |
| `DS:c0e6`  | offset-high table pointer            |
| `DS:c0e2`  | offset-low table pointer             |
| `DS:c0de`  | glyph bitmap base                    |
| `DS:c0e8`  | line height                          |

## Text routines

- `0x6cf6` `measure_string(str)` — sums `width[char]` per line and returns the
  widest line.  Used to centre text (the glyph blitter centres around x=160,
  i.e. `0xa0 - width/2`).
- `0x6d3c` `draw_string(x, y, str)` — walks a NUL-terminated string; `0x0a`/`0x0d`
  start a new line (`y += line_height`, x reset to the start); every other byte
  calls the glyph blitter and advances x by `width[char]`.
- `0x17a4` glyph blitter — looks up `width`, `offset` and bitmap for one char and
  ORs its 1bpp rows into the planar VGA buffer using the current text colour
  register `DS:40c8`.  Newlines in `draw_string` make it a multi-line box renderer.

So a full text layer needs only: the decoded font blob, a text-colour selector
(`DS:40c8`), `measure_string` for centring, and `draw_string` for placement.

## Menu bar and dialogs

The menu labels live as plain strings in the data segment (`Help   F1` at
`DS:0dba`, `File   F2` at `DS:0e20`, `Options F3` at `DS:0ec3`) and the dialog
item lists are contiguous right after (`Hall of Fame`, `List of Players`,
`Return to Map Menu`, `Start New Game`, `Exit and Save`, `Esc`/` to Go Back`).
They are reached through far-pointer tables rather than immediate offsets, so the
menu/dialog dispatch reads an item list and renders each entry with
`draw_string`, drawing the window border separately and inverting the text
colour (`DS:40c8`) for the highlighted row.

Status: the font/text path above is fully traced and is the right foundation for
a reusable renderer.  The exact dialog-window border draw and the F1/F2/F3
menu-state machine still need to be walked before a pixel-perfect menu is built,
but a custom menu can already be layered on the recovered font renderer.

## Startup difficulty, map menu and new-user messages

The current `ae_game` shell jumps straight into level 1 Explorer room 0.  The
original goes through the text/menu system first:

1. A list dialog asks for difficulty: `Which Level of Difficulty?`.
   The runtime RAM dump contains the contiguous strings around physical
   `0x126f5`: title, explanatory body, then the two selectable rows
   `Explorer Level of Difficulty` and `Expert Level of Difficulty`.  Selecting
   Explorer/Expert maps directly to the level-part index (`0`/`1`).
2. The game shows the map menu before entering a cavern.  Resource loading at
   `0x56c6` loads resources `0x38` and `0x37` into `DS:bfe2` and `DS:bfe6`,
   calls `0x55c7` to build pointer tables, then draws the map/menu screen.
   `0x5708` prepares AE000 resource `0x35`, and `0x576a` calls `D5F9(0x35)`,
   so the map has its own AE000:049/050 PC-speaker/sound-card music pair.  The
   backing image is AE000:026, the visible map is AE000:028, AE000:029..032 are
   the normal region icons, AE000:033..036 are the completed variants, and
   AE000:037 is the red selector rectangle.  The map flow uses the same
   keyboard/menu helpers as dialogs:
   `0x5593` waits for keys, `0x6b1a` reads keyboard input, and the generic
   selectable-list engine lives at `0x7932` / `0x7964`.
3. Resource `0x34` is loaded by `0x55c7` into `DS:bfde`.  Its first nine offset
   entries are copied into a runtime pointer table; additional entries are
   filled from room-sized image records.  This resource participates in the map
   and menu-image composition, not the answer-puzzle symbol bank in AE001:034.
4. Resource `0x35` is loaded for the map/menu music and/or map-associated data:
   `0x5708` calls `D5BA(0x35)`, and `0x576a` calls `D5F9(0x35)` before drawing
   the map/menu screen.
5. Current capture alignment shows a 12px black margin at both the top and bottom of the screen. The port therefore composites AE000:026 at `(0,12)` and AE000:028 at `(5,15)`, with all four region icons/selector shifted down by the same amount.
6. The map menu draws several subimages/text chunks with `0x5321`, using offsets
   from `DS:bfe2` such as `+0x0344`, `+0x0498`, `+0x05fa`, and `+0x066c`.
   These calls line up with the visible map/cavern menu composition rather than
   ordinary gameplay rendering.
6. The in-game tutorial overlays are plain text strings in RAM after the game
   has loaded them.  The screenshot text for switches/tools appears around
   physical `0x72509` in the Spice86 memory dump.  Dialog title text
   `New User Message` appears around `0x1356a`, and the option prompt
   `The New User Messages... Do you want to see...` appears around `0x13096`.

Important resource distinction: AE001 resource `034` is already used by the
answer-puzzle renderer as a symbol bank, but the map/menu code above loads
resource `0x34` through the current active archive/resource context.  In the map
startup flow this appears to be AE000:034, whose decoded payload is a small
`0x47` image resource, while AE001:034 remains the large answer-symbol bank.
Keep the bank explicit when porting this.

High-level implementation target for `ae_game`:

- Add a startup scene before `GameWindow` begins ticking a level.
- Show the difficulty dialog and set `part_index` from its selected row.
- Show the map menu scene and let the player choose a cavern/region instead of
  always loading `project.levels[0]`.
- Track completed caverns; after all caverns in the four normal regions are
  completed, advance the map to the Ancient World region.
- Keep the existing native Tk developer menu as a debug convenience, but route
  normal player-facing level selection through the recovered map scene.

## Planned reuse

1. Done: `ancient_empires.rendering.bitmap_font.BitmapFont` decodes AE000 font resources 0/1 in the recovered blob format and exposes `measure()` / `draw()` / `draw_centered()`.
2. Done for startup difficulty: `DifficultyDialogRenderer` uses the recovered font and hard-matched DOS coordinates for the Explorer/Expert selection dialog. A fuller generic dialog/list widget can now be factored from it.
3. Add a developer menu (cheats such as "switch to next level", room/level jump)
   as an extra dialog — gated behind a debug flag in `ae_game`.
