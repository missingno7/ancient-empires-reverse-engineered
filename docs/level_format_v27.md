# Level/object payload notes - v27 cleanup

This build is a cleanup after comparing the renderer with a fuller AEPROG.EXE disassembly.
The big correction is that the room payload after the terrain grid has several EXE-defined
sections.  Earlier builds were still scanning it heuristically, which produced convincing but
wrong objects.

## Confirmed terrain/room model

Each decoded level resource in `AE001.DAT` is still interpreted as:

```text
2 pages / parts
  0x40 page header
  13 room records * 1000 bytes
    +0x000..0x001  room preamble
    +0x002..0x2AD  38*18 terrain bytes
    +0x2AE..0x3E7  314-byte room payload
  4-byte footer
```

Normal terrain is an 8x8 logical grid rendered with larger overlapping 18x17-ish sprites.
The terrain sprite anchor `(-4,-4)` is intentional and matches the way blocks overlap in the
real game.

## Aha moment from AEPROG.EXE

The payload is not a free-form list of `(x,y,code)` records.  AEPROG points `BFC0` at
`current_room + 0x2CA`, which is `Room.trailing + 0x1E` in the editor.

The relevant routines are:

```text
0x2A2D  skip N length-prefixed records
0x2A70  return the main visual compact3 table
0x2BF7  draw visual compact3 entries with code >= 0x80
0x2C71  render terrain/special background pass
0x2D3E  draw the same visual compact3 table with code < 0x80
0x2F10  process length-prefixed control records
0x3085  process the first compact3 section after control records
0x3132  process 12-byte records and write collision 0x07 spans
```

The effective structure at `trailing+0x1E` is:

```text
base[0]                    directory count / mode selector
base[base[0]*4 + 1]         number of length-prefixed control records
base[base[0]*4 + 2]         first control record

After the selected control records:
  section A: compact3  count + N*(x, y, code)
  section B: record12   count + N*12 bytes
  section C: compact3  count + N*(x, y, code)
  section D: compact3  count + N*(x, y, code)  <-- main visual object table
```

The previous v26 parser used the first compact3 table after the control records as the visual
object table.  That was wrong.  v27 uses section D, matching `0x2A70`.

## Visual compact3 code mapping

AEPROG masks compact3 visual codes with `0x3f` and indexes a runtime pointer table at `DS:72B2`.
That table is rebuilt when the current theme changes by loading resource `0x1019 + theme`,
which corresponds to:

```text
theme 0 -> AE001:025
theme 1 -> AE001:026
theme 2 -> AE001:027
theme 3 -> AE001:028
```

So the current editor now maps:

```text
visual sprite = AE001:(25 + theme):(code & 0x3f)
```

This removes several old per-room/per-code hacks.  For example, background reliefs in level 6
room 5 now come naturally from `AE001:026:0..5`, and the vase/picture/urn-style decorations use
the same general rule.

## Visual compact3 coordinates

AEPROG draws visual compact3 objects into a larger off-screen/world buffer:

```text
x_screen = x_raw * 2
y_screen = y_raw + 0xB8
```

The room viewport terrain origin is roughly:

```text
x_base = 4
y_base = 0xC4
```

Therefore local editor coordinates are:

```text
x = x_raw * 2 - 4
y = y_raw - 12
```

This is now implemented as coordinate mode `screen_exe`.

## Control records currently rendered

Length-prefixed records are not all visual.  Many are platform/trigger/collision logic.
The editor renders only the cases that are visually supported by screenshots:

```text
06 00 x y 00 40 / 06 00 x y 00 41 -> red ceiling/floor button, AE000:039/042 family
06 02 x y 00 00                   -> enemy actor candidate; level 6 room 5 aligns with AE000:020:0 ant when x uses x_raw*4
```

The second rule is still marked as research because enemies likely have a more complete actor
schema elsewhere.

## Laser reflector / crystal section

Section C, which `0x2A70` skips before the main visual table, lines up with the rotating blue
laser reflectors in verified rooms.  v27 renders it as:

```text
sprite = AE000:019:code
x = x_raw * 2 - 4
y = y_raw - 12
```

## Still unresolved

* Collectible diamond/artifact placement is not fully located yet.  Some screenshots show it,
  but it does not consistently appear in the main visual compact3 table.
* Enemy/actor schemas are incomplete.  The ant rule above is a useful match for one room, not a
  final general solution.
* Section A and the 12-byte section B need more reverse engineering.  Section B definitely writes
  collision `0x07` spans in the EXE.
* The exact semantics of Page A/Page B are still not fully clear.  They are not simply two frame
  positions for platforms; they can contain different room layouts.

## Debug tool

Use:

```bash
PYTHONPATH=. python tools/probe_exe_payload.py --exe AEPROG.EXE --level 6 --page A --room 5 AE000.DAT AE001.DAT
```

It now dumps the four EXE sections separately, instead of just reporting one guessed table.
