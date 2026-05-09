# Audio engine status

This is the current authoritative note for the editor audio code. Older notes
that treated the beginning of `AE000:065` as a PIT divisor table have been
removed from the project.

## Confirmed PC speaker SFX path

`AE000:065` is the CAF1/event `play_sound(id)` bank. Its first 16-bit words are
relative offsets into the same resource:

```text
sound id -> stream offset
0x00     -> 0x0096
0x01     -> 0x0618
0x02     -> 0x0638
...
```

`0x0096` is therefore the start of sound `0x00`, not a frequency divisor. This
is the main bug that caused earlier high/warped previews.

The SFX streams are bytecode pairs:

```text
[opcode][arg]
```

The opcode low nibble is the command kind:

```text
0x0       rest / speaker off
0x1..0xC  normal musical note
0xD       control command
0xE       direct PIT/effect pitch
0xF       terminator / loop endpoint
```

For ordinary note commands the preview uses the EXE music-style chromatic
mapping: `note - 1 + octave * 12`. Direct-effect commands (`?E`) use the CAF1
PIT arithmetic from `CA9B`:

```text
if arg == 0:
    speaker off
else:
    divisor = (base - (arg << 7)) & 0xffff
    divisor >>= opcode_high_nibble
    program PIT channel 2
```

The live divisor base is not stored as the first word of `AE000:065`. The editor
uses the capture-calibrated runtime value `0x8F90`, which matches real-game
recordings of `play_sound(0x00)` and normal jump `play_sound(0x0C)`.

## Confirmed timing model

The duration unit is the game master tick (`GAME_MASTER_TICK_HZ`). CAF1 starts
one-shot SFX with:

```text
base duration       = 0x4B * 4 ticks unless changed by 4D xx
direct ?E duration  = 1 tick unless changed by 3D xx
gate cutoff         = 6 ticks unless changed by 0D xx
```

Known `?D` control commands:

```text
0D xx   gate cutoff control; 0 disables normal cutoff
1D xx   positive duration bend: +round(base * xx / 100)
2D xx   negative duration bend: -round(base * xx / 100)
3D xx   direct-effect duration for ?E
4D xx   base duration = xx * 4 ticks
5D xx   sound-card instrument/envelope selector in music streams
6D xx   sound-card auxiliary volume/timbre byte in music streams
```

Music streams have shared global tempo/bend state across channels. The MIDI/WAV
export therefore parses multi-channel music with synchronized stream cursors,
not by decoding each channel in isolation.

## Resource classes

Type `0x44` is a container family, not one audio format. The atlas currently
separates it into:

- `pc-speaker-sfx`: split CAF1 streams from `AE000:065`.
- `pc-speaker-music`: simple PC-speaker music stream beginning at `0x96`.
- `soundcard-music`: AdLib/SoundBlaster-style multi-channel music with channel offsets.
- `soundcard-channel`: one channel from a sound-card music resource.
- `soundcard-patch`: named 27-byte instrument/patch records such as `Silly`, `Viktor`, `Dj`, `MissingN`.
- `raw`: preserved unknown data.

The patch banks are intentionally not treated as playable audio.

## Current limitation

PC speaker SFX are now considered capture-accurate enough for editor playback.
The remaining known weakness is the sound-card/MIDI instrument side: exported
MIDI currently uses generic GM program/drum approximations instead of decoding
and applying the original 27-byte patch/instrument records.
