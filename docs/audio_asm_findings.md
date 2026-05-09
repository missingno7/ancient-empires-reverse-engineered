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
direct-pitch path.

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

## Practical next step

The PC speaker SFX side is now stable enough for editor playback. The next audio work should focus on sound-card/MIDI music: the 27-byte named records are confirmed high-score/player tables, while the real AdLib/OPL instruments are embedded in AEPROG.EXE at DS:301A with a 0x38-byte stride.
