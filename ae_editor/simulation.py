from __future__ import annotations

from dataclasses import dataclass, field
import random

from .actor_dsl import ActorScriptError, branch_target, decode_instruction, opcode_size
from .constants import CELL_SIZE, ROOM_COLUMNS, ROOM_ROWS
from .coordinates import platform_motion_delta, platform_xy
from .overlay import control_targets
from .room_payload import (
    ACTOR_TABLE_OFFSET,
    ACTOR_TABLE_SIZE,
    ActorTableRecord,
    control_commands,
    header_player_start,
    parse_actor_table,
    parse_platform_triplets,
    record12_green_block_records,
    room_cell_for_runtime_offset,
)

COLLISION_TILE_CODE = 0x07
PLATFORM_FOOTPRINT_CELLS = {
    "horizontal": (6, 1),
    "vertical": (1, 6),
    "unknown": (1, 1),
}


@dataclass
class SimActorState:
    index: int
    name: str
    actor_type: int
    room_index: int
    x: int
    y: int
    frame: int
    frame_variant: int
    hidden: int
    frame_min: int
    frame_max: int
    script_offset: int
    saved_script_offset: int
    restart_script_offset: int
    pc: int
    call_stack: list[int] = field(default_factory=list)
    loop_counters: dict[int, int] = field(default_factory=dict)
    halted: bool = False
    last_event: str = ""

    @classmethod
    def from_record(cls, record: ActorTableRecord) -> "SimActorState":
        return cls(
            index=record.index,
            name=record.confirmed_name or f"frame {record.frame:02X}",
            actor_type=record.actor_type,
            room_index=record.room_index,
            x=record.x,
            y=record.y,
            frame=record.frame,
            frame_variant=record.frame_variant,
            hidden=record.hidden,
            frame_min=record.frame_min,
            frame_max=record.frame_max,
            script_offset=record.script_offset,
            saved_script_offset=record.saved_script_offset,
            restart_script_offset=record.restart_script_offset,
            pc=record.script_offset,
        )


@dataclass
class SimGreenBlockState:
    index: int
    raw: bytes
    sequence: list[int]
    progress: int = 0
    at_alternate: bool = False
    last_event: str = ""

    @classmethod
    def from_record(cls, index: int, raw: bytes) -> "SimGreenBlockState":
        sequence: list[int] = []
        for value in raw[5:10]:
            if value == 0:
                break
            sequence.append(value)
        return cls(index=index, raw=raw, sequence=sequence)

    @property
    def current_xy(self) -> tuple[int, int]:
        base = 2 if self.at_alternate else 0
        if len(self.raw) < base + 2:
            return 0, 0
        return _green_block_xy(self.raw[base], self.raw[base + 1])

    @property
    def remaining_sequence(self) -> list[int]:
        return self.sequence[self.progress:]

    def receive_symbol(self, symbol_id: int) -> bool:
        if not self.sequence:
            return False
        expected = self.sequence[self.progress]
        if symbol_id == expected:
            self.progress += 1
            if self.progress >= len(self.sequence):
                self.progress = 0
                self.at_alternate = not self.at_alternate
                where = "alternate" if self.at_alternate else "default"
                self.last_event = f"complete -> {where}"
                return True
            self.last_event = f"accepted S{symbol_id}"
            return True
        changed = self.progress != 0
        self.progress = 0
        self.last_event = f"reset by S{symbol_id}"
        return changed


def _green_block_xy(raw_x: int, raw_y: int) -> tuple[int, int]:
    return raw_x * 2 - 8, raw_y - 12


def _green_block_footprint_cells_from_xy(x_px: int, y_px: int) -> set[tuple[int, int]]:
    start_x = max(0, min(ROOM_COLUMNS - 1, (x_px + 4) // CELL_SIZE))
    start_y = max(0, min(ROOM_ROWS - 1, y_px // CELL_SIZE))
    return {
        (x, y)
        for y in range(start_y, min(ROOM_ROWS, start_y + 2))
        for x in range(start_x, min(ROOM_COLUMNS, start_x + 6))
    }


def _green_block_footprint_cells(record: SimGreenBlockState, *, alternate: bool | None = None) -> set[tuple[int, int]]:
    use_alternate = record.at_alternate if alternate is None else alternate
    base = 2 if use_alternate else 0
    if len(record.raw) < base + 2:
        return set()
    x_px, y_px = _green_block_xy(record.raw[base], record.raw[base + 1])
    return _green_block_footprint_cells_from_xy(x_px, y_px)


class RoomSimulation:
    """Small in-memory preview of runtime actor/control behavior.

    The original game VM still has unknown corners, so this intentionally
    simulates only the confirmed bytecode and target classes. It never writes
    back into the level model.
    """

    def __init__(self, level, part_index: int, room_index: int):
        self.level = level
        self.part_index = part_index
        self.part = level.part(part_index)
        self.room_index = room_index
        self.tick_count = 0
        self.rng = random.Random((level.index + 1) * 1009 + part_index * 97 + room_index)
        raw = getattr(self.part, "raw", b"")
        block = bytes(raw[ACTOR_TABLE_OFFSET:ACTOR_TABLE_OFFSET + ACTOR_TABLE_SIZE])
        if len(block) < ACTOR_TABLE_SIZE:
            block += b"\x00" * (ACTOR_TABLE_SIZE - len(block))
        self.actor_block = block
        self.actors: dict[int, SimActorState] = {
            record.index: SimActorState.from_record(record)
            for record in parse_actor_table(self.part)
        }
        self.control_states: dict[int, bool] = {}
        self.green_blocks: list[SimGreenBlockState] = []
        self.runtime_tiles_cache: list[int] | None = None
        self._load_initial_controls()
        self._load_green_blocks()
        self.player_x, self.player_y = self._initial_player_position()

    @property
    def room(self):
        return self.part.room(self.room_index)

    def _load_initial_controls(self) -> None:
        for cmd in control_commands(self.room):
            state = bool(len(cmd.body) >= 4 and (cmd.body[3] & 0x40))
            self.control_states[cmd.record.index] = state

    def _load_green_blocks(self) -> None:
        _offset, records = record12_green_block_records(self.room)
        self.green_blocks = [
            SimGreenBlockState.from_record(index, record)
            for index, record in enumerate(records)
            if len(record) >= 4
        ]

    def _initial_player_position(self) -> tuple[int, int]:
        start = header_player_start(self.part.header)
        if start is not None and start.room_index == self.room_index:
            return start.x_raw * 2, start.y_raw
        return ROOM_COLUMNS * CELL_SIZE // 2, ROOM_ROWS * CELL_SIZE // 2

    def controls(self):
        return control_commands(self.room)

    def toggle_control(self, index: int) -> bool | None:
        if index not in self.control_states:
            return None
        self.control_states[index] = not self.control_states[index]
        self._invalidate_runtime_tiles()
        return self.control_states[index]

    def emit_symbol(self, symbol_id: int) -> bool:
        changed = False
        for block in self.green_blocks:
            changed = block.receive_symbol(symbol_id) or changed
        if changed:
            self._invalidate_runtime_tiles()
        return changed

    def set_player_position(self, x: int, y: int) -> None:
        self.player_x = max(0, min(ROOM_COLUMNS * CELL_SIZE - 1, int(x)))
        self.player_y = max(0, min(ROOM_ROWS * CELL_SIZE - 1, int(y)))

    def active_target_indices(self, kind: str) -> set[int]:
        active: dict[int, bool] = {}
        for cmd in self.controls():
            if not self.control_states.get(cmd.record.index, False):
                continue
            for target in control_targets(cmd):
                if target.kind == kind:
                    active[target.index] = not active.get(target.index, False)
        return {index for index, enabled in active.items() if enabled}

    def runtime_tile_at_offset(self, offset: int) -> int | None:
        cell = room_cell_for_runtime_offset(offset)
        if cell is None:
            return None
        room_index, x, y = cell
        if room_index != self.room_index:
            if not 0 <= room_index < len(self.part.rooms):
                return None
            return self.part.room(room_index).get(x, y) if 0 <= x < ROOM_COLUMNS and 0 <= y < ROOM_ROWS else None
        if not 0 <= x < ROOM_COLUMNS or not 0 <= y < ROOM_ROWS:
            return None
        tiles = self._runtime_tiles()
        return tiles[y * ROOM_COLUMNS + x]

    def control_summary(self) -> list[tuple[int, str, bool, str]]:
        rows: list[tuple[int, str, bool, str]] = []
        for cmd in self.controls():
            label = "C"
            if cmd.command == 0x00:
                label = "B"
            elif cmd.command == 0x01:
                label = "S"
            elif cmd.command == 0x02:
                label = "J"
            targets = ",".join(target.label for target in control_targets(cmd)) or "-"
            rows.append((cmd.record.index, f"{label}{cmd.record.index}", self.control_states.get(cmd.record.index, False), targets))
        return rows

    def step(self, ticks: int = 1) -> None:
        for _ in range(max(1, ticks)):
            self.tick_count += 1
            for actor in list(self.actors.values()):
                if actor.room_index == self.room_index:
                    self._step_actor(actor)

    def _step_actor(self, actor: SimActorState) -> None:
        if actor.halted:
            return
        for _ in range(16):
            pc = actor.pc
            if pc < 0 or pc >= len(self.actor_block):
                actor.halted = True
                actor.last_event = "pc outside actor block"
                return
            if self._is_padding_wait(pc):
                actor.halted = True
                actor.last_event = "padding/end"
                return
            try:
                ins = decode_instruction(self.actor_block, pc)
            except ActorScriptError as exc:
                actor.halted = True
                actor.last_event = str(exc)
                return

            op = ins.opcode
            next_pc = pc + ins.byte_size()

            if op == 0x00:
                actor.pc = next_pc
                return
            if op == 0x01:
                actor.pc = ins.target_offset() if ins.target_offset() is not None else next_pc
                continue
            if op == 0x02:
                actor.call_stack.append(next_pc)
                actor.pc = ins.target_offset() if ins.target_offset() is not None else next_pc
                continue
            if op == 0x03:
                actor.pc = actor.call_stack.pop() if actor.call_stack else actor.restart_script_offset
                return
            if op in {0x04, 0x05, 0x06}:
                actor.pc = self._loop_next_pc(actor, pc, op, ins.args[0], ins.args[1], next_pc)
                continue
            if op == 0x07:
                actor.last_event = f"sound {ins.args[0]}"
                actor.pc = next_pc
                continue
            if op == 0x08:
                control_index = ins.args[0]
                state = self.toggle_control(control_index)
                actor.last_event = f"trigger C{control_index}" if state is not None else f"trigger C{control_index}?"
                actor.pc = next_pc
                continue
            if op == 0x09:
                # Actor VM stores emit_symbol as zero-based, while the room's
                # symbol buttons and green-block sequences are exposed as S1..S7.
                symbol_id = ins.args[0] + 1
                self.emit_symbol(symbol_id)
                actor.last_event = f"symbol raw={ins.args[0]} -> S{symbol_id}"
                actor.pc = next_pc
                continue
            if op in {0x0A, 0x0B}:
                target = self._resolve_actor_ref(actor.index, ins.args[0])
                other = self.actors.get(target)
                if other is not None:
                    other.actor_type = 1 if op == 0x0A else 0
                    actor.last_event = f"A{target} mode={other.actor_type}"
                actor.pc = next_pc
                continue
            if op == 0x0C:
                actor.frame_min, actor.frame_max = ins.args
                actor.pc = next_pc
                continue
            if op == 0x0D:
                self._set_packed_frame(actor, ins.args[0])
                actor.pc = next_pc
                continue
            if op == 0x0E:
                dx, dy, packed = ins.args
                actor.x += dx
                actor.y += dy
                self._advance_frame(actor, packed)
                actor.pc = self._after_timed_movement(actor, pc, next_pc)
                return
            if op == 0x0F:
                x_raw, y, packed = ins.args
                actor.x = x_raw * 2
                actor.y = y
                self._advance_frame(actor, packed)
                actor.pc = self._after_timed_movement(actor, pc, next_pc)
                return
            if op == 0x10:
                x_raw, y, packed, room = ins.args
                actor.x = x_raw * 2
                actor.y = y
                actor.room_index = room
                self._set_packed_frame(actor, packed)
                actor.pc = self._after_timed_movement(actor, pc, next_pc)
                return
            if op == 0x11:
                actor.hidden = 1
                actor.pc = next_pc
                return
            if op == 0x12:
                actor.hidden = 0
                actor.pc = next_pc
                continue
            if 0x13 <= op <= 0x1B:
                if self._condition_is_true(op, ins.args[0]):
                    actor.pc = next_pc
                else:
                    actor.pc = self._skip_next_instruction(next_pc)
                continue

            actor.pc = next_pc
            return

        actor.last_event = "step budget exhausted"

    def _is_padding_wait(self, pc: int) -> bool:
        return self.actor_block[pc] == 0x00 and not any(self.actor_block[pc + 1:pc + 8])

    def _skip_next_instruction(self, pc: int) -> int:
        if pc < 0 or pc >= len(self.actor_block):
            return pc
        try:
            size = opcode_size(self.actor_block[pc])
        except ActorScriptError:
            size = 1
        return pc + size

    def _loop_next_pc(self, actor: SimActorState, pc: int, op: int, rel: int, count: int, next_pc: int) -> int:
        target = branch_target(pc, op, rel)
        remaining = actor.loop_counters.get(pc)
        if remaining is None:
            remaining = max(1, count)
        if remaining > 1:
            actor.loop_counters[pc] = remaining - 1
            return target
        actor.loop_counters.pop(pc, None)
        return next_pc

    def _after_timed_movement(self, actor: SimActorState, move_pc: int, next_pc: int) -> int:
        if next_pc >= len(self.actor_block):
            return next_pc
        try:
            loop = decode_instruction(self.actor_block, next_pc)
        except ActorScriptError:
            return next_pc
        if loop.opcode not in {0x04, 0x05, 0x06} or len(loop.args) < 2:
            return next_pc
        if loop.target_offset() != move_pc:
            return next_pc
        # The counted loop is the duration of this one movement instruction.
        return self._loop_next_pc(actor, next_pc, loop.opcode, loop.args[0], loop.args[1], next_pc + loop.byte_size())

    def _set_packed_frame(self, actor: SimActorState, packed: int) -> None:
        actor.frame = packed & 0x7F
        actor.frame_variant = 1 if (packed & 0x80) else 0

    def _advance_frame(self, actor: SimActorState, packed: int) -> None:
        delta = packed & 0x7F
        actor.frame_variant = 1 if (packed & 0x80) else 0
        if not delta:
            return
        lo = actor.frame_min
        hi = max(actor.frame_min, actor.frame_max)
        span = max(1, hi - lo + 1)
        base = actor.frame if lo <= actor.frame <= hi else lo
        actor.frame = lo + ((base - lo + delta) % span)

    def _condition_is_true(self, opcode: int, value: int) -> bool:
        if opcode in {0x13, 0x14, 0x15, 0x16}:
            tile = self.runtime_tile_at_offset(value)
            if tile is None:
                tile = 0
            if opcode == 0x13:
                return bool(tile & 0x07)
            if opcode == 0x14:
                return not bool(tile & 0x07)
            if opcode == 0x15:
                return not bool(tile & 0x10)
            return bool(tile & 0x10)
        if opcode == 0x17:
            return self.player_x > value * 2
        if opcode == 0x18:
            return self.player_x < value * 2
        if opcode == 0x19:
            return self.player_y > value
        if opcode == 0x1A:
            return self.player_y < value
        if opcode == 0x1B:
            return self.rng.randrange(256) < value
        return False

    def _resolve_actor_ref(self, current_index: int, raw: int) -> int:
        raw &= 0xFF
        if raw < 0x80:
            return raw
        return current_index + (raw & 0x7F)

    def _invalidate_runtime_tiles(self) -> None:
        self.runtime_tiles_cache = None

    def _runtime_tiles(self) -> list[int]:
        if self.runtime_tiles_cache is None:
            self.runtime_tiles_cache = self._build_runtime_tiles()
        return self.runtime_tiles_cache

    def _build_runtime_tiles(self) -> list[int]:
        tiles = list(self.room.tiles)

        def set_cell(x: int, y: int, value: int) -> None:
            if 0 <= x < ROOM_COLUMNS and 0 <= y < ROOM_ROWS:
                tiles[y * ROOM_COLUMNS + x] = value

        def clear_cells(cells: set[tuple[int, int]]) -> None:
            for x, y in cells:
                if 0 <= x < ROOM_COLUMNS and 0 <= y < ROOM_ROWS and tiles[y * ROOM_COLUMNS + x] == COLLISION_TILE_CODE:
                    tiles[y * ROOM_COLUMNS + x] = 0

        def write_cells(cells: set[tuple[int, int]]) -> None:
            for x, y in cells:
                set_cell(x, y, COLLISION_TILE_CODE)

        active_platforms = self.active_target_indices("platform")
        for platform in parse_platform_triplets(self.room):
            if not platform.visible:
                continue
            start_cells = self._platform_footprint_cells(platform, offset=(0, 0))
            if platform.index not in active_platforms:
                continue
            clear_cells(start_cells)
            write_cells(self._platform_footprint_cells(platform, offset=platform_motion_delta(platform)))

        for block in self.green_blocks:
            clear_cells(_green_block_footprint_cells(block, alternate=False))
            write_cells(_green_block_footprint_cells(block))

        return tiles

    def _platform_footprint_cells(self, platform, *, offset: tuple[int, int]) -> set[tuple[int, int]]:
        x_px, y_px = platform_xy(platform)
        x_px += offset[0]
        y_px += offset[1]
        cols, rows = PLATFORM_FOOTPRINT_CELLS.get(platform.orientation, PLATFORM_FOOTPRINT_CELLS["unknown"])
        start_x = max(0, min(ROOM_COLUMNS - 1, (x_px + 4) // CELL_SIZE))
        start_y = max(0, min(ROOM_ROWS - 1, (y_px + 8) // CELL_SIZE))
        return {
            (x, y)
            for y in range(start_y, min(ROOM_ROWS, start_y + rows))
            for x in range(start_x, min(ROOM_COLUMNS, start_x + cols))
        }
