# Current Level Format

This is the canonical level-format note for the editor.

## Level Resources

`AE001.DAT` resources `0..19` are the 20 level resources. Each decoded resource
starts with magic byte `0x4D` and splits into two equal difficulty parts:

```text
part 0 = Explorer
part 1 = Expert
```

Each part is parsed as:

```text
0x0000..0x003F  part header
0x0040..0x274F  10 room records * 1000 bytes
0x2750..0x2753  4-byte separator
0x2754..0x330B  actor block, 0x0BB8 bytes
```

## Room Records

Each room record is 1000 bytes:

```text
+0x000..0x001  preamble / metadata
+0x002..0x2AD  terrain grid, 38 * 18 bytes, row-major
+0x2AE..0x3E7  trailing room payload, 314 bytes
```

The room viewport is:

```text
38 columns * 18 rows * 8 px cells = 304 * 144 px
```

Rooms 0..9 are the normal room records. Older editor builds exposed rooms
10..12 by accidentally parsing the 3000-byte actor block as three extra room
records; those pseudo-rooms are not real gameplay rooms.

## Part Header

Known header fields:

```text
header[2] & 0x03       theme index
header[0x03]           player start x
header[0x04]           player start y
header[0x05]           conditional exit door room index, zero-based
header[0x06]           conditional exit door x
header[0x07]           conditional exit door y
header[0x08..0x0D]     room-gated pickup room ids
header[0x0E..0x13]     pickup x values
header[0x14..0x19]     pickup y values
header[0x1A..0x23]     left room links
header[0x24..0x2D]     right room links
header[0x2E..0x37]     up room links
header[0x38..0x41]     down room links
```

Room links are stored as one-based room ids. Zero means no link.

The conditional exit door appears after all artifacts are collected. Its
artwork is sprite 0 from the current theme terrain bank:

```text
theme 0 -> AE001:021:0
theme 1 -> AE001:022:0
theme 2 -> AE001:023:0
theme 3 -> AE001:024:0
```

Door coordinates use the one shared object anchor that AEPROG applies to every
payload object (blit `x = x_raw*2`, `y = y_raw + 0xb8`), which in editor space is:

```text
x = x_raw * 2 - 8
y = y_raw - 16
```

## Trailing Room Payload

The first 30 bytes are ten 3-byte platform records:

```text
+0x00..0x1D  platform triplets
```

Each triplet is:

```text
flags, x_raw, y
```

Known platform flag families:

```text
0x40 / 0x60  horizontal platform
0x80 / 0xA0  vertical platform
```

Current observed travel preview:

```text
0x40  +48 px x
0x60  -48 px x
0x80  +48 px y
0xA0  -48 px y
```

The editor labels those as right, left, down and up respectively. The triplet
does not store an explicit destination point; `platform_motion_delta()` keeps
the shared preview value until an EXE-derived motion table is recovered.

The EXE-style variable payload starts at trailing offset `0x1E`:

```text
+0x1E  directory count / selector family
...    length-prefixed control records
...    section_a compact3 table, puzzle markers
...    section_b record12 table, green-block mechanisms
...    section_c compact3 table, laser crystals
...    visual compact3 table, theme/global visuals
```

Control records are length-prefixed. The command byte is the first byte of the
body, not the length prefix:

```text
raw[0]     length
raw[1]     command
raw[2..]   command arguments
```

Known command families:

```text
0x00  ceiling button
0x01  floor switch
0x02  laser trigger / light sensor family
```

`arg_b & 0x40` is treated as the current confirmed pressed/start-state bit for
switch artwork.

Control target bytes currently decode as:

```text
00..0F  P0..P15 platform slots
10..1F  CV0..CV15 conveyor/CV records
40..4F  R0..R15 section_c reflector records
```

One control can target multiple objects. Observed switch behavior in Simulation
combines active controls on the same target by parity/XOR: one active source
turns the target on, two active sources turn it off again.

### Section A Symbols And Section B Green Blocks

Section_a compact3 entries are wall symbol buttons/emitters. Their low three
code bits are stored zero-based and displayed as one-based `S1..S7`.

Section_b record12 entries are green-block mechanisms. Each 12-byte record uses:

```text
0x00  default x_raw
0x01  default y
0x02  alternate x_raw
0x03  alternate y
0x05..0x09  one-based symbol sequence, zero-terminated
```

Runtime behavior currently modeled:

- correct next symbol advances progress and hides that symbol from the block;
- wrong symbol resets progress and restores the original sequence;
- completing the sequence toggles the block between default and alternate
  position and restores the sequence for the next toggle;
- the block owns a 6x2 `0x07` collision footprint at its current runtime
  position.

Actor VM opcode `0x09` (`emit_symbol`) stores a zero-based raw symbol id. The
runtime signal is therefore `raw + 1`; raw `0` emits `S1`.

## Actor Table

Runtime actor records are stored in the difficulty part, not in room control
records. The table starts at part offset `0x2754`:

```text
+0x000          count
+0x001..        count * 0x20-byte actor records
```

Useful actor record fields:

```text
0x00  actor mode/type; observed mode 0 runs, mode 1 sleeps
0x01  zero-based room index
0x02  x low
0x03  x high
0x04  y low
0x05  y high
0x06  frame
0x07  frame variant / horizontal flip bit
0x08  hidden/start-state
0x09  delay
0x0A  cooldown
0x0B  frame range minimum
0x0C  frame range maximum
0x0D  script offset low
0x0E  script offset high
0x17  restart script offset low
0x18  restart script offset high
```

Confirmed frame families currently include ant, bat, green spitter, ladybug,
scorpion shooter, spider and snake, plus several projectile/secondary actor
frames.


### Actor VM condition model

A data pass over every stock actor script shows that condition opcodes
`0x13..0x1B` guard exactly the immediately following VM command. When the
condition is true the next command executes; when false, that one command is
skipped and execution continues after it. The guarded command is usually a
`jump` or `call`, but stock data also uses `yield`, `set_frame`, `return` and
`set_actor_mode`. This is important for the Actors tab: do not model these as
free-form "skip descriptor" records. Model them as structured guarded
commands.

Relative branches (`0x01`, `0x02`, loops `0x04..0x06`) use offsets relative to
the next instruction.

Runtime tile condition offsets point into the room terrain buffer, whose x
coordinate is two tiles left of the editor's visible room coordinates. In editor
terms, actor VM offset `0x04A8` is room 1 tile `(14,3)`, while the raw buffer
index within that row is x=12. Low terrain bits (`tile & 0x07`) model
passability: `0` is passable, non-zero is solid. Ropes use zero low bits so they
remain passable; `0x07` is an invisible solid tile. Conveyor footprints are
terrain tiles plus a visual CV object: `0x0F` is the grey direction and `0x1F`
is the teal direction. Moving platforms likewise combine a runtime object with
`0x07` terrain tiles that move with it. Simulation also moves the green-block
`0x07` footprint so actor tile checks can see current room runtime collision.

Observed VM opcodes in stock data are limited to `0x00..0x1B` excluding `0x06`;
unknown byte values did not appear as script opcodes in the current actor entry
point scan. Event ids are still semantic names to recover, but their structural
shape is known: `0x07/0x08/0x09 id`.

## Render Order

The current static renderer follows the layer rules recovered from AEPROG's
room draw path around `0x2CE2` where they are known:

1. theme background;
2. animated decal preview pass used by the editor for static snapshots;
3. main visual compact3 entries with `code >= 0x80`;
4. terrain pass, with rope-family tiles drawn inside the same row-major tile
   loop so later wall/terrain sprites can cover rope artwork;
5. main visual compact3 entries with `code < 0x80`;
6. conveyors from CV payload records plus terrain physics tile runs;
7. moving platforms;
8. control records;
9. puzzle markers and panels;
10. laser crystals/reflectors;
11. header pickups;
12. conditional exit door;
13. known extra pickups;
14. visible actor records;
15. player start marker in room 0; the original game does not expose a start-room field.

The compact3 rule is the important broad layering split: high-bit decor is
background, low-bit decor is foreground. Actor/player previews stay after those
foreground decors. Animated decor timing is more dynamic in the EXE: the
after-visual 12-byte table is refreshed by a later animation routine around
`0xD586`, so exact per-frame z-order is still a research target.

## MVP Editing

The current editor writes terrain tile bytes:

```text
room terrain = part_base + 0x40 + room_index * 1000 + 0x02
length       = 38 * 18
```

Changed level resources are written back to `AE001.DAT` as plain uncompressed
resources (`flags=0`). Untouched resources are preserved byte-for-byte.

The editor also writes these known header object slots:

```text
header[0x03..0x04]  player start x/y; start room is hard-coded to room 0
header[0x05..0x07]  exit door
header[0x08..0x19]  six artifact slots
```

The first payload write path covers only the leading moving-platform triplets:

```text
room trailing[slot * 3 + 0]  existing platform flags
room trailing[slot * 3 + 1]  platform x raw
room trailing[slot * 3 + 2]  platform y
```

The editor can move a platform by updating x/y, or delete it by clearing the
three-byte slot. It also keeps the paired `0x07` support footprint in sync for
platform moves/deletes.

Additional modeled payload write paths include control command bodies, CV belt
records, section_a symbols, section_b green blocks, section_c reflectors,
visual compact3 entries, animated decor entries, red apple tail markers, room
links and actor table records. These paths should get binary fixture coverage
before large-scale automated editing.
