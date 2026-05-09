# Audio: YM3812 / OPL full-register trace work

This pass moves the AdLib research from a Python FM approximation toward the
actual register layer used by the original game.

## Confirmed model

The title/sound-card music resource `AE000:054` is still parsed as:

```text
0x00..0x07  stream offsets
0x08..0x10  nine OPL instrument ids
0x11..0x19  nine per-voice pitch offsets copied to DS:CA62..CA6A
0x1A..0x22  nine per-voice level bytes
```

The important playback path is:

```text
D8F0  load the per-song instrument ids and pitch/level header
DA66  copy one EXE patch into the two runtime OPL operator slots
E1F2  write 0x40 + operator slot, total level / KSL
E372  write 0x20 + operator slot, trem/vib/sustain/KSR/mult
E2D6  write 0x60 + operator slot, attack/decay
E324  write 0x80 + operator slot, sustain-level/release
E44B  write 0xE0 + operator slot, waveform
E27B  write 0xC0 + voice, feedback/connection
DB60  map stream 0/1/2 to OPL voices 0..2 / 3..5 / 6..8
E48A  write A0/B0 note registers
E52A  write B0/A0 voice-off before retriggering
```

## What changed in the editor

The old `Export OPL init trace` only wrote the instrument setup.  The editor now
also has:

- `Export full OPL trace`: CSV containing init writes plus A0/B0 note writes for
  the whole song.
- `Export YM3812 VGM`: `.vgm` file with YM3812 register writes suitable for an
  external VGM/OPL player.

This matters because the Python `AdLib-like FM` preview is only an approximation.
The `.vgm` export is closer to the actual game path: it delegates FM synthesis to
an OPL emulator instead of inventing a new synth model in Python.

## Current known limitation

The note A0/B0 calculation currently uses the standard YM3812 formula to convert
frequency to fnum/block.  The DOS code appears to build or use runtime tables
around `C5EA/C64A` and `C6C3`, so the next precision pass should recover those
tables exactly instead of using the formula approximation.

The instrument table itself is no longer guessed: it is still extracted from
`AEPROG.EXE` at DS:301A, stride 0x38.
