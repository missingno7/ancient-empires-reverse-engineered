"""Experimental actor movement script decoder.

The game actors do not appear to use pathfinding AI.  Actor table records point
into a small bytecode stream inside the same difficulty-part actor block.  This
module decodes the parts we can recognize safely enough for editor overlays:
movement vectors, dwell/update durations, animation frame changes and obvious
loop/jump markers.

The decoder is intentionally conservative.  Unknown opcodes are preserved as
commands, but they are not allowed to move the actor.  That lets the editor show
useful path probes without pretending the full script VM is solved.
"""
from __future__ import annotations

from dataclasses import dataclass

from .room_payload import ACTOR_TABLE_OFFSET, ActorTableRecord


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
    flags: int
    duration: int
    timing_opcode: int | None
    timing_rel: int | None

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
        return f"move dx={self.dx:+d} dy={self.dy:+d} t={self.duration} flags={self.flags:02X} op={op}{rel}"


@dataclass(frozen=True)
class DecodedActorScript:
    actor_index: int
    script_offset: int
    start_absolute: int
    commands: list[ActorScriptCommand]
    segments: list[ActorPathSegment]
    points: list[tuple[int, int]]
    truncated: bool = False
    loop_detected: bool = False

    @property
    def summary(self) -> str:
        if not self.segments:
            return "path=?"
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


def actor_script_bytes(part, actor: ActorTableRecord, limit: int = 192) -> tuple[int, bytes]:
    raw = getattr(part, "raw", b"")
    start = ACTOR_TABLE_OFFSET + actor.script_offset
    if start < 0 or start >= len(raw):
        return start, b""
    # Scripts live in the actor block after the 0x20-byte records.  Staying
    # inside the part blob avoids overreading if a guessed offset is wrong.
    return start, bytes(raw[start:start + limit])


def decode_actor_script(part, actor: ActorTableRecord, *, max_bytes: int = 192, max_segments: int = 16) -> DecodedActorScript:
    """Decode the currently known subset of an actor movement script.

    Known movement pattern observed in many enemies::

        0E dx dy flags 04/05 rel_lo rel_hi duration_lo duration_hi

    `dx` and `dy` are signed per-tick deltas.  The following timing opcode gives
    a loop-relative address plus the number of update ticks, so the editor can
    estimate the next waypoint as `current + delta * duration`.  This is enough
    to visualize patrol paths for snakes, spiders, bats, ladybugs, etc.
    """
    start, data = actor_script_bytes(part, actor, max_bytes)
    commands: list[ActorScriptCommand] = []
    segments: list[ActorPathSegment] = []
    points: list[tuple[int, int]] = [(actor.x, actor.y)]
    pc = 0
    seen: set[int] = set()
    truncated = False
    loop_detected = False

    while pc < len(data) and len(segments) < max_segments:
        if pc in seen:
            loop_detected = True
            break
        seen.add(pc)
        opcode = data[pc]

        # Padding / script terminator.  Many scripts end with zero-filled bytes;
        # do not keep scanning into the next script by accident.  Some actor
        # families (notably spiders) also use opcode 0x00 as a timed wait, so
        # only treat it as padding when the following bytes are empty too.
        if opcode == 0x00 and not any(data[pc + 1:pc + 6]):
            commands.append(ActorScriptCommand(pc, opcode, data[pc:pc + 1], "end/pad"))
            break

        if opcode == 0x0E and pc + 3 < len(data):
            dx = _s8(data[pc + 1])
            dy = _s8(data[pc + 2])
            flags = data[pc + 3]
            raw_end = pc + 4
            duration = actor.delay or 1
            timing_opcode: int | None = None
            timing_rel: int | None = None
            if raw_end + 4 < len(data) and data[raw_end] in {0x04, 0x05}:
                timing_opcode = data[raw_end]
                timing_rel = _s16(data[raw_end + 1], data[raw_end + 2])
                duration = max(1, _u16(data[raw_end + 3], data[raw_end + 4]))
                raw_end += 5
            raw = data[pc:raw_end]
            segment = ActorPathSegment(pc, dx, dy, flags, duration, timing_opcode, timing_rel)
            segments.append(segment)
            commands.append(ActorScriptCommand(pc, opcode, raw, segment.label))
            last_x, last_y = points[-1]
            points.append((last_x + segment.total_dx, last_y + segment.total_dy))
            pc = raw_end
            continue

        if opcode == 0x0D and pc + 1 < len(data):
            # Set current animation frame / pose.  Two-byte form is the one
            # observed in spider scripts; older versions incorrectly consumed an
            # extra byte and lost the following movement opcode.
            raw = data[pc:pc + 2]
            commands.append(ActorScriptCommand(pc, opcode, raw, f"frame {data[pc + 1]:02X}"))
            pc += 2
            continue

        if opcode == 0x0C and pc + 2 < len(data):
            raw = data[pc:pc + 3]
            commands.append(ActorScriptCommand(pc, opcode, raw, f"frame_range {data[pc + 1]:02X}-{data[pc + 2]:02X}"))
            pc += 3
            continue

        if opcode == 0x09 and pc + 1 < len(data):
            raw = data[pc:pc + 2]
            commands.append(ActorScriptCommand(pc, opcode, raw, f"trigger {data[pc + 1]}"))
            pc += 2
            continue

        if opcode == 0x00 and pc + 5 < len(data) and data[pc + 1] in {0x04, 0x05}:
            rel = _s16(data[pc + 2], data[pc + 3])
            duration = max(1, _u16(data[pc + 4], data[pc + 5]))
            raw = data[pc:pc + 6]
            commands.append(ActorScriptCommand(pc, opcode, raw, f"wait rel={rel:+d} t={duration}"))
            pc += 6
            continue

        if opcode == 0x01 and pc + 2 < len(data):
            rel = _s16(data[pc + 1], data[pc + 2])
            raw = data[pc:pc + 3]
            commands.append(ActorScriptCommand(pc, opcode, raw, f"jump rel={rel:+d}"))
            if rel < 0:
                loop_detected = True
                break
            pc += 3
            continue

        if opcode in {0x04, 0x05} and pc + 4 < len(data):
            rel = _s16(data[pc + 1], data[pc + 2])
            duration = max(1, _u16(data[pc + 3], data[pc + 4]))
            raw = data[pc:pc + 5]
            commands.append(ActorScriptCommand(pc, opcode, raw, f"wait/jump rel={rel:+d} t={duration}"))
            pc += 5
            continue

        raw = data[pc:pc + 1]
        commands.append(ActorScriptCommand(pc, opcode, raw, f"op {opcode:02X}"))
        pc += 1

    if pc < len(data) and len(segments) >= max_segments:
        truncated = True

    return DecodedActorScript(
        actor_index=actor.index,
        script_offset=actor.script_offset,
        start_absolute=start,
        commands=commands,
        segments=segments,
        points=points,
        truncated=truncated,
        loop_detected=loop_detected,
    )
