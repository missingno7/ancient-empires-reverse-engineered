# Audio engine status

This is the authoritative note for the editor audio code.

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

`0x0096` is therefore the start of sound `0x00`, not a frequency divisor.

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
`0x8E88`. The editor uses this exact ASM-backed value.

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

The CAF1 SFX engine has a per-event read-tick that the music player does not.
`C8E2`/`C914` only fetch the next event on a later tick that observes the
duration counter at zero, so each SFX event actually occupies `duration + 1`
timer ticks. For ordinary notes the extra tick is negligible, but the `?E`
direct-pitch sweeps used by most SFX run at `effect_ticks = 1`, so the missing
tick made them about twice too fast in preview. The fix adds this read tick on
the SFX path only (`parse_game_audio_stream(music=False)`); the music player
`C1F7` is a separate routine without it, so music timing is unchanged.

Music streams have shared global tempo/bend state across channels. The MIDI/WAV
export therefore parses multi-channel music with synchronized stream cursors,
not by decoding each channel in isolation.

## Preview implementation notes

PC-speaker SFX/music decoding is centralized in `parse_pc_speaker_preview_tracks`,
and sound-card music in the YM3812 register trace. Playback and WAV export share
that exact decode, so there is no second independent decoder.

There is one playback path and one set of dependencies. numpy, sounddevice and
cffi are hard requirements (`requirements.txt`), and sound-card music is rendered
through the bundled **Nuked-OPL3** cffi backend in `nuked_opl3/` (the same
cycle-accurate OPL core DOSBox-X and VGMPlay use - build it once with
`python -m nuked_opl3._ffi_build`). The code does not silently degrade to a
different renderer when one is missing - that raises a clear error. Two cleanly
separated concerns:

- **Interactive playback** (Audio Atlas double-click / Play preview) =
  `play_audio_item_realtime`, a low-latency sounddevice callback. pc-speaker uses
  the square/noise source, sound-card music drives the Nuked-OPL3 chip. Setup
  runs in a worker thread so Tk stays responsive; there is no full-song WAV
  render and no WAV cache on this path.
- **WAV generation** (Export WAV button, Simulation tab) = `synthesize_wav`
  (pc-speaker) and `synthesize_nuked_opl_wav` (sound-card music). File output
  only; never used for the normal preview.

## Resource classes

Type `0x44` is a container family, not one audio format. The atlas currently
separates it into:

- `pc-speaker-sfx`: split CAF1 streams from `AE000:065`.
- `pc-speaker-music`: simple PC-speaker music stream beginning at `0x96`.
- `soundcard-music`: multi-channel sound-card music with channel offsets, driven
  by the register-synthesis path described below.
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

Interactive preview (Audio Atlas double-click / Play) is realtime for every
playable kind, through `start_audio_preview_async` -> `play_audio_item_realtime`:

- `pc-speaker-sfx` / `pc-speaker-music` -> `PcSpeakerRealtimeSource` (square/noise).
- `soundcard-music` -> `OplRealtimeSource` (Nuked-OPL3 driven by the recovered
  register trace).

`start_audio_preview_async` runs the setup (register trace, device open) in a
worker thread so the Tk callback never imports backends, builds an OPL trace, or
opens a device synchronously. Results return to the UI thread through
`after(...)`; a generation token prevents a late result from playing after Stop
or a newer request, and a cancellation token aborts obsolete setup. There is no
WAV render or WAV cache on the playback path.

numpy and sounddevice are hard dependencies and sound-card music needs the
nuked_opl3 cffi backend built. If one is missing the realtime path raises a clear
error - it never silently switches to a different renderer. Set
`AE_DISABLE_REALTIME_AUDIO=1` only to turn realtime off in headless/CI contexts.

WAV generation is a separate concern (Export WAV button, Simulation tab):
`synthesize_wav` for pc-speaker (1-bit square-wave device) and
`synthesize_nuked_opl_wav` for sound-card music (chunked: register writes are fed
to the OPL core in chronological order and PCM blocks are written straight to the
WAV file). `temp_preview_wav` content-addresses these files so Simulation/export
do not re-render the same item. This branch is never used for the normal preview.

The same `render_preview_async` helper is used by Simulation PC-speaker effects,
so CAF1 sound events do not synthesize WAV files inside the simulation tick.

## Current limitations

PC speaker SFX are capture-accurate enough for editor playback.

The OPL path is decoded, not guessed: `ae_editor/audio/core.py` extracts the
`ds:0x301A` patch table (`load_opl_instrument_table`, file offset
`0x200 + 0x0FA30 + 0x301A = 0x12C4A`), parses each 56-byte patch as two 13-word
operator blocks plus two waveform words (`parse_opl_instrument_patch`), applies
the `0x3F - level*9` carrier-level override, expands each channel to its octave
voice stack (`DB60`), and emits an OPL register trace driven into Nuked-OPL3
(plus a VGM file for external players). Verified against the disassembly
(`D8F0/DA66/E0C0/C898/DB60`) and against a DOSBox-X DRO capture of the real game.

The VGM/full-register trace follows `E48A`'s default pitch lookup directly: the
runtime maps note index to `block = note // 12`, `semitone = note % 12`, then
writes the YM3812 FNUM row from `C6C3`. All playback and WAV export route those
writes through the Nuked-OPL3 chip. Operator feedback, envelopes and waveforms
are whatever the chip does;
the editor does not model them itself. (One data fix found via the DRO capture:
channel feedback `0xC0` comes from the *modulator* operator, not the carrier.)

DOSBox Staging uses `Nuked-OPL3-fast` for this register layer and renders the OPL
channel at `49716 Hz`. It may then apply a Sound Blaster model-specific
low-pass filter: `12000 Hz` for SB1/SB2, `8000 Hz` for SBPro1/SBPro2, and none
for SB16/modern output.

For A/B comparison, choose the Audio Atlas `OPL filter` profile or set
`AE_OPL_FILTER_PROFILE` before launching the editor. Supported values are `off`
(default), `sb1`, `sb2`, `sbpro1`, `sbpro2`, `sb16` and `modern`. The
`sb1`/`sb2` profiles apply a first-order `12000 Hz` low-pass; the
`sbpro1`/`sbpro2` profiles use `8000 Hz`, matching DOSBox Staging's model
choices. The cache key includes this profile.

The register trace renders all nine stacked OPL voices at their real OPL-relative
levels (carrier total-level + header voice level), with no per-channel weighting
or octave-stack damping. `0xDB60` plays every enabled voice at full level.

OPL channel **feedback** (`0xC0` bits 1..3) matters here: it makes an operator
self-modulate into a bright, gritty, noise-like timbre - the thing that can sound
like a missing "PCM/sample" channel. Feedback comes from the **modulator**
operator's shadow byte (confirmed against the DRO capture: AE000:054 ids `1B` = 7,
`0F` = 5, `0E`/`14` = 3, `01` = 1, `17` = 0). The register trace carries this
`0xC0` value, which Nuked-OPL3 reproduces.

Things that are NOT missing (verified against the OPL music tick `C27D`): the
detune/chorus system (`CA24` tables + `CA6D` offsets) exists but its setter
`df98` is never called, so OPL voices stay on the base pitch table with zero
detune; the vibrato/envelope updater `C440` and the `6D`/`E1F2` dynamic-volume
path run only for device 1 (Tandy/PCjr PSG), not for OPL. So the editor is
correct to omit detune, vibrato and per-note volume swells for AdLib.

The note trigger only keys on voices that loaded a real instrument. Songs that
disable voices 6..8 with header id `0xFF` (AE000:068/120/124 and AE001:124/126)
leave those voices silent.

Remaining weaknesses:

- The atlas does not emulate the AdLib/Sound Blaster analog **output low-pass
  filter**, so the YM3812 render is brighter/harsher than a real card. This is
  the most likely remaining tone difference. Choose an `OPL filter` profile in
  the Audio Atlas (`sb2` ~12 kHz, `sbpro1/2` ~8 kHz) to approximate it; the right
  choice depends on which card the reference recording used.
- The trace recovers note pitch by round-tripping the parser frequency back to a
  YM3812 note index. It is exact for the known mapping but would be cleaner to
  compute the note index straight from the bytecode.

MIDI export (`write_opl_trace_midi`) is driven from the same OPL register trace:
each of the 9 OPL channels becomes a MIDI channel, FNum/block become a fractional
note rendered as an integer note plus a pitch-wheel (microtonal tuning + small
glides), and the carrier total level becomes note velocity. pc-speaker music
keeps the simpler stream-based MIDI path. `write_opl_vgm` still exports a VGM for
cross-checking against other Nuked/OPL players.

## FM instrument mapping

`AE000:061/062` are 27-byte named save/high-score/progress records, not
sound-card instrument banks.

The sound-card music resources themselves contain the first real AdLib/Sound Blaster mapping layer. Before the bytecode streams, bytes `0x08..0x10` store nine OPL instrument ids, bytes `0x11..0x19` store voice config values, and bytes `0x1A..0x22` store voice level/routing values. For example, `AE000:054` uses OPL ids:

```text
01 1B 0F 0E 12 0F 0E 17 14
```

The EXE AdLib path reads these ids and indexes an internal OPL patch table. The editor therefore treats `5D/6D` as stream control/envelope hints and exposes the resource-header OPL ids separately in the MIDI audition panel.
