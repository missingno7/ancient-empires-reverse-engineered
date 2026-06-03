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

## Planned reuse

1. Decode the two font resources into the blob format above and expose a
   `BitmapFont.measure()` / `draw()` renderer in `ancient_empires.rendering`.
2. Rebuild the top menu bar and a generic dialog/list widget on that renderer,
   matching the original layout but allowing new entries.
3. Add a developer menu (cheats such as "switch to next level", room/level jump)
   as an extra dialog — gated behind a debug flag in `ae_game`.
