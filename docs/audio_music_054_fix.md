# AE000:054 music / sound-card timbre findings

## Confirmed from capture

Reference capture `sound0x00.wav` is 54.081 s. The decoded AE000:054 bytecode runs for about 54.079 s, so the master tick / duration math is already essentially correct. The audible mismatch was mostly pitch base and timbre interpretation, not tempo.

AE000:054 is a 4-offset sound-card music resource:

```text
0x0023 channel 0 - main melody
0x0161 channel 1 - plucked / bass ostinato
0x0397 channel 2 - rhythm / noise voice
0x0427 channel 3 - FF FF terminator only
```

The first melodic command after setup is `35 01`. Older export treated that as E5. The capture fits E4, so the sound-card branch is exported one octave lower than the generic PC-speaker preview.

## Important correction: this is not OPL patch data

The initial assumption was that AE000:061/062 might be AdLib/OPL instrument banks. The disassembly argues against that for the music path currently being previewed:

- the live output helper writes single latched bytes to the selected sound-card port;
- the note helper builds bytes like `0x80 + channel*0x20 + low_nibble` and then writes the high bits separately;
- the volume/envelope helper builds bytes like `0x90/0xB0/0xD0/0xF0 + attenuation`;
- there is no register/value programming sequence to AdLib ports `0x388/0x389` in this path.

That byte shape matches PSG/Tandy/SN76489-style tone/noise/attenuation writes much more closely than OPL FM operators.

## What 5D / 6D mean now

The music stream control handlers are:

```text
5D xx  select PSG timbre/envelope pointer through the game's table
6D xx  store PSG auxiliary live driver byte
```

So the MIDI exporter no longer treats them as meaningless control bytes or timing bytes.

Current conservative MIDI mapping:

```text
5D 02  bell/celesta-like lead
5D 06  picked/plucked bass ostinato
5D 23  release/silent envelope marker, not a new GM instrument
6D xx  expression hint, not tempo and not pitch
```

This is not meant to recreate the original PSG envelope exactly; MIDI cannot represent the original byte-level PSG writes. It does make the export structurally closer: channel 0 becomes a bell-like lead, channel 1 becomes a plucked bass, channel 2 remains percussion/noise-like, and the pitch base matches the capture.

## Patch banks AE000:061/062

AE000:061/062 are now parsed as 27-byte named sound-card patch records:

```text
9 bytes   NUL-padded ASCII name
18 bytes  compact driver parameters / words
```

These records are exposed in the atlas/debug output, but they are intentionally not decoded as OPL registers. The known examples include names such as `Silly`, `Viktor`, `Dj`, `MissingN`, etc.

## Remaining unknowns

- The exact table behind `5D xx -> envelope pointer` is still not fully reconstructed.
- The 18 parameter bytes in AE000:061/062 are parsed and displayed, but not yet proven against the runtime driver.
- The WAV preview still uses a simple square/noise synth. A truly accurate preview would need to emulate the PSG/Tandy-style channel latch, tone/noise register writes, and envelope/attenuation stream per tick.

## Audio atlas MIDI instrument audition

The Audio Atlas now includes a **MIDI instrument audition** panel for music resources.
When a sound-card music mix such as `AE000:054` is selected, the panel lists every detected channel stream and exposes a General MIDI instrument dropdown for each channel.

This is intentionally a reverse-engineering aid rather than a claim that the game stores General MIDI programs:

- the original bytecode/timing/channel parsing is kept intact;
- the dropdown only changes the preview/export mapping layer;
- `5D xx` PSG timbre selectors are shown next to each channel so manual choices can be compared with the in-game recording;
- the `Follow in-stream 5D timbre changes` checkbox can be enabled when testing the current PSG-inspired `5D` mapping, or disabled when manually auditioning one chosen instrument per channel.

For `AE000:054`, useful starting points are:

- channel 0: Drawbar Organ, Reed Organ, Celesta, Music Box, Lead 1 (square), Lead 3 (calliope);
- channel 1: Harpsichord, Clavinet, Acoustic Guitar (steel), Electric Guitar (muted), Electric Bass (pick), Pizzicato Strings;
- channel 2: rhythm/noise channel. It still exports as General MIDI percussion channel 10; the instrument dropdown is visible for consistency, but the rhythm parser currently maps note-like events to percussion hits.
