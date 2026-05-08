# SFX timing/identity verification pass 3

## Main preview regression found

The latest high/fast/piercing preview was caused by keeping the leading `0x0096`
word as if it were the first PC-speaker PIT divisor.

That is wrong for the actual note routines:

- `C988` / `C36C` decrement the note number and index `DS:17FC`.
- Therefore note `1` must read the first real divisor at `DS:17FC`.
- In the PC-speaker music resource layout, the leading `0x0096` is the stream
  start marker. The first real divisor is `0x0618`.

So the effective table must start like this:

```text
0x0618, 0x0638, 0x0666, 0x067E, ...
```

not like this:

```text
0x0096, 0x0618, 0x0638, 0x0666, ...
```

Keeping `0x0096` made note events about ten times too high. That explains the
thin/piercing sound and also made short SFX feel faster or more broken than the
same bytecode in game.

## Refactor made in `ae_editor/audio.py`

- Split note decoding into two explicit paths:
  - `pc_speaker`: real PIT divisor-table path used by PC speaker music/SFX.
  - `soundcard`: semitone-style path used by AdLib/SoundBlaster music streams.
- Added `audio_kind` to WAV/MIDI export paths so a raw sound-card channel does
  not get misclassified as PC speaker just because the channel chunk itself has
  no sound-card resource header.
- Kept high-frequency PIT events as real events instead of turning them into
  artificial rests. The game writes the PIT divisor; it does not silently drop
  these events. This matters for jump arcs such as `0x0C`/`0x10`, which should
  not acquire preview-only gaps.
- Raised WAV preview sample rate to 44100 Hz so high PC-speaker events alias less
  aggressively than at 22050 Hz.

## Identity notes after gameplay feedback

### `0x03`

Keep this as `special_pickup_or_green_symbol` rather than a too-specific apple
label. The code path is still collision result `7`, but listening feedback says
it is very close to the green-block symbol press and can be apple-like by design.

### `0x0A`

Code still points at the control-object/switch family (`36F0`, collision results
`0x20..0x2F`), but the current synthesized preview is not a reliable audible
match. Keep the label as a code-site candidate, not a confirmed switch sound.

### `0x0C` and `0x10`

The ASM evidence for jump paths remains strong:

- `0x0C`: normal grounded jump path, `DS:0730 = 5`.
- `0x10`: longer/special jump path, `DS:0730 = 8`.

The preview should now be less interrupted because high direct-PIT events are no
longer converted to `None`/rest spans.

### `0x0F`

Gameplay listening agrees better with the code-site interpretation: beam hit,
reflection, or light-sensor reaction inside the beam update routine.

### `0x1B`

Keep this as end-of-level / extra puzzle success. It is not ordinary in-room
puzzle feedback.

### `0x01`

Still the best landing/impact candidate from the call site, but the stream is
very short. If it still feels too fast, the next thing to verify is not a magic
stretch constant; it is whether the game retriggers it or layers it with a
movement/animation state outside the SFX bytecode.
