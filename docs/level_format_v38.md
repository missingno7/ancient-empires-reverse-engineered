# Ancient Empires level format notes - v38

This build cleans up the switch/button interpretation.

## Control command visual rule

The control records are length-prefixed.  `raw[0]` is the byte length and the
actual command starts at `raw[1]`.

The verified simple rule is now:

```text
command 0 -> ceiling button, AE000:039:0
command 1 -> floor switch,    AE000:040:0
```

Do **not** infer floor/ceiling from the y coordinate and do **not** use `arg_b`
as a sprite id.  Level 1 / Expert / room 3 proves this: all three visible
ceiling buttons are command 0, even though one command has `arg_b == 0x02`.
The arg and extra bytes appear to be trigger/link metadata for platform puzzle
logic.

Example from Level 1 / Expert / room 3:

```text
07 00 18 68 00 00 02 -> command 0 ceiling button, link metadata 00 00 02
07 00 29 68 00 00 01 -> command 0 ceiling button, link metadata 00 00 01
06 00 3A 68 00 02    -> command 0 ceiling button, link metadata 00 02
```

Example from Level 1 / Expert / room 4:

```text
06 01 17 90 00 00 -> command 1 floor switch
06 01 80 80 01 01 -> command 1 floor switch
06 00 80 50 00 00 -> command 0 ceiling button
```

## Remaining unknowns

The visual type is now cleaner, but trigger logic is not solved yet.  The same
control records likely encode which moving platform(s), doors, or puzzle states
are affected by a switch.  The bytes after the command/x/y fields should be
treated as trigger metadata, not as sprite IDs.
