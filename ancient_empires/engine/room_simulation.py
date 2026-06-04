from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import random

from ..game_data.actor_dsl import ActorScriptError, branch_target, decode_instruction, opcode_size
from ..constants import CELL_SIZE, ROOM_COLUMNS, ROOM_ROWS
from .runtime import (
    PLATFORM_TRAVEL_DISTANCE,
    control_targets,
    platform_motion_delta,
    platform_xy,
)

# Platform slide speed in pixels per tick (AEPROG 0x25b3 moves 8 px/step).
PLATFORM_STEP = 8

# Flashlight laser (AEPROG 0x5a3b/0x5ac3).  The original does not draw an
# instant full-width beam.  0x5a3b fills two 0x18-word coordinate arrays
# (DS:C050..C07F and DS:C080..C0AF) with the muzzle position, sets DS:C04E to
# the last ring slot, DS:C0C0 to 0x18, and raises the active/cooldown flag
# DS:08FE.  Each 0x5ac3 update advances only eight 1-pixel substeps through
# that 24-slot ring, so the visible laser is a short line that grows and then
# travels through the room.
LASER_TTL = 0x18
LASER_RING_SLOTS = 0x18
LASER_SUBSTEPS_PER_TICK = 8
LASER_PIXEL_STEP = 1
# Actor byte 0x09 is copied to byte 0x0A when the laser head overlaps
# the actor.  A zero value intentionally means "not frozen"; this is how
# stock projectile/secondary records avoid being stopped by the flashlight.
LASER_FREEZE_TICKS = 0x40  # legacy fallback only; real actors use record.delay
from ..game_data.game_graphics_records import iter_game_graphics_records
from ..game_data.dat_archive import DatArchive
from ..game_data.room_payload import (
    ACTOR_TABLE_OFFSET,
    ACTOR_TABLE_SIZE,
    ActorTableRecord,
    control_commands,
    header_player_start,
    parse_actor_table,
    parse_platform_triplets,
    parse_conveyor_visual_records,
    record12_green_block_records,
    room_cell_for_runtime_offset,
    section_a_symbol_table,
    laser_crystal_table,
)

COLLISION_TILE_CODE = 0x07
# play_sound id for switch/symbol activation feedback (AEPROG 0x34fc).
SFX_TRIGGER = 8
CONVEYOR_GREY_TILE_CODE = 0x0F
CONVEYOR_TEAL_TILE_CODE = 0x1F
CONVEYOR_TILE_TOGGLE = {
    CONVEYOR_GREY_TILE_CODE: CONVEYOR_TEAL_TILE_CODE,
    CONVEYOR_TEAL_TILE_CODE: CONVEYOR_GREY_TILE_CODE,
}
PLATFORM_FOOTPRINT_CELLS = {
    "horizontal": (6, 1),
    "vertical": (1, 6),
    "unknown": (1, 1),
}
REFLECTOR_FRAME_COUNT = 24
REFLECTOR_AUTO_TICKS = 10
LASER_DIRECTION_COUNT = 12
LASER_DIRECTION_PHASES = 6
# 12-way direction table copied from the DS:0900 signed-word table used by
# AEPROG 0x5ac3.  Direction 3 is due-right, 9 is due-left, and diagonal-ish
# rows use a six-step dither so the beam can travel at shallow/steep angles
# without requiring fractional coordinates.
LASER_DIRECTION_STEPS = {
    0: [(0, 0), (0, -1), (0, -1), (0, -1), (0, -1), (0, -1)],
    1: [(0, -1), (1, -1), (1, -1), (0, -1), (1, -1), (1, -1)],
    2: [(0, -1), (1, -1), (1, 0), (1, -1), (1, 0), (1, -1)],
    3: [(1, 0)] * 6,
    4: [(1, 0), (1, 1), (1, 0), (1, 1), (1, 0), (1, 1)],
    5: [(1, 0), (1, 1), (1, 1), (0, 1), (1, 1), (1, 1)],
    6: [(0, 1)] * 6,
    7: [(0, 1), (-1, 1), (-1, 1), (0, 1), (-1, 1), (-1, 1)],
    8: [(0, 1), (-1, 1), (-1, 0), (-1, 1), (-1, 0), (-1, 1)],
    9: [(-1, 0)] * 6,
    10: [(-1, 0), (-1, -1), (-1, 0), (-1, -1), (-1, 0), (-1, -1)],
    11: [(-1, 0), (-1, -1), (-1, -1), (0, -1), (-1, -1), (-1, -1)],
}


def _load_reflector_pixel_masks() -> list[list[list[int]]]:
    """Load the 30x30 reflection-class masks used by AEPROG 0x5f3c.

    Reflector sprites live in AE000 resource 19.  The draw routine at 0x6036
    blits one 0x0f-byte x 0x1e-row sprite, while 0x5f3c indexes the same
    packed 4bpp data nibble-by-nibble to decide which triangular face was hit.
    In the VGA mode used by the game, 0x5f3c classifies the already mapped
    screen colours 0x83/0x86/0x8a rather than raw logical nibbles.  The per-frame
    VGA lookup table changes which logical nibbles are reflective, so precompute
    class masks here instead of using one global raw-nibble mapping.
    """
    candidates = [
        Path("game_data/AE000.DAT"),
        Path(__file__).resolve().parents[2] / "game_data" / "AE000.DAT",
    ]
    dat_path = next((path for path in candidates if path.exists()), None)
    if dat_path is None:
        return []
    try:
        res = DatArchive(dat_path)[19]
        masks: list[list[list[int]]] = []
        for rec in iter_game_graphics_records(res.decoded, res.rtype):
            payload = rec.payload
            row_bytes = payload[0x20]
            height = payload[0x21]
            if row_bytes != 0x0F or height != 0x1E:
                continue
            raw = payload[0x22:0x22 + row_bytes * height]
            if len(raw) < row_bytes * height:
                continue
            vga_table = list(payload[16:32])
            rows: list[list[int]] = []
            for y in range(height):
                row: list[int] = []
                for byte in raw[y * row_bytes:(y + 1) * row_bytes]:
                    for value in ((byte >> 4) & 0x0F, byte & 0x0F):
                        row.append(_reflector_vga_pixel_to_class(vga_table[value]))
                rows.append(row)
            masks.append(rows)
        return masks
    except Exception:
        return []


def _reflector_vga_pixel_to_class(value: int) -> int:
    """Return AEPROG 0x5f3c VGA reflection class for one mapped pixel value."""
    if value == 0x83:
        return 1
    if value == 0x86:
        return 2
    if value == 0x8A:
        return 3
    return 0


REFLECTOR_PIXEL_MASKS = _load_reflector_pixel_masks()


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
    delay: int
    frame_min: int
    frame_max: int
    script_offset: int
    saved_script_offset: int
    restart_script_offset: int
    # Fixed anchor of the spider's hanging thread: the spider's *spawn* ``y``.
    # ``None`` for actors that have no thread (record byte +0x1A == 0).  The live
    # thread length is ``current_y - anchor`` so the thread stays pinned at the
    # original spawn position and stretches as the spider descends, instead of
    # being a fixed segment dragged under it.
    thread_anchor_y: int | None
    pc: int
    call_stack: list[int] = field(default_factory=list)
    loop_counters: dict[int, int] = field(default_factory=dict)
    halted: bool = False
    frozen: int = 0
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
            delay=record.delay,
            frame_min=record.frame_min,
            frame_max=record.frame_max,
            script_offset=record.script_offset,
            saved_script_offset=record.saved_script_offset,
            restart_script_offset=record.restart_script_offset,
            thread_anchor_y=(record.y if record.vertical_marker else None),
            pc=record.script_offset,
            loop_counters={
                0x04: record.loop_counter_a,
                0x05: record.loop_counter_b,
                0x06: record.loop_counter_c,
            },
        )

    @property
    def vertical_marker(self) -> int:
        """Live hanging-thread length: distance from the fixed spawn anchor to
        the spider's current ``y`` (AEPROG draws the thread from
        ``y - vertical_marker + 1`` to ``y``).  Zero when the actor has no
        thread or has climbed back up to the anchor."""
        if self.thread_anchor_y is None:
            return 0
        return max(0, self.y - self.thread_anchor_y)

    @property
    def active(self) -> bool:
        # Stock secondary actors/projectiles sleep in mode 1 until another
        # script wakes them with set_actor_mode_0.
        return self.actor_type == 0

    def activate(self) -> None:
        self.actor_type = 0
        self.halted = False

    def deactivate(self) -> None:
        self.actor_type = 1
        self.call_stack.clear()
        self.loop_counters.clear()
        self.halted = False


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


def _green_block_footprint_cells_from_raw(raw_x: int, raw_y: int) -> set[tuple[int, int]]:
    """Collision footprint of a green block, exactly as AEPROG 0x3132 writes it.

    The original fills a 6x2 invisible-solid (0x07) region whose top-left cell is
    ``col = raw_x // 4 - 1`` (``raw_x`` is the half-resolution x, so /4 = /8 in
    full pixels) and ``row = raw_y // 8 - 1``.  The earlier geometric heuristic
    (``(raw_x*2-4)//8`` / ``(raw_y-12)//8``) drifted by a row or column for many
    blocks, leaving stale invisible walls and clearing the wrong cells when the
    block teleported.
    """
    col = raw_x // 4 - 1
    row = raw_y // 8 - 1
    return {
        (col + dx, row + dy)
        for dy in range(2)
        for dx in range(6)
        if 0 <= col + dx < ROOM_COLUMNS and 0 <= row + dy < ROOM_ROWS
    }


def _green_block_footprint_cells(record: SimGreenBlockState, *, alternate: bool | None = None) -> set[tuple[int, int]]:
    use_alternate = record.at_alternate if alternate is None else alternate
    base = 2 if use_alternate else 0
    if len(record.raw) < base + 2:
        return set()
    return _green_block_footprint_cells_from_raw(record.raw[base], record.raw[base + 1])


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
        self.pending_sound_ids: list[int] = []
        self.green_blocks: list[SimGreenBlockState] = []
        self.reflector_frames: dict[int, int] = {}
        self.reflector_events: dict[int, str] = {}
        # AEPROG 0x60a9 rotates auto reflectors only while no laser is active;
        # DS:0A20 is initialised/reset to 10 and decremented once per call.
        self._reflector_auto_counter = REFLECTOR_AUTO_TICKS
        self.runtime_tiles_cache: list[int] | None = None
        self._last_object_code: int | None = None
        # Per-platform travel progress in pixels (0..PLATFORM_TRAVEL_DISTANCE).
        # Platforms slide gradually toward/away from their target (8 px/tick,
        # AEPROG 0x25b3) rather than snapping.
        self.platform_offsets: dict[int, int] = {}
        # Flashlight laser beam state.  `_laser_slots` mirrors the original
        # 24-entry coordinate ring; `laser_points` is the ordered visible view
        # used by render/tests.
        self._laser_slots: list[tuple[int, int]] = []
        self._laser_head = 0
        self._laser_direction = 3
        self._laser_phase = 0
        self._laser_inactive_substeps = 0
        # Mirrors DS:C0B6 as a collision latch: after a reflector hit, the ASM
        # skips repeated classification while the head is still in that object,
        # but later reflector objects can still bounce the same beam.
        self._laser_reflection_latch_entry: int | None = None
        # Mirrors DS:C0BE/pending 0x338a trigger: one jello/lever control may be
        # tripped by a beam, and the hit kills the travelling head.
        self._laser_triggered_controls: set[int] = set()
        self._laser_freeze_probe_points: list[tuple[int, int]] = []
        self.laser_points: list[tuple[int, int]] = []
        self.laser_ttl = 0
        self._load_initial_controls()
        self._load_green_blocks()
        self._load_reflectors()
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

    def _load_reflectors(self) -> None:
        """Initialise section_c laser reflector runtime frames.

        Section C stores one compact3 byte per reflector.  The low six bits are
        the sprite/orientation frame used by AE000:019.  Bit 0x80 marks
        self-rotating reflectors and bit 0x40 reverses the rotation direction.
        Controlled reflectors do not spin while the control is held; a control
        trigger advances the referenced reflector by exactly one frame.
        """
        table = laser_crystal_table(self.room)
        self.reflector_frames = {}
        self.reflector_events = {}
        if table is None:
            return
        for entry in table.entries:
            # ASM masks the orientation with 0x1f everywhere it draws/updates
            # these crystals (0x6053, 0x60f7/0x6101, 0x61b1/0x61bb).
            # Bit 0x80 is auto-rotate and bit 0x40 reverses step direction;
            # bit 0x20 is preserved as metadata but is not part of the frame.
            self.reflector_frames[entry.index] = (entry.code & 0x1F) % REFLECTOR_FRAME_COUNT

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
        self._trigger_reflector_targets(index)
        self._invalidate_runtime_tiles()
        return self.control_states[index]

    def set_control(self, index: int, state: bool) -> bool | None:
        """Force a control to a specific state (used by momentary buttons)."""
        if index not in self.control_states:
            return None
        if self.control_states[index] == state:
            return state
        self.control_states[index] = state
        self._trigger_reflector_targets(index)
        self._invalidate_runtime_tiles()
        return state

    def _trigger_reflector_targets(self, control_index: int) -> None:
        cmd = next((cmd for cmd in self.controls() if cmd.record.index == control_index), None)
        if cmd is None:
            return
        table = laser_crystal_table(self.room)
        if table is None:
            return
        entries = {entry.index: entry for entry in table.entries}
        for target in control_targets(cmd):
            if target.kind != "reflector":
                continue
            entry = entries.get(target.index)
            if entry is None:
                continue
            self._advance_reflector(entry.index, entry.code, reason=f"C{control_index}")

    def _advance_reflector(self, index: int, code: int, *, reason: str) -> None:
        direction = -1 if (code & 0x40) else 1
        current = self.reflector_frames.get(index, (code & 0x1F) % REFLECTOR_FRAME_COUNT)
        self.reflector_frames[index] = (current + direction) % REFLECTOR_FRAME_COUNT
        message = f"{reason}: frame {self.reflector_frames[index]}"
        previous = self.reflector_events.get(index, "")
        # Auto-rotation is noisy and happens every draw/update pass.  Do not
        # immediately hide the more important laser-reflection trace.
        if "reflect" in previous and reason == "auto":
            self.reflector_events[index] = f"{previous}; {message}"
        else:
            self.reflector_events[index] = message

    def reflector_sprite_index(self, entry) -> int:
        return self.reflector_frames.get(entry.index, (entry.code & 0x1F) % REFLECTOR_FRAME_COUNT)

    def reflector_runtime_summary(self) -> list[str]:
        table = laser_crystal_table(self.room)
        if table is None:
            return []
        return [f"R{entry.index}={self.reflector_sprite_index(entry)}" for entry in table.entries]

    def drain_pending_sound_ids(self) -> list[int]:
        """Return and clear play_sound ids emitted by actor scripts.

        Opcode 0x07 is the actor VM's play_sound/event_07 instruction.  Keep
        it as a side-effect queue so the GUI can play the matching CAF1/PC
        speaker SFX exactly once per simulated execution, instead of replaying
        sounds every redraw.
        """
        out = self.pending_sound_ids
        self.pending_sound_ids = []
        return out

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

    def apply_player_object_interaction(self) -> None:
        """Walk-onto-control activation, recovered from AEPROG 0x3b05/0x3c50.

        Every frame the player loop probes the object box list at the player's
        body box via 0x1d89a and, when the probed object *code* changes, acts on
        it.  Control records sit in that list with code ``index + 8``; stepping
        onto a button (command 0/1) calls 0x338a, which toggles it.  Activation
        is debounced on the code change so holding still does not retrigger.
        Levers (command 2) are excluded from the walk path in the EXE
        (0x3c67) - they are driven by the actor VM (opcode 0x08) instead.

        Section_a symbol buttons register boxes with code ``symbol + 0x20``
        (0x30ff); touching one emits ``symbol + 1`` (0x36f0), advancing the green
        block sequence exactly like an actor's emit_symbol opcode.
        """
        code = self._object_code_at_player()
        if code == self._last_object_code:
            return
        self._last_object_code = code
        if code is None:
            return
        if code >= 0x20:
            if self.emit_symbol((code - 0x20) + 1):
                # AEPROG plays the activation SFX (play_sound 8) on a trigger.
                self.pending_sound_ids.append(SFX_TRIGGER)
            return
        if code < 8:
            return
        index = code - 8
        cmd = next((c for c in self.controls() if c.record.index == index), None)
        if cmd is not None and cmd.command != 2:
            if self.toggle_control(index) is not None:
                self.pending_sound_ids.append(SFX_TRIGGER)

    # Per-command control interaction boxes (left/top offsets and size) as
    # registered into the object list by the control draw at 0x2f10 via 0xd825,
    # all in raw-x / full-y space:
    #   command 0 ceiling button -> (x+6, y+3, 2, 6)   (0x2f98..0x2fb2)
    #   command 1 floor button   -> (x+3, y,   7, 7)   (0x3001..0x3017)
    #   command 2 light sensor   -> (x,   y,   8, 16)  (0x3039..0x307a)
    #   command 3+ trigger       -> (x,   y,   8, 4)   (0x2f38..0x2f49)
    _CONTROL_BOX = {
        0: (6, 3, 2, 6),
        1: (3, 0, 7, 7),
        2: (0, 0, 8, 16),
    }

    def _object_code_at_player(self) -> int | None:
        # Player probe box in raw-x space (AEPROG 0x3b05: x = X/2+1, y = Y+1,
        # w = 14, h = 39).  The query is the inclusive AABB test from 0xd89a.
        qx = self.player_x // 2 + 1
        qy = self.player_y + 1
        q_right = qx + 14 - 1
        q_bottom = qy + 39 - 1
        for cmd in self.controls():
            if cmd.command is None or cmd.x_raw is None or cmd.y_raw is None:
                continue
            ox, oy, ow, oh = self._CONTROL_BOX.get(cmd.command, (0, 0, 8, 4))
            left = cmd.x_raw + ox
            top = cmd.y_raw + oy
            if q_right >= left and left + ow > qx and q_bottom >= top and top + oh > qy:
                return cmd.record.index + 8

        # Section_a symbol buttons (0x30ff): box (x+1, y+4, 6, 10), code sym+0x20.
        table = section_a_symbol_table(self.room)
        if table is not None:
            for entry in table.entries:
                left = entry.x_raw + 1
                top = entry.y + 4
                if q_right >= left and left + 6 > qx and q_bottom >= top and top + 10 > qy:
                    return (entry.code & 0x07) + 0x20
        return None

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
            self._step_laser()
            self._advance_platforms()
            self._step_auto_reflectors()
            for actor in list(self.actors.values()):
                if actor.room_index == self.room_index and actor.active:
                    self._step_actor(actor)
            self._laser_freeze_actors()

    def fire_laser(self, x: int, y: int, facing: int) -> bool:
        """Start the flashlight laser if the original cooldown flag is clear.

        AEPROG 0x4214 refuses to call 0x5a3b while DS:08FE is non-zero and plays
        the blocked-action sound instead.  0x5a3b itself only seeds the 24-slot
        coordinate ring at the muzzle.  The moving trail is produced later by
        0x5ac3, eight 1-pixel substeps per game tick.
        """
        if self.laser_ttl > 0:
            return False
        sx = x + 0x10
        sy = y + 4
        if not (8 <= sx <= 0x137 and 0x10 <= sy <= 0x9f):
            return False

        self._laser_slots = [(sx, sy)] * LASER_RING_SLOTS
        self._laser_head = LASER_RING_SLOTS - 1  # DS:C04E = 0x17
        self._laser_direction = 9 if facing else 3
        self._laser_phase = 0
        self._laser_inactive_substeps = 0
        self._laser_reflection_latch_entry = None
        self._laser_triggered_controls.clear()
        self._laser_freeze_probe_points = [(sx, sy)]
        self.laser_ttl = LASER_TTL  # DS:C0C0 = 0x18 / DS:08FE = 1
        self._refresh_laser_points()
        return True

    def _refresh_laser_points(self) -> None:
        if self.laser_ttl <= 0 or not self._laser_slots:
            self.laser_points = []
            return
        # Oldest-to-newest order, starting after the current ring head.  Drop
        # duplicate seed points so the first frames appear as a growing line
        # rather than a pre-filled instant beam.
        ordered = [
            self._laser_slots[(self._laser_head + 1 + i) % LASER_RING_SLOTS]
            for i in range(LASER_RING_SLOTS)
        ]
        compact: list[tuple[int, int]] = []
        for point in ordered:
            if point == (0, 0):
                continue
            if not compact or compact[-1] != point:
                compact.append(point)
        self.laser_points = compact

    def _laser_hits_edge(self, x: int, y: int) -> bool:
        if not (8 <= x <= 0x137 and 0x10 <= y <= 0x9f):
            return True
        return False

    def _laser_crossed_tile_boundary(self, old_x: int, old_y: int, x: int, y: int) -> bool:
        return (old_x >> 3) != (x >> 3) or (old_y >> 3) != (y >> 3)

    def _laser_hits_solid(self, x: int, y: int) -> bool:
        col = x // 8 - 1
        row = y // 8 - 2
        if 0 <= col < ROOM_COLUMNS and 0 <= row < ROOM_ROWS:
            return bool(self.runtime_tiles()[row * ROOM_COLUMNS + col] & 0x07)
        return False

    def _laser_direction_step(self) -> tuple[int, int]:
        row = LASER_DIRECTION_STEPS[self._laser_direction % LASER_DIRECTION_COUNT]
        dx, dy = row[self._laser_phase % LASER_DIRECTION_PHASES]
        self._laser_phase = (self._laser_phase + 1) % LASER_DIRECTION_PHASES
        return dx * LASER_PIXEL_STEP, dy * LASER_PIXEL_STEP

    @staticmethod
    def _reflector_entry_xy(entry) -> tuple[int, int]:
        # Same transform as rendering.coordinates.object_entry_xy, kept local to
        # avoid coupling the simulation package back to the renderer.
        return entry.x_raw * 2 - 8, entry.y - 16

    def _reflector_at_point(self, x: int, y: int):
        table = laser_crystal_table(self.room)
        if table is None:
            return None
        for entry in table.entries:
            # AEPROG 0x5c18 calls the object hit-test with (laser_x >> 1,
            # laser_y) and accepts section-C objects 0x30..0x4f.  The matched
            # entry then provides the exact raw anchor used by 0x5f3c below:
            # local_x = laser_x - entry.x_raw*2, local_y = laser_y - entry.y.
            # Do not use the editor/rendered top-left here; it is cropped by
            # (-8,-16) for display and makes the triangular faces reflect from
            # the wrong pixels.
            if entry.x_raw <= (x >> 1) < entry.x_raw + 0x0F and entry.y <= y < entry.y + 0x1E:
                return entry
        return None

    @staticmethod
    def _laser_reflection_class(entry, x: int, y: int, frame: int | None = None) -> int:
        # AEPROG 0x5f3c does not treat the reflector as a rectangular mirror.
        # It subtracts the section-C entry position (x_raw*2, y), indexes the
        # current 30x30 packed 4bpp reflector sprite, extracts one nibble, and
        # maps only selected logical colours to reflection classes.  This is the
        # triangular-face test: class 1/2/3 is selected by the actual sprite
        # colour at the touched pixel, not by a simple box or diagonal.
        local_x = x - entry.x_raw * 2
        local_y = y - entry.y
        if not (0 <= local_x < 0x1E and 0 <= local_y < 0x1E):
            return 0

        if frame is None:
            frame = entry.code & 0x1F
        if REFLECTOR_PIXEL_MASKS:
            mask = REFLECTOR_PIXEL_MASKS[frame % len(REFLECTOR_PIXEL_MASKS)]
            return mask[local_y][local_x]

        # Fallback for test/minimal installs without AE000.DAT: keep the same
        # triangle-shaped idea rather than the old square/diagonal classifier.
        if local_x + local_y < 8 or local_x + local_y > 50:
            return 0
        if abs(local_x - local_y) <= 3:
            return 1
        return 2 if local_x > local_y else 3

    def _laser_try_reflect(self, x: int, y: int) -> bool:
        entry = self._reflector_at_point(x, y)
        if entry is None:
            self._laser_reflection_latch_entry = None
            return False
        if self._laser_reflection_latch_entry == entry.index:
            return False
        frame = self.reflector_sprite_index(entry) & 0x1F
        reflection_class = self._laser_reflection_class(entry, x, y, frame)
        if reflection_class == 0:
            return False

        # AEPROG 0x5d00/0x5d20/0x5d43: the three coloured triangular faces are
        # not equivalent.  The 0x5f3c sprite-nibble classifier returns class
        # 1/2/3, and that selects frame-old_dir, frame-old_dir-8, or
        # frame-old_dir+8.  DS:C0B0 (the dither phase into DS:0900) is *not*
        # reset after reflection, so keep our phase too.
        old_direction = self._laser_direction
        adjustment = {1: 0, 2: -8, 3: 8}[reflection_class]
        self._laser_direction = (frame - old_direction + adjustment) % LASER_DIRECTION_COUNT
        self._laser_reflection_latch_entry = entry.index
        self.reflector_events[entry.index] = (
            f"reflect face {reflection_class}: frame {frame} old {old_direction} -> dir {self._laser_direction}"
        )
        self.pending_sound_ids.append(0x0F)
        return True

    def _laser_try_trigger_jello(self, x: int, y: int) -> bool:
        """Return True when the beam hits a command-2 jello/lever trigger.

        In the ASM this is the 0x5c2f..0x5c67 path: object codes 0x08..0x1f
        are converted to control records, only command byte 2 is accepted,
        DS:C0BE is set, SI is cleared, and 0x6021 later calls 0x338a exactly
        once.  The old preview scanned the whole visible trail every tick,
        which made one beam toggle the same jello repeatedly.
        """
        qx = x >> 1
        for cmd in self.controls():
            if cmd.command != 2 or cmd.x_raw is None or cmd.y_raw is None:
                continue
            ox, oy, ow, oh = self._CONTROL_BOX[2]
            left, top = cmd.x_raw + ox, cmd.y_raw + oy
            if left <= qx < left + ow and top <= y < top + oh:
                if cmd.record.index not in self._laser_triggered_controls:
                    self._laser_triggered_controls.add(cmd.record.index)
                    self.toggle_control(cmd.record.index)
                return True
        return False

    def _laser_trip_levers(self) -> None:
        # Compatibility stub retained for older callers/tests.  Jello/lever
        # laser triggering is now done during _step_laser() from the travelling
        # head only, matching the ASM object-probe path and preventing repeated
        # toggles from the historical 24-slot trail.
        return

    def _laser_head_point(self) -> tuple[int, int] | None:
        """Return the single DS:C04E laser coordinate used for actor freeze.

        The renderer shows the whole 24-slot trail, but AEPROG 0x4c7a tests
        actors only against the current head slot (DS:C050/C080 indexed by
        DS:C04E), not every historical point in the trail.
        """
        if self.laser_ttl <= 0 or not self._laser_slots:
            return None
        point = self._laser_slots[self._laser_head]
        return None if point == (0, 0) else point

    def _laser_freeze_actors(self) -> None:
        # AEPROG 0x4c7a copies actor byte 0x09 into byte 0x0A when the active
        # laser coordinate overlaps the actor's sprite bounds.  Zero remains the
        # exclusion filter for projectiles/secondary records.  In this cleaned
        # simulation we test the current tick's moved head positions instead of
        # only the final substep; otherwise an 8-px-per-tick head can skip over
        # many 16-px sprites in the preview.
        points = self._laser_freeze_probe_points or ([self._laser_head_point()] if self._laser_head_point() else [])
        if not points:
            return
        for actor in self.actors.values():
            if actor.room_index != self.room_index:
                continue
            if actor.hidden or actor.frozen > 0 or actor.delay <= 0:
                continue
            ax0, ay0 = actor.x, actor.y
            ax1, ay1 = actor.x + 16, actor.y + 16
            if any(ax0 <= bx <= ax1 and ay0 <= by <= ay1 for bx, by in points):
                actor.frozen = actor.delay

    def _step_laser(self) -> None:
        self._laser_freeze_probe_points = []
        if self.laser_ttl <= 0:
            self._laser_slots = []
            self.laser_points = []
            return

        x, y = self._laser_slots[self._laser_head]
        for _ in range(LASER_SUBSTEPS_PER_TICK):
            if x == 0:
                # ASM 0x5d80 decrements DS:C0C0 only after the travelling head
                # has died (SI == 0).  There is no fixed range counter while the
                # beam is moving; range is effectively bounded by room edge,
                # solid tiles, or a non-reflective collision.
                self.laser_ttl -= 1
                next_x, next_y = 0, 0
                if self.laser_ttl <= 0:
                    self._laser_slots = []
                    self.laser_points = []
                    self._laser_freeze_probe_points = []
                    return
            else:
                dx, dy = self._laser_direction_step()
                next_x = x + dx
                next_y = y + dy
                if self._laser_hits_edge(next_x, next_y):
                    next_x, next_y = 0, 0
                elif (_ % 4) == 0:
                    # AEPROG 0x5c07 tests object collisions only when the
                    # per-call substep counter has bits 0..1 clear.  This is
                    # important for triangular reflectors: the face sampled by
                    # 0x5f3c is a 4-pixel cadence point, not every pixel along
                    # the entering edge.
                    if self._laser_try_trigger_jello(next_x, next_y):
                        next_x, next_y = 0, 0
                    elif self._laser_crossed_tile_boundary(x, y, next_x, next_y) and self._laser_hits_solid(next_x, next_y):
                        next_x, next_y = 0, 0
                    else:
                        reflected = self._laser_try_reflect(next_x, next_y)
                        if reflected:
                            # Reflection rewrites DS:C0B8 (direction) but keeps
                            # this substep's coordinate alive; the new direction
                            # is consumed by the next DS:0900 row lookup.
                            pass
                elif self._laser_crossed_tile_boundary(x, y, next_x, next_y) and self._laser_hits_solid(next_x, next_y):
                    next_x, next_y = 0, 0

            self._laser_head = (self._laser_head + 1) % LASER_RING_SLOTS
            self._laser_slots[self._laser_head] = (next_x, next_y)
            if next_x != 0:
                self._laser_freeze_probe_points.append((next_x, next_y))
            x, y = next_x, next_y

        self._refresh_laser_points()

    def _advance_platforms(self) -> None:
        """Slide each platform toward/away from its target by 8 px (0x25b3)."""
        active = self.active_target_indices("platform")
        changed = False
        for platform in parse_platform_triplets(self.room):
            if not platform.visible:
                continue
            target = PLATFORM_TRAVEL_DISTANCE if platform.index in active else 0
            current = self.platform_offsets.get(platform.index, 0)
            if current == target:
                continue
            step = PLATFORM_STEP if target > current else -PLATFORM_STEP
            current = max(0, min(PLATFORM_TRAVEL_DISTANCE, current + step))
            self.platform_offsets[platform.index] = current
            changed = True
        if changed:
            self._invalidate_runtime_tiles()

    def platform_render_offset(self, platform) -> tuple[int, int]:
        """Current pixel offset of a platform along its travel vector."""
        magnitude = self.platform_offsets.get(platform.index, 0)
        if magnitude <= 0:
            return (0, 0)
        dx, dy = platform_motion_delta(platform)
        scale = magnitude / PLATFORM_TRAVEL_DISTANCE
        return (round(dx * scale), round(dy * scale))

    def _step_auto_reflectors(self) -> None:
        # AEPROG 0x60a9 first checks DS:08FE and returns immediately while a
        # flashlight laser is active/cooling down.  Only when no laser exists
        # does it decrement DS:0A20; on zero it resets the counter to 10 and
        # advances each reflector whose code has bit 0x80.
        if self.laser_ttl > 0:
            return
        self._reflector_auto_counter -= 1
        if self._reflector_auto_counter > 0:
            return
        self._reflector_auto_counter = REFLECTOR_AUTO_TICKS
        table = laser_crystal_table(self.room)
        if table is None:
            return
        for entry in table.entries:
            if entry.code & 0x80:
                self._advance_reflector(entry.index, entry.code, reason="auto")

    def _step_actor(self, actor: SimActorState) -> None:
        if actor.halted:
            return
        # A laser-frozen actor skips its script and counts down (AEPROG 0x4b39).
        if actor.frozen > 0:
            actor.frozen -= 1
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
                sound_id = ins.args[0]
                self.pending_sound_ids.append(sound_id)
                actor.last_event = f"sound {sound_id}"
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
                    mode = 1 if op == 0x0A else 0
                    if mode == 0:
                        other.activate()
                        other.last_event = f"activated by A{actor.index}"
                    else:
                        other.deactivate()
                        other.last_event = f"deactivated by A{actor.index}"
                    actor.last_event = f"A{target} mode={mode}"
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
        remaining = actor.loop_counters.get(op, 0) - 1
        actor.loop_counters[op] = remaining
        if remaining == 0:
            return next_pc
        if remaining < 0:
            actor.loop_counters[op] = count & 0xFFFF
            return target
        return target

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

    def runtime_tiles(self) -> list[int]:
        """Return a copy of the current room collision tiles."""
        return list(self._runtime_tiles())

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

        for platform in parse_platform_triplets(self.room):
            if not platform.visible:
                continue
            offset = self.platform_render_offset(platform)
            if offset == (0, 0):
                continue  # at rest: base tiles already hold it
            # Collision follows the platform's current (gradually moving) cells.
            clear_cells(self._platform_footprint_cells(platform, offset=(0, 0)))
            write_cells(self._platform_footprint_cells(platform, offset=offset))

        active_conveyors = self.active_target_indices("conveyor")
        if active_conveyors:
            for cv in parse_conveyor_visual_records(self.room):
                if cv.index not in active_conveyors:
                    continue
                for x, y in cv.cells:
                    if 0 <= x < ROOM_COLUMNS and 0 <= y < ROOM_ROWS:
                        idx = y * ROOM_COLUMNS + x
                        tiles[idx] = CONVEYOR_TILE_TOGGLE.get(tiles[idx], tiles[idx])

        for block in self.green_blocks:
            # AEPROG keeps the block's invisible-solid tiles only at its current
            # position.  Our stored terrain bakes them at the default spot, so
            # clear *both* candidate positions before writing the live one;
            # otherwise teleporting the block leaves a stale invisible wall.
            clear_cells(_green_block_footprint_cells(block, alternate=False))
            clear_cells(_green_block_footprint_cells(block, alternate=True))
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
