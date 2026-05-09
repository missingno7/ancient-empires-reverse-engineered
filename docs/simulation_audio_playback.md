# Simulation audio playback

The Simulation tab now treats actor VM opcode `0x07` as the real `play_sound(id)` side effect.

Implementation notes:

- `RoomSimulation` records `play_sound` ids in `pending_sound_ids` while stepping actor scripts.
- The GUI drains that queue once per simulation tick and resolves the id through the Audio Atlas.
- Only `pc-speaker-sfx` items are used, i.e. the split CAF1 streams from the confirmed AE000:065 SFX bank.
- The simulation does not reinterpret sound ids as music resources or raw resource indexes.
- When several `play_sound` instructions fire during one VM burst/tick, the GUI plays the last one. This is closer to the single-output PC speaker model and avoids many overlapping preview processes.
- Playback uses `temp_preview_wav(item, speed=DEFAULT_PREVIEW_SPEED)`, so Simulation uses the same SFX decoder as the Audio Atlas preview.

The SFX decoder is now capture-calibrated. Simulation playback therefore uses the same `play_sound(id)` stream and renderer as the Audio Atlas preview instead of silently showing only `sound XX` in actor debug.
