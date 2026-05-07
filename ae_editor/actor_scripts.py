"""Actor bytecode disassembler and conservative path/branch summarizer.

Actors are runtime VM objects stored in the level-part actor block.  Each
0x20-byte actor record points into a shared bytecode stream.  This module does
not edit scripts yet; it gives the renderer/editor a truthful disassembly and a
safe, best-effort path summary for the future Actors tab.

Research pass 2026-05 update:

* Actor conditions 0x13..0x1B are guards for the immediately following VM
  command.  If the condition is true, the next command executes; if false, the
  VM skips exactly that one command.
* Unconditional jumps are real control-flow changes.  Bytes after a jump often
  belong to another actor entry point, so a script summarizer must not keep
  scanning linearly after a reachable jump.
* Common movement is encoded as ``0E dx dy frame_delta`` followed by one of the
  counted loop opcodes ``04/05/06`` jumping back to that move.  For display we
  fold that pair into one human segment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque

from .room_payload import ACTOR_TABLE_OFFSET, ActorTableRecord
from .actor_dsl import decode_entry_until_stop, ActorScriptError, ActorRecordIR


@dataclass(frozen=True)
class ActorScriptCommand:
    offset: int
    opcode: int
    raw: bytes
    label: str


@dataclass(frozen=True)
class ActorPathSegment:
    offset: int
    dx: int
    dy: int
    frame_delta_packed: int
    duration: int
    timing_opcode: int | None
    timing_rel: int | None

    @property
    def frame_delta(self) -> int:
        return self.frame_delta_packed & 0x7F

    @property
    def variant_bit(self) -> int:
        return 1 if (self.frame_delta_packed & 0x80) else 0

    # Backward-compatible name used by older overlay code/status text.
    @property
    def flags(self) -> int:
        return self.frame_delta_packed

    @property
    def total_dx(self) -> int:
        return self.dx * max(1, self.duration)

    @property
    def total_dy(self) -> int:
        return self.dy * max(1, self.duration)

    @property
    def label(self) -> str:
        op = "--" if self.timing_opcode is None else f"{self.timing_opcode:02X}"
        rel = "" if self.timing_rel is None else f" rel={self.timing_rel:+d}"
        return (
            f"move dx={self.dx:+d} dy={self.dy:+d} ×{self.duration} "
            f"frame+={self.frame_delta} variant={self.variant_bit} loop_op={op}{rel}"
        )

    @property
    def human_label(self) -> str:
        if self.dx == 0 and self.dy == 0:
            verb = "idle/animate" if self.frame_delta else "wait"
            return f"{verb} ×{self.duration}"
        parts: list[str] = []
        if self.dx:
            parts.append(("right" if self.dx > 0 else "left") + f" {abs(self.total_dx)} px")
        if self.dy:
            parts.append(("down" if self.dy > 0 else "up") + f" {abs(self.total_dy)} px")
        return f"move {' and '.join(parts)} over {self.duration} ticks"


@dataclass(frozen=True)
class ActorPathTrace:
    """One possible route through an actor script branch graph."""

    points: list[tuple[int, int]]
    segments: list[ActorPathSegment]
    conditions: tuple[str, ...] = field(default_factory=tuple)
    loop_detected: bool = False
    truncated: bool = False

    @property
    def label(self) -> str:
        cond = "" if not self.conditions else " when " + " and ".join(self.conditions[:3])
        if len(self.conditions) > 3:
            cond += " ..."
        segs = "; ".join(seg.human_label for seg in self.segments[:4])
        if len(self.segments) > 4:
            segs += " ..."
        loop = " loop" if self.loop_detected else ""
        return f"{segs or 'no movement'}{cond}{loop}"


@dataclass(frozen=True)
class DecodedActorScript:
    actor_index: int
    script_offset: int
    start_absolute: int
    commands: list[ActorScriptCommand]
    segments: list[ActorPathSegment]
    points: list[tuple[int, int]]
    traces: list[ActorPathTrace] = field(default_factory=list)
    truncated: bool = False
    loop_detected: bool = False
    entry_dsl: str = ""
    actor_record_dsl: str = ""

    @property
    def summary(self) -> str:
        if self.traces:
            moving = [trace for trace in self.traces if trace.segments]
            if len(moving) == 1:
                return f"behavior: {moving[0].label}"
            if moving:
                parts = "; ".join(f"branch {i + 1}: {trace.label}" for i, trace in enumerate(moving[:3]))
                suffix = " ..." if len(moving) > 3 else ""
                return f"behavior: {parts}{suffix}"
        if not self.commands:
            return "script=?"
        if not self.segments:
            first = "; ".join(cmd.label for cmd in self.commands[:4])
            suffix = " ..." if len(self.commands) > 4 or self.truncated else ""
            return f"script: {first}{suffix}"
        segs = "; ".join(seg.label for seg in self.segments[:4])
        suffix = " ..." if len(self.segments) > 4 or self.truncated else ""
        loop = " loop" if self.loop_detected else ""
        return f"path: {segs}{suffix}{loop}"


def _s8(value: int) -> int:
    return value - 0x100 if value & 0x80 else value


def _s16(lo: int, hi: int) -> int:
    value = lo | (hi << 8)
    return value - 0x10000 if value & 0x8000 else value


def _u16(lo: int, hi: int) -> int:
    return lo | (hi << 8)


def _relative_target(pc: int, instruction_size: int, rel: int) -> int:
    """Actor VM relative branches are relative to the next instruction."""
    return pc + instruction_size + rel


def actor_script_bytes(part, actor: ActorTableRecord, limit: int = 192) -> tuple[int, bytes]:
    raw = getattr(part, "raw", b"")
    start = ACTOR_TABLE_OFFSET + actor.script_offset
    if start < 0 or start >= len(raw):
        return start, b""
    return start, bytes(raw[start:start + limit])


def _command_size(data: bytes, pc: int) -> int:
    """Return the byte length of a known actor VM instruction."""
    opcode = data[pc]
    fixed = {
        0x00: 1,  # yield/end current tick; all-zero tail is padding
        0x01: 3,  # relative jump
        0x02: 3,  # call-like branch
        0x03: 1,  # return from saved pc
        0x04: 5,  # counted loop A: rel16,count16
        0x05: 5,  # counted loop B
        0x06: 5,  # counted loop C
        0x07: 2,  # sound/effect event
        0x08: 2,  # special event
        0x09: 2,  # special trigger/event
        0x0A: 2,  # set referenced actor mode/type=1
        0x0B: 2,  # set referenced actor mode/type=0
        0x0C: 3,  # frame range
        0x0D: 2,  # set packed frame/current pose
        0x0E: 4,  # relative move + animate
        0x0F: 4,  # absolute position + animate
        0x10: 5,  # absolute position + packed frame + room
        0x11: 1,  # hide actor and yield
        0x12: 1,  # show actor
        0x13: 3,  # if runtime[offset] & 0x07 set
        0x14: 3,  # if runtime[offset] & 0x07 clear
        0x15: 3,  # if runtime[offset] & 0x10 clear
        0x16: 3,  # if runtime[offset] & 0x10 set
        0x17: 2,  # if player_x > x_raw*2
        0x18: 2,  # if player_x < x_raw*2
        0x19: 2,  # if player_y > y
        0x1A: 2,  # if player_y < y
        0x1B: 2,  # random condition
    }.get(opcode, 1)
    return min(fixed, max(1, len(data) - pc))


def _actor_ref_label(value: int) -> str:
    if value < 0x80:
        return f"A{value}"
    return f"A+{value & 0x7F}"


def _condition_text(cmd: ActorScriptCommand) -> str:
    label = cmd.label
    if label.startswith("if ") and " then next_cmd" in label:
        return label[3:].replace(" then next_cmd", "")
    return label


def _decode_command(data: bytes, pc: int) -> ActorScriptCommand:
    opcode = data[pc]
    size = _command_size(data, pc)
    raw = data[pc:pc + size]

    def b(i: int, default: int = 0) -> int:
        return raw[i] if i < len(raw) else default

    label = f"op_{opcode:02X}"
    if opcode == 0x00:
        label = "yield/end_tick"
    elif opcode == 0x01 and len(raw) >= 3:
        rel = _s16(b(1), b(2))
        label = f"jump rel={rel:+d} -> {_relative_target(pc, len(raw), rel):04X}"
    elif opcode == 0x02 and len(raw) >= 3:
        rel = _s16(b(1), b(2))
        label = f"call rel={rel:+d} -> {_relative_target(pc, len(raw), rel):04X}"
    elif opcode == 0x03:
        label = "return saved_pc"
    elif opcode in {0x04, 0x05, 0x06} and len(raw) >= 5:
        rel = _s16(b(1), b(2))
        label = f"loop_{chr(ord('A') + opcode - 4)} rel={rel:+d} -> {_relative_target(pc, len(raw), rel):04X} count={_u16(b(3), b(4))}"
    elif opcode in {0x07, 0x08, 0x09} and len(raw) >= 2:
        label = f"event_{opcode:02X} id={b(1)}"
    elif opcode in {0x0A, 0x0B} and len(raw) >= 2:
        mode = 1 if opcode == 0x0A else 0
        label = f"set_actor_mode {_actor_ref_label(b(1))}={mode}"
    elif opcode == 0x0C and len(raw) >= 3:
        label = f"frame_range {b(1):02X}-{b(2):02X}"
    elif opcode == 0x0D and len(raw) >= 2:
        label = f"set_frame {b(1) & 0x7F:02X} variant={(b(1) >> 7)} raw={b(1):02X}"
    elif opcode == 0x0E and len(raw) >= 4:
        fd = b(3)
        label = f"move dx={_s8(b(1)):+d} dy={_s8(b(2)):+d} frame+={fd & 0x7F} variant={fd >> 7}"
    elif opcode == 0x0F and len(raw) >= 4:
        fd = b(3)
        label = f"set_pos x={b(1) * 2} y={b(2)} frame+={fd & 0x7F} variant={fd >> 7}"
    elif opcode == 0x10 and len(raw) >= 5:
        label = f"set_pos_room x={b(1) * 2} y={b(2)} frame={b(3):02X} room={b(4)}"
    elif opcode == 0x11:
        label = "hide_actor yield"
    elif opcode == 0x12:
        label = "show_actor"
    elif opcode in {0x13, 0x14, 0x15, 0x16} and len(raw) >= 3:
        off = _u16(b(1), b(2))
        tests = {
            0x13: "tile is solid",
            0x14: "tile is passable",
            0x15: "conveyor tile is grey",
            0x16: "conveyor tile is teal",
        }
        label = f"if {tests[opcode]} offset={off:04X} then next_cmd"
    elif opcode in {0x17, 0x18, 0x19, 0x1A} and len(raw) >= 2:
        tests = {
            0x17: f"player_x > {b(1) * 2}",
            0x18: f"player_x < {b(1) * 2}",
            0x19: f"player_y > {b(1)}",
            0x1A: f"player_y < {b(1)}",
        }
        label = f"if {tests[opcode]} then next_cmd"
    elif opcode == 0x1B and len(raw) >= 2:
        label = f"if random threshold={b(1)} then next_cmd"
    return ActorScriptCommand(pc, opcode, raw, label)


def _is_padding_end(data: bytes, pc: int) -> bool:
    return data[pc] == 0x00 and not any(data[pc + 1:pc + 8])


def _folded_move_segment(data: bytes, pc: int) -> tuple[ActorPathSegment, int] | None:
    """Fold ``move`` + counted-loop-back into one display segment.

    Returns ``(segment, next_pc_after_timing_loop)``.
    """
    if pc >= len(data) or data[pc] != 0x0E or pc + 3 >= len(data):
        return None
    raw = data[pc:pc + 4]
    dx = _s8(raw[1])
    dy = _s8(raw[2])
    packed = raw[3]
    duration = 1
    timing_opcode: int | None = None
    timing_rel: int | None = None
    next_pc = pc + 4
    if next_pc < len(data) and data[next_pc] in {0x04, 0x05, 0x06} and next_pc + 4 < len(data):
        rel = _s16(data[next_pc + 1], data[next_pc + 2])
        target = _relative_target(next_pc, 5, rel)
        # The common timing form loops straight back to this move instruction.
        # Do not treat it as a control-flow branch for path preview; it is the
        # duration of this one movement segment.
        if target == pc:
            timing_opcode = data[next_pc]
            timing_rel = rel
            duration = max(1, _u16(data[next_pc + 3], data[next_pc + 4]))
            next_pc += 5
    return ActorPathSegment(pc, dx, dy, packed, duration, timing_opcode, timing_rel), next_pc


def _branch_successors(data: bytes, pc: int, cmd: ActorScriptCommand) -> list[int]:
    """Reachable successor PCs for a decoded command, ignoring movement state."""
    end = pc + len(cmd.raw)
    if cmd.opcode == 0x01 and len(cmd.raw) >= 3:
        return [_relative_target(pc, len(cmd.raw), _s16(cmd.raw[1], cmd.raw[2]))]
    if cmd.opcode == 0x02 and len(cmd.raw) >= 3:
        # Calls need a full call stack for exact runtime, but for disassembly it
        # is useful to visit both the callee and the fall-through return site.
        return [_relative_target(pc, len(cmd.raw), _s16(cmd.raw[1], cmd.raw[2])), end]
    if 0x13 <= cmd.opcode <= 0x1B:
        if end >= len(data):
            return []
        skipped = end + _command_size(data, end)
        return [end, skipped]
    if cmd.opcode == 0x03:
        return []
    if _is_padding_end(data, pc):
        return []
    return [end]


def _collect_reachable_commands(data: bytes, *, max_commands: int = 160) -> tuple[list[ActorScriptCommand], bool]:
    commands: dict[int, ActorScriptCommand] = {}
    truncated = False
    queue: deque[int] = deque([0])
    while queue and len(commands) < max_commands:
        pc = queue.popleft()
        if pc < 0 or pc >= len(data) or pc in commands:
            continue
        cmd = _decode_command(data, pc)
        commands[pc] = cmd
        if _is_padding_end(data, pc):
            continue
        # Include folded loop command in the disassembly even when path preview
        # treats it as duration.
        if cmd.opcode == 0x0E:
            folded = _folded_move_segment(data, pc)
            if folded is not None:
                _seg, after = folded
                loop_pc = pc + len(cmd.raw)
                if loop_pc < after and loop_pc < len(data):
                    commands.setdefault(loop_pc, _decode_command(data, loop_pc))
                queue.append(after)
                continue
        for nxt in _branch_successors(data, pc, cmd):
            if 0 <= nxt < len(data):
                queue.append(nxt)
    if queue:
        truncated = True
    return [commands[pc] for pc in sorted(commands)], truncated


def _explore_path_traces(
    data: bytes,
    actor: ActorTableRecord,
    *,
    max_traces: int = 12,
    max_depth: int = 80,
    max_segments: int = 16,
) -> tuple[list[ActorPathTrace], bool, bool]:
    traces: list[ActorPathTrace] = []
    truncated = False
    any_loop = False

    def append_trace(points, segments, conditions, *, loop=False, trunc=False):
        nonlocal any_loop, truncated
        if len(traces) >= max_traces:
            truncated = True
            return
        any_loop = any_loop or loop
        truncated = truncated or trunc
        traces.append(
            ActorPathTrace(
                points=list(points),
                segments=list(segments),
                conditions=tuple(conditions),
                loop_detected=loop,
                truncated=trunc,
            )
        )

    def visit(pc: int, x: int, y: int, points, segments, conditions, seen: set[int], depth: int):
        nonlocal truncated, any_loop
        if len(traces) >= max_traces:
            truncated = True
            return
        if depth > max_depth or len(segments) >= max_segments:
            append_trace(points, segments, conditions, trunc=True)
            return
        if pc < 0 or pc >= len(data):
            append_trace(points, segments, conditions, trunc=True)
            return
        if pc in seen:
            append_trace(points, segments, conditions, loop=True)
            return
        if _is_padding_end(data, pc):
            append_trace(points, segments, conditions)
            return

        cmd = _decode_command(data, pc)
        next_pc = pc + len(cmd.raw)
        local_seen = set(seen)
        local_seen.add(pc)

        if cmd.opcode == 0x0E:
            folded = _folded_move_segment(data, pc)
            if folded is not None:
                seg, after = folded
                nx = x + seg.total_dx
                ny = y + seg.total_dy
                visit(after, nx, ny, points + [(nx, ny)], segments + [seg], conditions, local_seen, depth + 1)
                return

        if cmd.opcode == 0x0F and len(cmd.raw) >= 4:
            fd = cmd.raw[3]
            nx = cmd.raw[1] * 2
            ny = cmd.raw[2]
            seg = ActorPathSegment(pc, nx - x, ny - y, fd, 1, None, None)
            visit(next_pc, nx, ny, points + [(nx, ny)], segments + [seg], conditions, local_seen, depth + 1)
            return

        if cmd.opcode == 0x10 and len(cmd.raw) >= 5:
            nx = cmd.raw[1] * 2
            ny = cmd.raw[2]
            seg = ActorPathSegment(pc, nx - x, ny - y, cmd.raw[3], 1, None, None)
            visit(next_pc, nx, ny, points + [(nx, ny)], segments + [seg], conditions, local_seen, depth + 1)
            return

        if cmd.opcode == 0x01 and len(cmd.raw) >= 3:
            target = _relative_target(pc, len(cmd.raw), _s16(cmd.raw[1], cmd.raw[2]))
            if target in local_seen:
                append_trace(points, segments, conditions, loop=True)
            else:
                visit(target, x, y, points, segments, conditions, local_seen, depth + 1)
            return

        if 0x13 <= cmd.opcode <= 0x1B:
            cond = _condition_text(cmd)
            if next_pc < len(data):
                skipped = next_pc + _command_size(data, next_pc)
                # True: execute the guarded next command.
                visit(next_pc, x, y, points, segments, conditions + [cond], local_seen, depth + 1)
                # False: skip exactly that command.
                visit(skipped, x, y, points, segments, conditions + [f"not({cond})"], local_seen, depth + 1)
            else:
                append_trace(points, segments, conditions, trunc=True)
            return

        if cmd.opcode == 0x02 and len(cmd.raw) >= 3:
            # For path preview, show both possible continuations instead of
            # pretending calls are linear.  A future actor editor can add an
            # explicit call stack if needed.
            target = _relative_target(pc, len(cmd.raw), _s16(cmd.raw[1], cmd.raw[2]))
            visit(target, x, y, points, segments, conditions + ["call branch"], local_seen, depth + 1)
            visit(next_pc, x, y, points, segments, conditions + ["call return site"], local_seen, depth + 1)
            return

        if cmd.opcode == 0x03:
            append_trace(points, segments, conditions)
            return

        # Yield is not a structural end of the script unless it is padding.
        visit(next_pc, x, y, points, segments, conditions, local_seen, depth + 1)

    visit(0, actor.x, actor.y, [(actor.x, actor.y)], [], [], set(), 0)
    return traces, truncated, any_loop


def decode_actor_script(part, actor: ActorTableRecord, *, max_bytes: int = 192, max_segments: int = 16) -> DecodedActorScript:
    """Disassemble actor VM bytes and summarize reachable movement branches.

    The branch-aware path summary follows unconditional jumps and explores both
    sides of condition-guarded commands.  This avoids the old two opposite
    mistakes: reading unrelated bytes after a jump as if they belonged to the
    current actor, and hiding conditional routes such as the L01R01 bat's long
    route behind P0.
    """
    start, data = actor_script_bytes(part, actor, max_bytes)
    if not data:
        return DecodedActorScript(actor.index, actor.script_offset, start, [], [], [(actor.x, actor.y)], [], entry_dsl="", actor_record_dsl=ActorRecordIR.from_record(actor).to_dsl(actor.confirmed_name))

    commands, cmd_truncated = _collect_reachable_commands(data)
    traces, trace_truncated, loop_detected = _explore_path_traces(data, actor, max_segments=max_segments)

    # Flatten segments for older GUI/status code while keeping traces for the
    # overlay and future Actors tab.
    segments: list[ActorPathSegment] = []
    for trace in traces:
        for seg in trace.segments:
            if len(segments) >= max_segments:
                break
            segments.append(seg)
        if len(segments) >= max_segments:
            break

    # Backward-compatible primary point list: choose the longest movement trace.
    points = [(actor.x, actor.y)]
    if traces:
        points = max(traces, key=lambda tr: (len(tr.segments), len(tr.points))).points

    try:
        entry_dsl = decode_entry_until_stop(data, 0).to_dsl()
    except ActorScriptError as exc:
        entry_dsl = f"# actor DSL decode error: {exc}\n"
    actor_record_dsl = ActorRecordIR.from_record(actor).to_dsl(actor.confirmed_name)

    return DecodedActorScript(
        actor.index,
        actor.script_offset,
        start,
        commands,
        segments,
        points,
        traces,
        truncated=cmd_truncated or trace_truncated,
        loop_detected=loop_detected,
        entry_dsl=entry_dsl,
        actor_record_dsl=actor_record_dsl,
    )
