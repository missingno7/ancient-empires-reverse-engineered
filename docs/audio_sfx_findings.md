# PC speaker SFX findings

The confirmed one-shot/event SFX bank is `AE000:065` and is played through the
`CAF1` routine. Streams are byte pairs. The low nibble of the first byte is the
opcode; the high nibble is a parameter.

Current implementation summary: see `docs/audio_engine.md`.

Important control state recovered from the EXE:

- `4D xx` sets the base duration word to `xx * 4` master ticks.
- `3D xx` sets the direct-effect duration used by `?E` opcodes.
- `0D 00` disables the automatic gate cut-off.
- `0D nn` enables automatic gate cut-off and sets the cut-off threshold to `nn`.
- `?E xx` directly programs PC speaker PIT channel 2 using the `CA9B` divisor
  calculation. It is not a musical note mapping.

Important resource-layout correction:

```text
AE000:065 word 0 = 0x0096 = offset of sound id 0x00
```

It is not the first PIT divisor. Direct-pitch effects use the live CAF1 divisor
base, currently capture-calibrated as `0x8F90`.

## Capture-verified behavior

The current SFX renderer was calibrated with real-game recordings:

- `play_sound(0x00)` matches the captured long effect duration and pitch contour.
- `play_sound(0x0C)` matches the captured normal jump sweep.
- The laser/headlamp shot capture matches `play_sound(0x14)` better than `0x0F`.

Sound `0x0E` and `0x1A` are part of the separate laser/jello puzzle cell
take/place logic, not the main headlamp shot sound.

## External runtime layers

Some audible behavior is outside the stream bytes themselves:

- `DS:1774` can loop/restart sounds such as `0x18` and `0x19`.
- Actor scripts can repeatedly call `play_sound(id)` through VM opcode `0x07`.
- CAF1 priority favors lower sound ids while another SFX is active.
