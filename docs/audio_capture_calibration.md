# Audio capture calibration

This pass used three WAV recordings captured from the original game:

- `sound0x00.wav` — captured `play_sound(0x00)`, about 5.87 s.
- `normal jump.wav` — captured normal jump, matching `play_sound(0x0C)`.
- `laser.wav` — laser/light-beam-like capture; feature matching is closest to `play_sound(0x14)`, not the shorter `play_sound(0x0F)` stream.

## Result

The editor SFX decoder now follows the real-game captures closely enough for
normal editor playback and Simulation `play_sound(id)` preview.

The important correction was separating two unrelated tables/values:

```text
AE000:065 word 0 = 0x0096    # stream offset for sound 0x00
CAF1 ?E base      ~= 0x8F90  # live PIT divisor base used by CA9B arithmetic
```

Using `0x0096` as the direct-pitch base was wrong. It made direct-pitch effects
wrap around the 16-bit arithmetic in the wrong region and caused bad sweeps or
pitch breaks. Fitting the captured jump sweep against the `3E 05, 3E 0A, ...`
bytecode gives the runtime divisor base used by the current code.

With the capture-calibrated base:

- `play_sound(0x0C)` follows the captured jump sweep.
- `play_sound(0x00)` has the captured duration and pitch contour.
- PC speaker music stays stable because it uses the simpler music/note path,
  not the CAF1 direct-pitch path.
