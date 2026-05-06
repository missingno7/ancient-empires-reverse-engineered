# Level format notes - v40 actor table and trigger cleanup

This build keeps the v38 switch rule, but separates visible triggers, diamonds,
and runtime actors into their own data paths.

## Control command records

Room payload control records are length-prefixed. The first byte of the raw
record is **length**, not an object id. The command is `raw[1]`.

Current visual rules:

```text
command 0 -> ceiling button family, AE000:039 normal, AE000:042 pressed
command 1 -> floor switch family, AE000:040 normal, AE000:043 pressed
command 2 -> laser trigger / red jello family, AE000:041
```

For commands 0/1, `arg_b & 0x40` is treated as an initial pressed-state bit.
The lower bits are trigger/link metadata and must not be used as sprite ids.

## Laser trigger command 2

`command 2` goes through the visible trigger renderer in AEPROG.  Earlier
builds treated only the `0x10/0x11` metadata pair as laser jello and tried to
reinterpret other command-2 records as enemies.  Level 20 Expert room 0 disproves
that: its two trigger records use `arg_b` values `0x01` and `0x00`, yet they are
the two platform-linked laser triggers in the room.

```text
06 02 x y ... -> AE000:041 at roughly x*2-12, y-12
```

Do not map the main visual compact3 code `0x80` to `AE000:041`.  Level 2 room 0
has only one command-2 trigger in both Explorer and Expert; the old visual-code
special case produced a false second laser jello.

## Moving platform triplets

The ten three-byte records at room trailing offset `0x00` describe moving
platform starts/control state.  The high nibble of the first byte distinguishes
the visible sprite family:

```text
0x40/0x60 -> horizontal platform, AE000:047
0x80/0xa0 -> vertical platform, AE000:048
```

The x byte is doubled like other screen-space payload x coordinates, and the
stored point is an object anchor rather than bitmap top-left:

```text
x = x_raw * 2 - 12
y = y_raw - 12
```

## Diamonds / artifact slots

The draw loop around `0x2e36` checks six slots in globals
`DS:437a/4380/4386`.  If `room_id == current_room+1`, it draws `AE000:044`.
Because AEPROG copies the level-part blob with the two-byte preamble skipped,
these slots line up with editor header slices:

```text
room ids: header[0x08:0x0e]
x bytes:  header[0x0e:0x14]   -> x*2
y bytes:  header[0x14:0x1a]   -> y
```

Level 20 Expert room 0 confirms slot 5: `room+1=01, x=05, y=6e`, so the
diamond renders at `(10, 110)`.

For the static room preview these stored positions are sprite anchors, not
bitmap top-lefts.  The renderer applies the same `x-12, y-12` screen-space
anchor correction used by the actor table layer, then clips to the visible
38x18 tile viewport.

## Actor table

Enemies are stored in the actor table at difficulty-part offset `0x2754`, copied
to `DS:b3ae`.  The table starts with a count byte, then 0x20-byte records.
Important confirmed fields:

```text
record[0x01]       room index, zero-based
record[0x02..0x03] x word
record[0x04..0x05] y word
record[0x06]       global actor frame id
record[0x07]       frame variant / high frame byte
record[0x08]       hidden/start-state flag
record[0x09]       movement/update delay
record[0x0b..0x0c] frame/path bounds used by the update script
record[0x0d..0x0e] actor script offset
record[0x17..0x18] restart script offset
```

Normal room previews skip records with `record[0x08] != 0`, matching the game's
draw loop.  `payload_debug` still renders them faintly so difficulty-specific
spawn state remains inspectable.  Level 1 Explorer room 2 demonstrates this:
one snake is visible at `x=206,y=138`, while the second snake at `x=104,y=138`
has `hidden=1`; in Expert the same second record has `hidden=0`.

The main gameplay actor frame id maps to the AE000 resources loaded around
`0x1d5f..0x1e2b`:

```text
00..16 -> AE000:020
17..2a -> AE000:021
2b..53 -> AE000:022
```

The later `0x49..0x51` resource run belongs to another actor/display
initialization path and should not be used for normal room enemies.  Level 1
room 0 confirms this: frame `0x3f` maps to `AE000:022:20`, the green snake.
Its Explorer and Expert records share the same start position/frame, but point
at different script offsets (`0x01c1` vs `0x01e1`); the first movement bytes
differ (`fe 00` vs `fc 00`), matching the observed speed change.

Confirmed gameplay enemy groups:

```text
AE000:020:0  frame 00 range 00-01 -> ant
AE000:020:8  frame 08 range 08-0b -> bat
AE000:020:15 frame 0f range 0f-12 -> green spitter
AE000:022:0  frame 2b range 2b-2c -> ladybug
AE000:022:7  frame 32 range 32-35/36 -> scorpion shooter
AE000:022:12 frame 37 range 37-3a -> spider
AE000:022:20 frame 3f range 3f-41 -> snake
```

The underlying mapping is not a hand-written object id table in the room
payload.  AEPROG loads sprite pointer runs from `AE000:020..022` into the global
frame pointer table around `DS:b07c`; actor records then select a frame range
inside that table, and scripts advance frames/positions within that range.

In Level 20 Expert room 0 the actor table has two room-0 records:

```text
actor[0] x=0   y=135 frame=2b -> AE000:022:0  range=2b-2c script=0162
actor[1] x=266 y=89  frame=08 -> AE000:020:8  range=08-0b script=0189
```

That matches the reported bat/ladybug style enemies and explains why they were
missed by trailing-payload object parsing.

## Room transition links

The screen-exit handler around `0x4240..0x4359` reads four 10-byte arrays from
the copied level-part payload:

```text
raw_part[0x1a:0x24] -> left exits
raw_part[0x24:0x2e] -> right exits
raw_part[0x2e:0x38] -> up exits
raw_part[0x38:0x42] -> down exits
```

Values are one-based target room ids; `0` means blocked/no transition.  If the
target is the current room, the EXE just clamps the player position and does not
reload a different room.

For Level 20 Expert room 0, `down[0] == 0x01`, so leaving downward targets room
index `0` again.  That matches the observed "fall out and re-enter the same
room" behavior and is a room graph self-link, not a separate teleport object.

## Remaining blind spot

Actor scripts are parsed only as offsets/ranges so far.  Their bytecode controls
movement timing, hidden/start states, and cross-room behavior such as enemies
entering from adjacent rooms.

## Editor overlay

As of v41, editor annotations are drawn by the Tk canvas after the room bitmap
is scaled.  The renderer no longer draws pixel-font labels into the image.
Platform ids, control ids, actor script offsets, raw script bytes, trigger
links, pickups, crystals, room exit arrows, `codes_hex`, and `trailing_hex`
values are separate vector/text overlay items.  This keeps the DOS art crisp at
3x zoom while labels stay readable at screen resolution.

Actor paths are not named as solved yet.  The overlay shows actor start anchors
and the first bytes at each actor's `script_offset`; those bytes are the source
for the future decoded movement-path layer.

Control records may reference platform/object ids outside the current room.
The overlay draws direct arrows only when the referenced id exists in the
current room; otherwise the raw `refs=` list remains visible on the trigger
label for cross-room investigation.
