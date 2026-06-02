# Simulation audio playback

The Simulation tab now treats actor VM opcode `0x07` as the real `play_sound(id)` side effect.

Implementation notes:

- `RoomSimulation` records `play_sound` ids in `pending_sound_ids` while stepping actor scripts.
- The GUI drains that queue once per simulation tick and resolves the id through the Audio Atlas.
- Only `pc-speaker-sfx` items are used, i.e. the split CAF1 streams from the confirmed AE000:065 SFX bank.
- The simulation does not reinterpret sound ids as music resources or raw resource indexes.
- When several `play_sound` instructions fire during one VM burst/tick, the GUI plays the lowest id. This follows the CAF1 priority rule: lower sound ids override higher sound ids on the single PC-speaker output.
- While a Simulation SFX preview is still busy, repeated calls to the same or lower-priority id are ignored instead of restarting the WAV every tick. This prevents rapid back-and-forth restarts when an actor script keeps emitting the same sound. A higher-priority lower id can still interrupt.
- PC-speaker playback uses the shared asynchronous cached WAV task and
  `temp_preview_wav(item, speed=DEFAULT_PREVIEW_SPEED)`. The optional realtime
  callback path is kept for AdLib/YM3812 music only, so Simulation and Audio
  Atlas PC-speaker sounds use the same canonical decoder and cached renderer.

The SFX decoder is now capture-calibrated. Simulation playback therefore uses the same `play_sound(id)` stream and renderer as the Audio Atlas preview instead of silently showing only `sound XX` in actor debug.
