# SFX timing/identity verification pass 2

## Biggest preview bug found

The old preview kept the leading `0x0096` word from the type-0x44 PC-speaker resource preamble as if it were the first PIT divisor. That is wrong for CAF1 playback.

The EXE's note routine `C988` indexes the live PC-speaker divisor table at `DS:17FC`; the first real divisor is `0x0618`, not `0x0096`. `0x0096` is the stream-start/format marker in the resource preamble.

Effect:

- Normal-note SFX such as `0x01`, `0x03`, `0x0A`, `0x0C`, and `0x10` were far too high / buzzy / artificial.
- Direct-pitch SFX were also based on the wrong base divisor if they used table index 0.
- This explains why jump and landing could sound like broken buzzing even when the bytecode IDs were right.

## Gate / sustain semantics

`0D xx` is handled by `CA35`:

- `0D 00`: sets `DS:1E94 = 1`; disables the early speaker-off gate.
- `0D nn`: sets `DS:1E94 = 0` and `DS:1E8E = nn`; enables early cutoff.

During timer update, `C8E2` turns the PC speaker off when:

```text
remaining_ticks == gate_ticks - 1
```

So the bytecode can have a long logical event whose audible part is only the attack, followed by silent tail ticks. This is data-driven, not a magic preview constant.

## Important stream comparisons

### 0x03 vs 0x0A

`0x03`:

```text
4D 0C 0D 01 4C 03 54 03 57 03 54 03 4C 03 54 03 57 03 54 03 4C 02 FF FF
```

`0x0A`:

```text
4D 0C 0D 01 5C 03 64 03 67 03 64 03 5C 03 64 03 67 03 64 03 6C 02 FF FF
```

They are intentionally the same rhythmic motif, only shifted/timbre-changed by opcode high nibble. So it is plausible that apple-like pickup and green-block/symbol/button feedback sound very similar in the real game.

ASM evidence still says:

- `0x03` is called by the collision-result-7 branch. The previous label "apple" may be too specific; safer label: `special_pickup_or_symbol_7`.
- `0x0A` is called at the start of the control object routine for collision results `0x20..0x2F`; safer label: `control_button_switch_family`.

### 0x0C vs 0x10

`0x0C` and `0x10` are both direct-pitch jump arcs. `0x10` is basically a longer/special version of the same idea. The ASM evidence is strong:

- `0x0C` is called when the normal grounded jump path sets `DS:0730 = 5`.
- `0x10` is called when the alternate/special path sets `DS:0730 = 8`.

The old preview made them sound too interrupted mostly because the PIT base divisor table was wrong and because gate semantics were not exact.

### 0x01

`0x01` is a very short descending direct-pitch stream and is still the best landing/touchdown candidate from the ASM call site. It is only about 0.034 s by stream timing, so in game it may be perceived as an impact click/thud rather than a separate melodic sound.

### 0x0F / 0x14

- `0x14`: headlamp beam/shot start, called immediately after the beam initializer `5A3B`.
- `0x0F`: beam hit/reflect/light-sensor reaction, called inside the beam update routine after collision/reflection classifier results.

This matches the observation that the light-sensor reaction sounds closer to `0x0F`.

### 0x1B

`0x1B` is a puzzle success/completion fanfare, but not necessarily the in-room laser/jello action. The call site is in the later puzzle-success routine around `904C`, so label it as end-of-level / extra puzzle success rather than generic room puzzle success.

## Safer labels after this pass

```text
0x00 invincibility_on_confirmed
0x01 landing_impact_candidate
0x02 ordinary_collectible_pickup_candidate
0x03 special_pickup_or_symbol_7 / apple-like motif
0x04 actor_fireball
0x05 actor_unknown
0x06 actor_pill_projectile
0x07 actor_energy_orb
0x08 special_object_pickup_unknown
0x09 ui_status_unknown
0x0A control_button_switch_family
0x0B movement_bump_or_snap
0x0C normal_jump_confirmed
0x0D room_transition
0x0E jello_laser_cell_take/select
0x0F beam_hit_reflect_sensor_reaction
0x10 rocket_boots_jump_confirmed
0x11 failed_invincibility_use
0x12 actor_sparkles
0x13 unused_or_unseen
0x14 headlamp_shot_start
0x15 actor_sparkles_phase
0x16 special_object_condition_unknown
0x17 invalid_action_or_blocked_laser
0x18 looped_transition_effect
0x19 looped_major_transition
0x1A jello_laser_cell_place/restore
0x1B end_or_extra_puzzle_success
```
