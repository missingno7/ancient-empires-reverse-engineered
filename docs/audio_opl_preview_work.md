# AdLib / OPL instrument follow-up

## Confirmed by ASM

The sound-card music path is an AdLib/Sound Blaster FM path, not only a PSG/Tandy path.
The important initialization flow is:

```text
D8F0
  reads 9 instrument IDs from sound-card music header offset +0x08
  reads voice-level bytes from header offset +0x1A
  writes adjusted carrier total level to DS:301A + instrument_id*0x38 + 0x2A
  calls DA66 for each active OPL voice

DA66
  uses operator slot pairs from DS:2FD2
  loads first 13-word operator block from patch +0x00
  loads second 13-word operator block from patch +0x1A
  loads waveform words from patch +0x34 / +0x36

E1F2 / E27B / E2D6 / E324 / E372 / E44B
  emit OPL registers 0x20/0x40/0x60/0x80/0xE0/0xC0

C898
  writes register/value to the AdLib port selected through DS:1830
```

## Patch layout

`AEPROG.EXE`, DS offset `0x301A`, stride `0x38`:

```text
+0x00  13 little-endian words, operator 1
+0x1A  13 little-endian words, operator 2
+0x34  waveform word for operator 1
+0x36  waveform word for operator 2
```

The low byte of each word is the meaningful value copied into the driver's 14-byte operator state.

## AE000:054 header

```text
stream offsets:      0x0023 0x0161 0x0397 0x0427
OPL instrument IDs:  01 1B 0F 0E 12 0F 0E 17 14
voice cfg:           18 0C 18 00 00 0C 00 00 0C
voice level:         07 07 07 07 07 07 07 07 07
```

`voice level 07` becomes `0x3F - 7*9 = 0x00`, so AE000:054 makes the carrier operator fully loud for all nine initialized OPL voices.

## New tooling

`tools/export_adlib_preview.py` exports:

```text
exports/ae000_054_adlib_like.wav
exports/ae000_054_mapped.mid
exports/ae000_054_opl_init_trace.csv
```

The WAV is an approximate FM renderer. It is **not** a cycle-accurate YM3812 emulator, but it uses the real EXE patch table, the real music header patch IDs and the recovered bytecode timing.

The CSV is more exact for reverse engineering: it lists the OPL register/value pairs produced by the initialization path.

## Audio Atlas changes

The Audio Atlas now has extra sound-card music controls:

- **Play AdLib-like FM**: renders a quick FM-style WAV from the extracted EXE patches.
- **Export OPL init trace**: exports the startup OPL register writes as CSV.
- MIDI instrument audition remains available as a separate General MIDI approximation layer.

## High-score resources

`AE000:061` and `AE000:062` are confirmed high-score / player tables. They are filtered out of the Audio Atlas and should not be treated as audio or patch banks.

## 2026-05-09 follow-up: AE000:054 capture tuning

The largest mismatch was not the global tempo. The capture is 54.081 s and the parser stays at ~54.079 s.

The important AdLib discovery is that the three bytecode streams are **not** simply the final three audible voices. ASM `DB60` maps each stream group to three OPL voices:

- stream 0 -> OPL voices 0, 1, 2
- stream 1 -> OPL voices 3, 4, 5
- stream 2 -> OPL voices 6, 7, 8

`D8F0` copies resource bytes `0x11..0x19` to `DS:CA62..CA6A`; `DB60` then adds those per-voice bytes to the stream note before calling `E48A`. For `AE000:054` the values are:

```text
18 0C 18 00 00 0C 00 00 0C
```

So the AdLib preview now treats them as per-voice pitch offsets/chord intervals instead of passive metadata.

The operator register decoder was also corrected from the ASM:

- `E2D6` writes `0x60+slot = values[3] << 4 | values[6]` (attack/decay)
- `E324` writes `0x80+slot = values[4] << 4 | values[7]` (sustain level/release)
- `E372` writes `0x20+slot` from tremolo/vibrato/sustain/KSR/multiple flags
- `E1F2` writes `0x40+slot` from KSL plus total-level attenuation

The previous preview had the decay and sustain-level fields swapped, which made FM envelopes less like the game.

For the capture-tuned preview, stream 2 is mixed lower because the real `AE000:054` recording has it as a rhythmic/percussive layer under the organ/plucked voices, not as a full-volume lead.
