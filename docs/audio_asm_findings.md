# Audio/SFX findings from AEPROG_full_disasm.asm

This note summarizes the current reverse-engineering pass over the PC-speaker
sound path. For the implementation-level summary, see `docs/audio_engine.md`.

## Core routines

### `CAF1` — start one-shot/event SFX

`CAF1` is the public `play_sound(sound_id)` routine used by hardcoded game logic
and by the actor VM.

Important behavior:

* It reads streams from the confirmed event SFX bank `AE000:065`, type `0x44`.
* The active stream pointer is stored at `DS:1E88`.
* The current active sound id is stored at `DS:1E8A`.
* New sound ids are compared against the current id:

```asm
CB07: cmp di, WORD PTR ds:1E8A
CB0B: ja  CB41      ; if new id > current id, ignore it
CB0D: mov WORD PTR ds:1E8A, di
```

So lower-numbered sound ids have higher priority.  Sound `0x00` is therefore a
very high-priority effect and can block many other SFX while it is running.

`CAF1` initializes these SFX-state words:

```asm
DS:1E8E = 6      ; gate cutoff threshold
DS:1E92 = 1      ; direct-pitch/effect duration, used by ?E
DS:1E86 = 0      ; duration bend
DS:1E90 = 0      ; remaining ticks
DS:1E94 = 0      ; gate enabled flag/state
DS:1E8C = 0      ; phrase/envelope-ish state used by duration arg bit 0x10
```

### `C8E2` / `C914` — advance active SFX

The timer/update routine advances the active SFX stream.  If the current event
has no remaining ticks, it reads bytecode pairs at `ES:DI`:

```text
[opcode][arg]
```

The opcode is split into nibbles:

```text
hi nibble = parameter/octave/subcommand
lo nibble = command kind
```

Known low nibbles:

```text
0x0       rest / speaker off
0x1..0xC  normal note
0xD       control command
0xE       direct PIT/effect pitch
0xF       terminator / end marker
```

### `CA9B` — direct-pitch opcode `?E`

`?E` is not a MIDI-like pitch.  The routine does direct PIT divisor arithmetic:

```asm
CA9E: mov dl, BYTE PTR es:[di+1]
CAA4: cmp dx, 0
CAA7: jne CAAF
CAA9: call CADB              ; arg 0 means speaker off / rest
CAAF: shl dx, 7
CAB3: neg dx
CAB5: mov cl, ah             ; high nibble shift
CAB9: mov bx, 17FC
CABC: mov ax, [bx]
CABE: add ax, dx             ; 16-bit wraparound
CAC0: shr ax, cl
CAC2: call CAE6              ; write divisor to PIT channel 2 port 0x42
CAC5: call CAD0              ; enable speaker gate via port 0x61
CAC8: mov ax, [1E92]
CACB: mov [1E90], ax         ; event duration comes from 3D/default state
```

Therefore `0E 00` is not bad data.  It is an explicit silence/rest event for the
direct-pitch path. `DS:17FC` is in the EXE data image; its first word is
`0x8E88`, so the direct-pitch base can be taken exactly from the binary instead
of approximated from captures.

### `CA03` — control opcode `?D`

Known controls from the SFX path:

```text
0D xx   gate cutoff control
        xx = 0 disables normal cutoff
        xx > 0 sets cutoff threshold DS:1E8E and enables gate behavior

1D xx   positive duration bend: +round(base_duration * xx / 100)
2D xx   negative duration bend: -round(base_duration * xx / 100)
3D xx   direct-pitch/event duration for ?E, stored in DS:1E92
4D xx   base duration = xx * 4 ticks, stored in DS:1E84
```

The previous parser mistake was treating too many values as simple timing.  In
particular, `?E` duration is controlled by `3D`, not by the second byte of `?E`.

### `C9A4` — normal note/rest duration

For ordinary note and rest opcodes, the second byte is decoded by `C9A4`.
Arguments with bit `0x80` set take a special full-base-duration branch:

```asm
C9B5: test ah, 80h
C9B8: je   C9BE
C9BA: and  al, 7Fh
C9BC: jmp  C9FD
...
C9FD: mov  [1E90], bx       ; bx is still base duration + bend
```

The masked `al` is not stored as the duration. The branch deliberately skips
the shift/dotted calculation and preserves the full `base + bend` value.
Treating `arg & 0x7F` as a literal tick count made any stream using this form
too quick.

## Looping / retriggering

At bytecode terminator `?F`, the engine normally stops the current SFX.  But it
has a global loop/retrigger flag at `DS:1774`:

```asm
C95D: call CADB              ; speaker off
C960: cmp WORD PTR ds:1774, 0
C965: je  C975               ; stop if loop flag is not set
C967: mov ax, WORD PTR ds:1E8A
C96B: call CAF1              ; restart the same sound id
C96F: inc WORD PTR ds:1E90
```

Confirmed hardcoded users of the loop flag:

* `0x58DB` sets `DS:1774 = 1`, plays sound `0x18`, later clears it.
* `0x5965` sets `DS:1774 = 1`, plays sound `0x18`, later clears it.
* `0xB820` sets `DS:1774 = 1`, plays sound `0x19`, later clears it.

This is a real second layer outside the SFX bytecode: some effects become longer
because the game loops/restarts them from code.

## Actor VM sound opcode

The actor VM has a direct sound opcode.  In ASM:

```asm
4CEF: xor ah, ah
4CF1: lods al                ; read sound id from actor script bytecode
4CF2: push ax
4CF3: call CAF1
```

In the editor DSL this is opcode `0x07: play_sound`.

A scan of the current decoded actor scripts finds these sound ids:

```text
0x04: 21 uses, mostly Fireball actors
0x05:  4 uses
0x06: 22 uses, mostly Pill Projectile actors
0x07:  6 uses, mostly Energy Orb actors
0x12: 14 uses, mostly Sparkles actors
0x15: 12 uses, mostly Sparkles actors
```

Generated evidence files:

* `docs/sfx_hardcoded_caf1_calls.csv`
* `docs/sfx_actor_script_uses.csv`

## Notes on specific sounds

### Sound `0x00`

The preview being cut short was caused by the preview event limit, not by the
game data.  The stream has about 695 direct-pitch events before the terminator.

Its header is:

```text
4D 4B  3D 02  0D 01  ... many ?E events ... FF FF
```

Meaning:

* base duration is initialized with `4D 4B`, mostly irrelevant for `?E`
* direct-pitch duration is two master ticks per segment (`3D 02`)
* gate threshold is set to 1 (`0D 01`)

The capture-calibrated decoder now treats this as a valid long direct-pitch
stream. The bytes are not unrelated padding; they are repeated `?E` events.

### Sound `0x01`

The very short atlas preview is consistent with the ASM. Its active stream is:

```text
4D 4B  3E 5A  3E 50  3E 46  3E 3C  3E 32  3E 28  3E 1E  3E 14  FF FF
```

There is no `3D` override, so `CAF1` keeps the initialized direct-pitch duration
of one master tick per `?E` event. Eight events at about `236.69 Hz` produce a
preview of about `34 ms`. This one is intentionally a quick descending chirp,
not evidence that the atlas is playing the stream at the wrong rate.

### Sound `0x0E`

The raw stream is short and has no explicit rests:

```text
4D 4B  3D 02  0D 00  4E 35 4E 38 ... 4E 8C  FF FF
```

So if the real in-game laser sounds longer or has longer gaps, that probably is
not hidden inside `0x0E` itself.  Either:

* `0x0E` is not the laser,
* the game retriggers it externally,
* or the laser uses a different sound id / actor-script sound.

The hardcoded call at `0x8DA4` does play `0x0E`, but it sits in a larger action
routine involving a table around `DS:C316` and calls around `0x9402/0x9466/0x963E`.
It is not one of the actor VM `play_sound` opcodes.

### Laser / beam sounds

The captured `laser.wav` matches `play_sound(0x14)` better than `0x0F`.
Hardcoded calls still show `0x0F` inside the beam collision/reflection update
routine, so the current interpretation is:

```text
0x14  headlamp / laser shot start
0x0F  beam hit / reflector / interaction feedback
```

`0x0E` and `0x1A` belong to the separate laser/jello puzzle cell take/place
logic rather than the main headlamp shot sound.

## Sound-card music path (OPL FM / PSG) — no PCM

The sound-card music is register-based tone/FM synthesis. The binary has 62
`out` instructions total; the sound ones only hit OPL/PSG register ports
(`ds:0x1830`), the PIT (`0x42/0x43`) and the speaker gate (`0x61`). The dense
`out dx,al` runs near startup are VGA register writes (`dx=0x3CE/0x3C4`). There
are **no Sound Blaster DSP ports** (`0x226/0x22A/0x22C/0x22E`), **no DMA**
(`0x00-0x0C`, page `0x83`), and the timer ISR (`0x6BCF`, ~237 Hz, reload
`0x13B1`) only calls the sound tick `0xC1A0` — there is no sample-rate DAC loop.
So a digitized/PCM channel does not exist.

The deeper audit did not find a hidden Sound Blaster DSP branch behind device
`2`: melodic note-on is `C678 -> DB60 -> E48A -> C898`, ending in YM3812
register writes. Device `3` sets port `0x205` and then deliberately falls back
to the PSG-style device-`1` branch; it is not a PCM mixer.

### What sounds "sampled" is high-feedback FM

OPL operator feedback (register `0xC0` bits 1..3, value 0..7) self-modulates the
operator and, at high values, produces a bright, gritty, noise-like timbre that
is easily mistaken for a digitized drum/percussion sample. AE000:054 uses
feedback 6..7 on several voices (instruments `0F`=7, `0E`=6, `17`=7). The editor
preview now models this (`OPL_FEEDBACK_*` in `audio/core.py`); ignoring it made
those voices sound like clean tones and a "PCM channel" appear to be missing.

### Device selection

`0xC77A` switches on the configured device `ds:0x1778` and sets the active port
`ds:0x1830`:

```text
1 -> ds:0x1830 = 0x00C0   Tandy/PCjr SN76489 PSG (single-port writes via 0xC8D4)
2 -> AdLib/OPL2 FM         (calls 0xD99B to upload the FM patches)
3 -> ds:0x1830 = 0x0205    third device
```

### OPL register writer `0xC898`

```asm
c89b: mov dx, ds:0x1830   ; OPL base port
c89f: mov ax, [bp+4]
c8a2: out dx, al          ; register number -> address port
c8a3: in al,dx  (x6)      ; address settling delay (~3.3us)
c8a9: inc dx
c8aa: mov ax, [bp+6]
c8ad: out dx, al          ; value -> data port
c8af: in al,dx  (x35)     ; data settling delay (~23us)
```

The dual `out` plus the 6/35 `in` settling reads are the canonical OPL2
programming pattern. `0xC8D4` is the single-port variant used for the SN76489.

### FM patch table and per-resource instruments

The FM patch ROM is embedded in `AEPROG.EXE` at `ds:0x301A`, `0x38` (56) bytes
per patch (file offset `0x200 + 0x0FA30 + 0x301A = 0x12C4A`). Each sound-card
music resource selects its own instruments in its header:

```text
0x08..0x10  nine OPL instrument ids (one per voice)
0x11..0x19  nine voice config values
0x1A..0x22  nine per-voice level/routing values
```

Instrument upload (`0xD935` loop, nine voices):

```text
for voice i in 0..8:
    id    = header_ids[i]                 ; stop at 0xFF
    level = header_levels[i]              ; resource byte 0x1A+i
    patch = ds:0x301A + id*0x38           ; source FM patch
    work  = ds:0x3044 + id*0x38           ; working copy
    work[0x2A] = 0x3F - level*9           ; override total level
    upload via 0xDA66 -> 0xE0C0 -> 0xC898
```

`0xE0C0` copies 13 register bytes per operator from the patch operator block
(patch `+0x1A`, stride 2) plus a 2-bit feedback/connection value into the
per-voice OPL register shadow at `ds:0xC91B` (14 bytes/voice), then `0xE1C4`
flushes that shadow to the chip. The patch words at `+0x34/+0x36` are the two
operators' OPL base-register offsets.

### Voice stacking — why the music sounds full/deep

`0xDB60` is the per-note trigger and it does NOT play one voice per stream. Each
melodic channel is expanded into a stack of up to three OPL voices, each with
its own pitch offset and enable flag:

```text
channel 0 -> voices 0,1,2   pitch offsets ds:0xCA62/63/64  enables ds:0xC6AB/AC/AD
channel 1 -> voices 3,4,5   ...
channel 2 -> voices 6,7,8   ...
note_for_voice = stream_note + ds:0xCA62[voice]
```

The nine pitch offsets are the music header bytes `0x11..0x19` (copied to
`ds:0xCA62..`); for `AE000:054` they are `24,12,24, 0,0,12, 0,0,12` semitones,
so each channel is an octave/interval stack. The enable byte `ds:0xC6AB+voice`
is set by the instrument loader only when the voice's id is not `0xFF`. Every
enabled voice plays through the same OPL path at the level set by its
instrument carrier total-level and the header voice level (`0x3F - level*9`);
there is no per-channel weighting and no octave attenuation in the driver. The
octave stack at full level is what gives the music its deep, "epic" character.

### Dynamic volume

`0xE1F2` (the `0x40`/total-level flush) scales the carrier total level by a
per-voice runtime volume at `ds:[voice-0x35B0]`, so voices can swell/fade during
a song independent of the static header level. The editor currently applies only
the static header level; live expression is a remaining fidelity item.

### Exact default pitch table

`E48A` does not convert Hz to OPL FNUM values. `DEFA/DE7E/DDD9` prepares runtime
tables, and the default table path is:

```text
C5EA[note] = note / 12       OPL block
C64A[note] = note % 12       semitone index
C6C3[...]  = 157 16B 181 198 1B0 1CA 1E5 202 220 241 263 287
```

`DB60` adds the header voice offset before calling `E48A`, which clamps the note
index to `0..0x5F` and writes A0/B0 directly. The editor VGM/full-trace path now
uses this ASM-shaped lookup instead of converting through Hz and applying a
capture-tuned transpose. Normal atlas playback now renders this trace through
`ymfm.YM3812`; the older approximate WAV path remains only as a fallback.

### `5D` / `6D` controls are PSG envelope controls

The music bytecode handlers `C5B3` and `C5C6` store per-channel PSG envelope
state at `17C4` and `17DC`. The updater `C440` consumes that state and writes
latched bytes through `C8D4`, but `C27D` calls `C440` only when
`DS:1778 == 1` (Tandy/PCjr PSG). These controls are useful hints for MIDI
audition, but they are not an AdLib PCM channel and do not replace the
resource-header OPL instrument ids used by device `2`.

The shared note gate is not PC-speaker-only. For non-PSG devices, `C27D`
decrements the live duration and calls `C6B9` at the configured cutoff
threshold. Keeping the short off interval in the AdLib register trace therefore
matches the DOS driver rather than truncating FM notes accidentally.

This pipeline is already implemented and ASM-verified in
`ae_editor/audio/core.py` (`load_opl_instrument_table`,
`parse_opl_instrument_patch`, `soundcard_music_opl_full_writes`,
`write_opl_vgm`): the `0x301A` table, the 28-word / two-13-word-operator patch
layout, and the `0x3F - level*9` carrier override all match this trace.

### Practical next step

The data side is solved. The remaining work is fidelity: drive the recovered
register trace through a real OPL2 emulator for exact preview, and build a
closer FM-patch → GM mapping (or ship the VGM) for MIDI export. No PCM/sample
work is needed because there is no sample path in the binary.
