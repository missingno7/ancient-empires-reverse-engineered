# SFX identification pass from AEPROG ASM and game data

This pass correlates the confirmed CAF1 `play_sound(id)` bank `AE000:065` with:

1. hardcoded `CAF1` call sites in `AEPROG_full_disasm.asm`,
2. actor VM `play_sound` opcodes in decoded level actor scripts,
3. raw SFX stream shape: duration, rests, direct-pitch events and looping.

The important correction is that the sound identity should not be inferred from
preview sound alone. Some previews still do not match the real game timbre/timing
closely enough. The strongest evidence is where the EXE calls the sound.

## High-confidence gameplay mapping

| ID | Current identification | Evidence |
|---:|---|---|
| `0x00` | temporary invincibility / protection activation | Known from gameplay. ASM at `41FA`/`BE67` sets `DS:072C = 0x3A` and starts `play_sound(0)`. Long stream: ~695 direct-pitch events, ~5.87 s at current timer model. |
| `0x01` | landing / touchdown / impact after falling or settling | Called at `4462` after player movement state changes; code sets a 0x1E tick animation/countdown immediately before playing it. Very short descending chirp. |
| `0x02` | non-apple collectible / artifact pickup, not normal jump | Called at `3BA2` when collision result is `< 7`; code clears item slot tables at `437A/4380/4386` and redraws the 16x16 pickup. |
| `0x03` | special pickup / green-block symbol feedback, apple-like motif | ASM at `3C4A` handles collision result exactly `7`, clears object bytes at `BFBC+0x3E5..0x3E7`, redraws, then plays `0x03`. Gameplay listening says this is closer to the green-block symbol press than a plain apple pickup; both may intentionally share a very similar motif. |
| `0x0A` | control/button/switch family by code, preview mismatch | Called at start of routine `36F0`, reached from collision results `0x20..0x2F`. These are command/control objects in the level payload. The stream has the same motif shape as `0x03` but shifted upward; current listening feedback says the preview does not yet sound like the observed switch sound, so keep this as a code-site candidate rather than a confirmed audible label. |
| `0x0C` | normal jump | Called at `4133` from the grounded movement branch; it sets `DS:0730 = 5` jump-counter and `DS:0734` vertical step. |
| `0x10` | special jump / rocket-boots jump | Called at `40B7` from the alternate action branch where `7277()` returns 1; it sets `DS:0730 = 8`, longer than normal jump. |
| `0x14` | headlamp/laser shot start | Called at `4222` immediately after `call 5A3B`, which initializes the beam state: `DS:C04E=0x17`, `DS:C0C0=0x18`, `DS:08FE=1`, and fills beam coordinate slots. |
| `0x0F` | headlamp/laser beam hit/reflect/interact with reflector/crystal | Called at `5D11`, `5D34`, `5D57` inside the beam update routine after collision/reflection classifier `5F3C` returns 1/2/3. |
| `0x17` | invalid/blocked action for laser/headlamp/jello UI | Called when a laser/jello slot is unavailable (`8D4C`, `8FB2`) and also when trying to fire headlamp while beam state `DS:08FE` is already active (`422C`/`BE93`). |
| `0x0E` | laser/jello puzzle select/take cell, not the headlamp shot | Called at `8DA4` after indexing table `DS:C316 + selected_group*12 + selected_cell*2`, copying a word into `DS:C132`, marking that cell `0xFF`, and calling `9402(1)`. This is a grid/puzzle cell operation. |
| `0x1A` | laser/jello puzzle restore/place cell | Called at `8FE2` in the inverse branch: if current cell is empty (`0xFF`), writes `DS:C132` back into the table, clears `DS:C132`, calls `9402(0)`. Its stream is the reverse of `0x0E`. |
| `0x1B` | end-of-level / extra puzzle success fanfare | Called at `904C` after `969D()` returns nonzero and follow-up routines `6B66`, `9440`, `93AA` run. It is a long musical-ish fanfare (~1.9 s). Gameplay context correction: this is the extra/end puzzle success, not generic in-room puzzle feedback. |

## Actor-triggered sounds

These are not hardcoded to player movement; they are emitted by actor scripts via
VM opcode `0x07 play_sound` at `4CEF..4CF3`.

| ID | Actor-script use |
|---:|---|
| `0x04` | Fireball actors. |
| `0x05` | Unknown actor records in level data; appears as script-triggered sound, not enough naming evidence yet. |
| `0x06` | Pill Projectile actors and some Praying Mantis projectile logic. |
| `0x07` | Energy Orb actors. |
| `0x12` | Sparkles actors. |
| `0x15` | Sparkles / secondary sparkles phase. Also hardcoded in a sparkles-like display routine at `9AD1`. |

## Lower-confidence / likely UI or transition sounds

| ID | Current guess | Evidence / uncertainty |
|---:|---|---|
| `0x08` | special pickup/object effect | Called at `34FC` after drawing an object/sprite sequence; nearby alternate branch plays `0x16` if `es:[bx+1] == 2`. Needs object table naming. |
| `0x09` | menu/status/interstitial sound | Called at `9D80`, then waits for `DS:1770` to clear. Not enough gameplay context yet. |
| `0x0B` | movement bump/snap/edge collision, not primary jump | Called at `4083` in movement collision code after snapping X coordinate to an 8-pixel boundary and setting animation frame. Could be a bump, step, or small landing contact. |
| `0x0D` | room/level transition / door-like transition | Called at `233E` and `249F` around room/scene transition drawing loops and `DS:00BC` toggles. |
| `0x11` | failed use of temporary invincibility / no charge | Called at `4204`/`BE71` when `7313(-1)` returns `0xFFFF`; same branch where success plays `0x00`. |
| `0x13` | no confirmed caller found yet | Stream contains rests and direct-pitch bursts, but no hardcoded or actor-script use was found in this pass. |
| `0x16` | special object condition / alternate pickup feedback | Called at `3510` if `es:[bx+1] == 2` in the object handling routine near `0x34FC`. Needs object semantic decode. |
| `0x18` | looped UI/transition effect | Hardcoded at `58E5`/`596F` with `DS:1774 = 1`, which loops/restarts the sound until the code clears the flag. Looks like a menu/interstitial animation section rather than normal room gameplay. |
| `0x19` | looped larger transition / sequence effect | Hardcoded at `B82A` with `DS:1774 = 1`. Long interrupted stream, probably a major sequence/transition. |

## Why previews still differ from the real game

The ID mapping above is from code/data, not from the current preview timbre. The
preview still has known limitations:

1. It synthesizes square waves from event spans, but the real PIT channel is
   reprogrammed in-place; phase/counter continuity is probably different.
2. Some effects rely on `0E 00` speaker-off events and rapid divisor changes.
   A WAV preview that restarts phase per span can sound too clean or too even.
3. Normal note streams such as `0x03` use the exact `C9A4` duration logic, but
   the perceived in-game tempo may still differ if the SFX update routine is not
   called at exactly the same cadence assumed by the preview.
4. Some sounds are extended by external runtime logic, e.g. `DS:1774` looping
   for `0x18`/`0x19`, or repeated calls from actor scripts/game state.

## Practical labels to put in the editor now

A conservative editor label set should use confidence markers:

```text
0x00 invincibility_on
0x01 landing_impact
0x02 collectible_pickup
0x03 special_pickup_or_green_symbol
0x04 actor_fireball
0x05 actor_unknown
0x06 actor_pill_projectile
0x07 actor_energy_orb
0x08 special_object_pickup_unknown
0x09 ui_status_unknown
0x0A control_button_switch_family_code_candidate
0x0B movement_bump_or_snap
0x0C jump
0x0D room_transition
0x0E jello_laser_cell_take
0x0F headlamp_beam_hit_reflect
0x10 rocket_boots_jump
0x11 failed_invincibility_use
0x12 actor_sparkles
0x13 unused_or_unseen
0x14 headlamp_shot_start
0x15 actor_sparkles_phase
0x16 special_object_condition_unknown
0x17 invalid_action_or_blocked_laser
0x18 looped_transition_effect
0x19 looped_major_transition
0x1A jello_laser_cell_place
0x1B end_or_extra_puzzle_success
```
