# Level format notes v31

## Main cleanup

The important fix in this version is that room control records are truly
**length-prefixed**.  Previous builds accidentally used the first byte of each
record as the command/type.  That byte is only the length.  The real command
body starts at `raw[1:]`.

Example from level 14 / Expert / room 0:

```text
06 00 0F 58 00 11
```

Old interpretation:

```text
command = 06   # wrong, this is length
```

Current interpretation:

```text
length  = 06
command = 00
x_raw   = 0F
y_raw   = 58
arg_a   = 00
arg_b   = 11
```

This explains why some trigger ids looked like sprite ids.  The renderer now
wraps these records as `ControlCommand` and uses body bytes explicitly.

## Conveyors

`AE000:038` is now rendered from control commands where:

```text
command in {00, 01}
arg_b in {10, 11}
```

The art appears to be grouped as 3-sprite strips: left cap, repeated middle,
right cap.  Coordinate conversion is still approximate, but the implementation
is now isolated in `coordinates.control_xy(..., mode="conveyor")` and the
renderer no longer confuses conveyor trigger ids with generic compact3 visual
codes.

## Buttons and actors

Ceiling/floor buttons now use the command body too:

```text
command in {00, 01}
arg_b in {02, 03, 04, 40, 41}
```

Known actor-ish records use:

```text
command == 02
```

This is still only partially solved, but it is cleaner than v30 because command
parsing is no longer off by one byte.

## Still unresolved

* Exact conveyor length/endpoints.
* Exact actor lookup table for player start, spider, ant, etc.
* Exact per-command coordinate transforms; several command families likely have
  different anchors.
