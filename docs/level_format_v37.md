# Level format notes – v37 button/control cleanup

This build keeps the v34/v35 terrain and visual-decor interpretation, but
fixes one important regression introduced while trying to draw all buttons.

## Control-command bytes

Room control records are length-prefixed.  The first byte is **not** the object
type.  The body layout currently used by the editor is:

```text
raw[0] = length
body[0] = command
body[1] = x_raw
body[2] = y_raw
body[3] = arg_a / state / link data
body[4] = arg_b / link data, if present
body[5..] = extra link data, if present
```

The v36 heuristic `y >= 0x50 => floor switch` was wrong.  Verified rooms show
that ceiling buttons can have `y_raw = 0x68`, and that command/link bytes carry
more meaning than the absolute y value.

## Current button model

Observed from Level 1 Expert rooms 3 and 4:

```text
command 0, arg_b == 0x02  -> floor switch
command 0, arg_b == 0x41  -> pressed floor switch
command 0, otherwise      -> ceiling button
command 1                 -> floor switch / trigger metadata family
```

The `arg_*` bytes are still treated as trigger/platform link metadata, not as
sprite ids.  This is important for puzzles where one button moves one or more
platform triplets.

## Coordinate families

Control command visuals use different anchors:

```text
ceiling_button -> x_raw*2 - 12, y_raw - 46
floor_switch   -> x_raw*2 - 12, y_raw - 12
actor          -> still experimental
```

This is deliberately centralized in `ae_editor/coordinates.py` so future fixes
do not add room-specific hacks to the renderer.

## Room connectivity

The fixed 13 room records per difficulty are storage slots, not necessarily the
playable graph.  In Level 1, the verified playable graph appears to be rooms
0-4 linearly, with room 5 above room 4 and room 6 below room 4.  Later records
can be empty placeholders or non-room data-like records.  The viewer keeps them
browsable, but labels them as `room`, `empty`, or `data?` rather than assuming
all 13 are reachable rooms.
