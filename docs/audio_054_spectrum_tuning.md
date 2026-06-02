# AE000:054 AdLib spectrum tuning notes

Reference capture: `music 054.wav` supplied by the user.

The old AdLib-like preview had the right duration and broad event structure, but it sounded too high/thin compared with the capture. A simple spectrum check confirmed it:

| Render | Median spectral centroid | Median 85% rolloff |
| --- | ---: | ---: |
| real capture | ~2055 Hz | ~3951 Hz |
| previous AdLib-like preview | ~4083 Hz | ~10551 Hz |
| tuned AdLib-like preview | ~2133 Hz | ~4791 Hz |

The main finding is that the earlier preview reused the generic `soundcard` note base and then also applied the AdLib header's 9-voice pitch offsets. That made the expanded AdLib render too bright once stream 0 was fanned out to OPL voices 0..2.

The code now keeps MIDI/PC-speaker parsing unchanged, but adds an AdLib-only `ADLIB_OPL_GLOBAL_TRANSPOSE = -12` when producing the recovered OPL register trace and the atlas AdLib WAV preview.

The DAT header pitch offsets are still used. For AE000:054 they are:

```text
18 0C 18 00 00 0C 00 00 0C
```

Those are copied by `D8F0` into `DS:CA62..CA6A` and used by `DB60` before `E48A`. The new tuning does **not** discard them; it shifts the whole AdLib layer down one octave before those offsets are applied.

The normal atlas WAV preview now sends the full recovered voice stack to
`ymfm.YM3812`. The older simple Python FM approximation remains only as a
fallback when `ymfm-py` is unavailable.

Remaining accuracy work:

1. Extend the default `E48A` table reconstruction to dynamic `DS:CA24/CA6D`
   pitch-table redirection if a stock trigger is connected.
2. Play the exported VGM through a Nuked-based renderer and compare that
   spectrum to the DOSBox capture. If it is still off, inspect dynamic
   pitch-table redirection and the selected Sound Blaster output filter.
3. Model live operator-volume behaviour more closely if later music records use `DB17/DAD7` style runtime changes.
