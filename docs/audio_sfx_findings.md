# PC speaker SFX findings

The confirmed one-shot/event SFX bank is `AE000:065` and is played through the
`CAF1` routine.  Streams are byte pairs.  The low nibble of the first byte is the
opcode; the high nibble is a parameter.

Important control state recovered from the EXE:

- `4D xx` sets the base duration word to `xx * 4` master ticks.
- `3D xx` sets the direct-effect duration used by `?E` opcodes.
- `0D 00` disables the automatic gate cut-off.
- `0D nn` enables automatic gate cut-off and sets the cut-off threshold to `nn`.
- `?E xx` directly programs PC speaker PIT channel 2 using the `CA9B` divisor
  calculation.  It is not a musical note mapping.

A previous preview bug made long streams such as sound `0x00` appear cut off,
because WAV export limited non-music streams to only 200 parsed events.  Sound
`0x00` is much longer than that: the first terminator is near the end of the
chunk, after roughly 695 direct-pitch events.  The SFX parser/exporter now allows
up to 5000 events for one-shot SFX.

Sound `0x0E` is a short rising direct-pitch chirp in the raw SFX data.  If the
in-game laser/head-lamp effect sounds longer or has larger pauses, that is likely
not encoded inside the single `0x0E` stream itself.  The caller around `8DA0`
starts `caf1(0x0E)` as part of the action logic, so the perceived longer
"trrroi" may come from external retriggering or gameplay timing around that
action rather than from additional bytes in the SFX chunk.
