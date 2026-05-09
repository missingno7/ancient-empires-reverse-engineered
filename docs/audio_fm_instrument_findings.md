# Audio: FM / sound-card instrument findings

This note corrects the earlier false lead around `AE000:061/062` and documents the current best understanding of the AdLib/Sound Blaster music path.

## Confirmed correction: AE000:061/062 are not audio

`AE000:061` and `AE000:062` are 10 × 27-byte player/high-score records. They contain names such as `Silly`, `Viktor`, `Dj`, and `MissingN`. They are now filtered out of the Audio Atlas and are not treated as patch banks.

## The real FM instrument table is in AEPROG.EXE

The DAT music resource contains instrument *ids*, not full FM patches. The full OPL instrument table is embedded in `AEPROG.EXE`.

Important ASM flow:

```text
D8F0:
  read music header at resource+0x08
  for each of 9 voice slots:
    if id != FF:
      instrument_address = DS:301A + id * 0x38
      call DA66(voice, instrument_address, waveform/config)

DA66:
  record + 0x00 -> first 13-word operator block
  record + 0x1A -> second 13-word operator block
  record + 0x34 -> first operator waveform
  record + 0x36 -> second operator waveform

E1F2/E372/E2D6/E324/E44B/E27B:
  convert the compact operator fields into OPL registers
  0x20, 0x40, 0x60, 0x80, 0xE0 and 0xC0

C898:
  writes OPL register/value pairs using base port DS:1830
```

This means each EXE instrument record is `0x38` bytes:

```text
0x00..0x19  operator A, 13 little-endian words, low byte used
0x1A..0x33  operator B, 13 little-endian words, low byte used
0x34..0x35  operator A waveform selector
0x36..0x37  operator B waveform selector
```

## AE000:054 header

For the reference intro/menu music `AE000:054`, the sound-card header is:

```text
stream offsets:       0023 0161 0397 0427
OPL instrument ids:   01 1B 0F 0E 12 0F 0E 17 14
voice cfg:            18 0C 18 00 00 0C 00 00 0C
voice level:          07 07 07 07 07 07 07 07 07
```

So channel 0 starting to sound organ-ish is consistent with OPL patch id `01`, and the plucked/brnkání character of channel 1 is consistent with a separate OPL patch id `1B`.

## What the editor now does

- Audio Atlas no longer shows `AE000:061/062` as audio.
- Sound-card music rows show the DAT-side OPL ids from the music header.
- The code can extract and display the EXE-side OPL patch table at `DS:301A`.
- A generated summary is in `docs/audio_opl_instrument_table.md` and `docs/audio_opl_instrument_table.csv`.

## Remaining work

The MIDI export is still an approximation. The next accuracy step is not more GM guessing, but an actual lightweight OPL preview path or an export/debug mode that emits the exact OPL register writes for each voice. The data needed for the instruments is now available; what remains is synthesizing it accurately.
