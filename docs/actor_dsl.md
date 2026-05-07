# Actor DSL / actor VM round-trip format

`ae_editor.actor_dsl` is a lossless assembler/disassembler for the Ancient Empires actor VM.

It is intentionally close to the original bytecode.  Human summaries such as “walk left 148 px” are useful UI hints, but this DSL is the source-of-truth format for writing actor script bytes back.

## Round-trip contract

For a known contiguous script region:

```python
from ae_editor.actor_dsl import decode_script_region, parse_dsl

script = decode_script_region(raw_region)
dsl = script.to_dsl()
assert parse_dsl(dsl).to_bytes() == raw_region
```

For an actor table record:

```python
from ae_editor.actor_dsl import ActorRecordIR, parse_actor_record_dsl

ir = ActorRecordIR.from_record(actor_record)
dsl = ir.to_dsl(actor_record.confirmed_name)
assert parse_actor_record_dsl(dsl).to_bytes() == actor_record.raw
```

## Example

```text
actor A0 "Snake" {
    mode 0x00
    room 0
    position x=286 y=138
    frame 0x3F
    variant 0x00
    hidden 0x00
    delay 30
    cooldown 0
    frames 0x3F..0x41
    script 0x01C1
    saved_pc 0x0000
    restart 0x01C1
    loops a=0 b=0 c=0
    contact 0x00
    vertical_marker 0x00
    activated 0x00
    raw_state 00 00 00 00
}

script snake_main {
L0000:
    move dx=-2 dy=0 frame_delta=0x01
    loop_a L0000 count=74
L0009:
    move dx=2 dy=0 frame_delta=0x81
    loop_b L0009 count=74
    goto L0000
}
```

## Commands

The DSL covers the current researched actor VM opcode set `0x00..0x1B`:

- `wait`, `goto`, `call`, `return`
- `loop_a`, `loop_b`, `loop_c`
- `event_07`, `event_08`, `event_09`
- `set_actor_mode_1`, `set_actor_mode_0`
- `set_frames`, `set_frame`
- `move`, `move_to`, `move_to_room`
- `hide`, `show`
- `if_tile_solid`, `if_tile_passable`
- `if_conveyor_grey`, `if_conveyor_teal`

The runtime tile checks can be written as visible editor coordinates:

```text
if_tile_solid room=1 x=14 y=3
if_tile_passable room=1 x=14 y=3
```

These assemble to the underlying runtime buffer offset. The actor VM room buffer
keeps two left-edge tile columns that the editor view has cropped away, so
`room=1 x=14 y=3` maps to runtime offset `0x04A8`.
- `if_player_x_gt`, `if_player_x_lt`, `if_player_y_gt`, `if_player_y_lt`
- `if_random_lt`

The condition opcodes are represented exactly as stored: each one guards the next VM command.  Higher-level block syntax should only be added later if the compiler can prove it expands back to equivalent guarded-command bytecode.

## Tool

Dump actor DSL from stock levels:

```bash
python tools/dump_actor_dsl.py --root . --level 1 --difficulty explorer --room 0 --actor 0
```
