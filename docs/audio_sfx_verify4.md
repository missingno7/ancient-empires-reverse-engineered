# Audio SFX verification pass 4

This pass reverts the previous assumption that the leading `0x0096` word can be
removed from the PC-speaker/SFX table and that the remaining AE000:065 table is
the normal-note PIT divisor table.

## Why the previous build sounded too high

`CAF1` starts a one-shot sound like this:

```asm
CB11: shl di,1
CB13: add di, WORD PTR ds:175e
CB17: mov ax, WORD PTR es:[di]
CB1A: add ax, WORD PTR ds:175e
CB1E: mov WORD PTR ds:1e88, ax
```

So the leading words in `AE000:065` are definitely a `play_sound(id)` relative
offset table. `0x0096` is sound 0's stream offset, `0x0618` is sound 1's stream
offset, etc. Treating the same table as normal-note PIT divisors makes normal
notes such as `0x03` and PC-speaker music several octaves too high.

## Current preview rule

- Normal note bytecode (`low nibble 1..12`) uses the chromatic mapping from the
  EXE sound-card path (`C384`: `note - 1 + octave * 12`). This matches the older
  preview behavior that sounded closer for `0x03`.
- Direct-pitch/effect bytecode (`?E`) still uses the CAF1 PIT-style arithmetic
  from `CA9B`.
- The direct-pitch base keeps the original `0x0096` value, because listening
  feedback says `0x00`/`0x01` were closer before skipping it.
- WAV synthesis no longer resets oscillator phase on every tiny event. That
  should reduce the audible zipper/click breaks in long 1-tick streams such as
  sound `0x00`.

## What is still unknown

The unresolved part is the real runtime initialization of `DS:17FC` / `DS:1814`.
The disassembly proves those addresses are used as pitch tables, but not yet
which resource or EXE data blob populates them for every sound mode. Until that
copy/init path is found, the code keeps the literal offset-table pitch path only
as a diagnostic mode (`offset_table_pc_speaker`), not as the default preview.
