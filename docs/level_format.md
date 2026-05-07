# Current Level Format

This is the canonical level-format note for the editor. Older versioned notes
were removed because they mixed confirmed behavior with research dead ends.

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
0x0040..        13 room records * 1000 bytes
...             4-byte footer
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

Some fixed room slots are empty or non-room data. The editor preserves all 13
slots and classifies each as `room`, `empty`, or `data?`.

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

Door coordinates currently use the same screen-space family as several payload
objects, but with an exit-specific origin:

```text
x = x_raw * 2 - 12
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

The EXE-style variable payload starts at trailing offset `0x1E`:

```text
+0x1E  directory count / selector family
...    length-prefixed control records
...    section_a compact3 table, puzzle markers
...    section_b record12 table, puzzle panels
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

## Actor Table

Runtime actor records are stored in the difficulty part, not in room control
records. The table starts at part offset `0x2754`:

```text
+0x000          count
+0x001..        count * 0x20-byte actor records
```

Useful actor record fields:

```text
0x00  actor type
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

Observed VM opcodes in stock data are limited to `0x00..0x1B` excluding `0x06`;
unknown byte values did not appear as script opcodes in the current actor entry
point scan. Event ids are still semantic names to recover, but their structural
shape is known: `0x07/0x08/0x09 id`.

## Render Order

The static renderer currently draws:

1. theme background;
2. background compact3 visuals;
3. terrain tiles;
4. rope special tiles;
5. conveyors from CV payload records plus terrain physics tile runs;
6. moving platforms;
7. control records;
8. puzzle markers and panels;
9. laser crystals;
10. foreground compact3 visuals;
11. header pickups;
12. conditional exit door;
13. known extra pickups;
14. visible actor records;
15. player start marker in room 0.

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
header[0x03..0x04]  player start
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
three-byte slot. Other payload families are intentionally deferred until those
structures have stronger round-trip coverage.
