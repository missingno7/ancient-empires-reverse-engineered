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

The live divisor base is not stored as the first word of `AE000:065`. `CA9B`
reads the first word of the EXE PIT divisor table at `DS:17FC`; that word is
`0x8E88`. The editor now uses this exact ASM-backed value. The earlier
capture-fitted approximation was `0x8F90`.

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
5D xx   PSG instrument/envelope selector in music streams
6D xx   PSG auxiliary volume/timbre byte in music streams
```

More precisely, `5D/6D` feed the Tandy/PCjr PSG envelope updater `C440`.
`C27D` invokes that updater only for device `1`. They remain useful MIDI
audition hints, but device `2` AdLib playback gets its instruments from the
resource header and EXE OPL patch table.

For ordinary note/rest events, routine `C9A4` treats duration arguments with
bit `0x80` set as a full-base-duration form: it skips the subdivision/dotted
calculation and stores the unchanged `base + bend` value. It does **not** use
`arg & 0x7F` as a literal tick count.

Music streams have shared global tempo/bend state across channels. The MIDI/WAV
export therefore parses multi-channel music with synchronized stream cursors,
not by decoding each channel in isolation.

## Resource classes

Type `0x44` is a container family, not one audio format. The atlas currently
separates it into:

- `pc-speaker-sfx`: split CAF1 streams from `AE000:065`.
- `pc-speaker-music`: simple PC-speaker music stream beginning at `0x96`.
- `soundcard-music`: multi-channel sound-card music with channel offsets, driven
  by the register-synthesis path described below.
- `soundcard-channel`: one channel from a sound-card music resource.
- `soundcard-patch`: named 27-byte records such as `Silly`, `Viktor`, `Dj`,
  `MissingN` — these are save/high-score/progress data, NOT instruments.
- `raw`: preserved unknown data.

The patch banks are intentionally not treated as playable audio.

## Sound-card music is register synthesis — there are no PCM samples

There is **no PCM/sample path anywhere in the binary**, confirmed three ways:

- The EXE has 62 `out` instructions total; every sound-related one targets an
  OPL/PSG register port (`ds:0x1830`, `0x42/0x43` PIT, `0x61` speaker). The
  dense `out dx,al` runs are VGA register writes (`0x3CE`/`0x3C4`).
- There are **no Sound Blaster DSP ports** (`0x226/0x22A/0x22C/0x22E`) and **no
  DMA controller programming** (`0x00-0x0C`, page register `0x83`). A sampled
  channel would require one or the other.
- The timer ISR (`0x6BCF`) runs at ~237 Hz (PIT reload `0x13B1`) and only calls
  the sound tick `0xC1A0`; there is no sample-rate DAC loop.

Anything that sounds "sampled" (gritty drums/percussion) is **high-feedback FM**
(see the feedback note below), not digitized audio. Sound-card music is entirely
**register-based tone/FM synthesis**. `ds:0x1778` selects the device and
`ds:0x1830` holds the active port:

- **AdLib / OPL2 FM** (device 2): the real instruments are an FM patch table in
  `AEPROG.EXE` at `ds:0x301A`, `0x38` (56) bytes per patch. The OPL register
  writer is `0xC898` — `out` register / settling `in` ×6 / `inc dx` / `out`
  value / settling `in` ×35 — the unmistakable OPL address+data programming
  signature.
- **Tandy / PCjr PSG** (device 1, SN76489 at port `0xC0`): single-port writes via
  `0xC8D4`.
- A third device (device 3, port `0x205`).

The "effects" in the music are FM envelopes/feedback and PSG attenuation, not
sample effects. See `docs/audio_asm_findings.md` for the full OPL patch pipeline.

### OPL instrument pipeline

Each sound-card music resource header carries its own instrument selection:

```text
0x08..0x10  nine OPL instrument ids (one per voice)
0x11..0x19  nine voice config values
0x1A..0x22  nine per-voice level/routing values
```

At music start the loader walks the nine voices: for voice i it takes patch
`id[i]` from `ds:0x301A + id*0x38`, copies it into the working bank at
`ds:0x3044`, overrides the patch level (offset `0x2A`) with `0x3F - level*9`
derived from the resource's `0x1A..0x22` byte, and uploads the two operators via
`0xDA66 -> 0xE0C0 -> 0xC898`. `0xE0C0` copies 13 register bytes per operator from
the patch operator block (at patch `+0x1A`, stride 2) plus a 2-bit feedback/
connection value, into the per-voice OPL register shadow.

## Playback routing

`temp_preview_wav` (Audio Atlas double-click / Play) and the WAV export now route
by kind:

- `pc-speaker-sfx` / `pc-speaker-music` -> `synthesize_wav` (square-wave synth).
  The PC speaker really is a 1-bit square-wave device, so this is correct and is
  left unchanged.
- `soundcard-music` -> `synthesize_soundcard_music_wav`, which feeds the
  recovered register trace to a real `ymfm.YM3812` emulator at its native
  sample rate. If `ymfm-py` is unavailable, it falls back to the older
  `synthesize_adlib_like_wav` approximation.

`temp_preview_wav` stores content-addressed WAV previews in the temporary atlas
directory. Replaying the same item and speed does not synthesize the complete
song again. The cache key includes resource bytes, renderer version, preview
speed and `AEPROG.EXE` metadata so driver discoveries invalidate old previews.

The Audio Atlas renders cache misses on a background worker thread. Tk remains
responsive while a complete song is synthesized. Playback and status updates
return to the UI thread through `after(...)`; a generation token prevents a
late result from playing after Stop or after a newer preview request.

This cache is for atlas responsiveness, not the final gameplay architecture.
Realtime gameplay music should keep one YM3812 instance alive and feed register
writes incrementally as game ticks advance. PC-speaker effects likewise should
update a persistent output voice instead of launching a new WAV player.

## Current state and limitation

PC speaker SFX are capture-accurate enough for editor playback.

The OPL path is decoded, not guessed: `ae_editor/audio/core.py` extracts the
`ds:0x301A` patch table (`load_opl_instrument_table`, file offset
`0x200 + 0x0FA30 + 0x301A = 0x12C4A`), parses each 56-byte patch as two 13-word
operator blocks plus two waveform words (`parse_opl_instrument_patch`), applies
the `0x3F - level*9` carrier-level override, expands each channel to its octave
voice stack (`DB60`), models operator feedback, and can emit an OPL register
trace, a VGM file and a chip-emulated WAV preview. Verified against the
disassembly (`D8F0/DA66/E0C0/C898/DB60`).

The VGM/full-register trace also follows `E48A`'s default pitch lookup directly:
the runtime maps note index to `block = note // 12`, `semitone = note % 12`,
then writes the YM3812 FNUM row from `C6C3`. This removes the earlier trace-only
Hz conversion and manual transpose. The atlas routes those writes through
`ymfm.YM3812`; the old approximate synth remains only as a fallback.

DOSBox Staging uses `Nuked-OPL3-fast` for this register layer and renders the OPL
channel at `49716 Hz`. It may then apply a Sound Blaster model-specific
low-pass filter: `12000 Hz` for SB1/SB2, `8000 Hz` for SBPro1/SBPro2, and none
for SB16/modern output. The atlas uses YMFM rather than Nuked, so a direct
DOSBox capture comparison is still useful, but it no longer guesses FM
waveforms or envelopes.

The register trace sent to YMFM renders all nine stacked OPL voices at their real
OPL-relative levels (carrier total-level + header voice level), with no
per-channel weighting and no octave-stack damping. Earlier previews damped the
octave voices to ~60% and nearly muted the third stream to match one capture,
which is why the sound-card music sounded thin compared with the original's
deeper, fuller stack — `0xDB60` plays every enabled voice at full level.

The fallback FM synth also models OPL operator **feedback** (`0xC0` bits 1..3). Several
music instruments use maximum feedback (AE000:054 ids `0F`/`17` = 7, `0E` = 6),
which turns the operator into a bright, gritty, noise-like timbre. With feedback
ignored, those voices rendered as clean tones; that mismatch is what made a
feedback-heavy voice sound like a missing "PCM/sample" channel. True feedback is
a per-sample recursion; YMFM handles that in normal playback, while the fallback
approximates the steady-state waveform with a few fixed-point iterations of
`y = wave(phase + beta*y)` (vectorized).

Remaining weaknesses:

- It applies only the static header voice level, not the live per-voice volume
  scaling from `0xE1F2` (`ds:[voice-0x35B0]`), so song-internal swells are flat.
- Dynamic `CA24/CA6D` detuned pitch-table selection is not yet connected.
- The atlas does not currently emulate a selected Sound Blaster model's analog
  low-pass filter after YM3812 rendering.
- MIDI export still maps FM patches to conservative GM voices.

For a Nuked-OPL comparison, use `write_opl_vgm` and play the VGM through a
Nuked-based player.

## 2026-05 FM instrument correction

The previous hypothesis that `AE000:061/062` were sound-card instrument banks was rejected. They are 27-byte named records and look more like save/high-score/progress data.

The sound-card music resources themselves contain the first real AdLib/Sound Blaster mapping layer. Before the bytecode streams, bytes `0x08..0x10` store nine OPL instrument ids, bytes `0x11..0x19` store voice config values, and bytes `0x1A..0x22` store voice level/routing values. For example, `AE000:054` uses OPL ids:

```text
01 1B 0F 0E 12 0F 0E 17 14
```

The EXE AdLib path reads these ids and indexes an internal OPL patch table. The editor therefore treats `5D/6D` as stream control/envelope hints and exposes the resource-header OPL ids separately in the MIDI audition panel.
