from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .constants import CELL_SIZE, ROOM_COLUMNS, ROOM_ROWS
from .level_format import Room

ROOM_WIDTH_PX = ROOM_COLUMNS * CELL_SIZE
ROOM_HEIGHT_PX = ROOM_ROWS * CELL_SIZE


@dataclass
class PayloadPoint:
    """A point-like item found in the 314-byte room payload.

    This is intentionally named PayloadPoint rather than Object: we know this
    area contains object/trigger/decorator/control data, but the exact schemas
    are still being reverse-engineered.
    """

    source_offset: int
    schema: str
    x: int
    y: int
    type_id: int | None = None
    subtype: int | None = None
    raw: bytes = b""
    label: str = ""

    @property
    def tile_x(self) -> float:
        return self.x / CELL_SIZE

    @property
    def tile_y(self) -> float:
        return self.y / CELL_SIZE


@dataclass
class PayloadCandidateTable:
    offset: int
    schema: str
    count: int
    score: int
    points: list[PayloadPoint]


@dataclass
class ParsedRoomPayload:
    leading_triplets: list[PayloadPoint]
    candidate_tables: list[PayloadCandidateTable]

    @property
    def best_table(self) -> PayloadCandidateTable | None:
        if not self.candidate_tables:
            return None
        return max(self.candidate_tables, key=lambda c: (c.score, len(c.points)))


def _inside(x: int, y: int, margin: int = 16) -> bool:
    return -margin <= x < ROOM_WIDTH_PX + margin and -margin <= y < ROOM_HEIGHT_PX + margin


def parse_room_payload(room: Room) -> ParsedRoomPayload:
    """Probe the unknown trailing payload after the 38x18 terrain grid.

    Current observations:
    - the first 6 bytes often behave like two 3-byte state/position tuples;
      in page A/B they change when a moving platform changes position.
    - later bytes contain one or more count-prefixed tables.  At least two
      layouts appear in early rooms:
        * compact3: count, then N*(x, y, type)
        * typed6:   count, then N*(type, subtype, x, y, a, b)

    The function returns candidates instead of committing to a single schema.
    """

    data = room.trailing
    leading: list[PayloadPoint] = []
    for i in range(0, min(6, len(data) - 2), 3):
        flags, x, y = data[i], data[i + 1], data[i + 2]
        if flags or x or y:
            leading.append(
                PayloadPoint(
                    source_offset=i,
                    schema="leading_triplet",
                    x=x,
                    y=y,
                    type_id=flags,
                    raw=data[i:i + 3],
                    label=f"lead {i//3}: f={flags:02X} x={x} y={y}",
                )
            )

    candidates: list[PayloadCandidateTable] = []
    candidates.extend(_scan_compact3(data))
    candidates.extend(_scan_typed6(data))
    candidates.sort(key=lambda c: (c.score, len(c.points)), reverse=True)
    return ParsedRoomPayload(leading, candidates[:12])


def _scan_compact3(data: bytes) -> Iterable[PayloadCandidateTable]:
    for off in range(0, min(0x80, len(data))):
        count = data[off]
        if not 1 <= count <= 12:
            continue
        start = off + 1
        end = start + count * 3
        if end > len(data):
            continue
        points: list[PayloadPoint] = []
        score = 0
        nonzero = 0
        for n in range(count):
            raw = data[start + n * 3:start + n * 3 + 3]
            x, y, typ = raw[0], raw[1], raw[2]
            if any(raw):
                nonzero += 1
            if _inside(x, y):
                score += 3
            if x % 8 == 0 or y % 8 == 0:
                score += 1
            if typ < 0x40:
                score += 1
            points.append(
                PayloadPoint(
                    source_offset=start + n * 3,
                    schema="compact3",
                    x=x,
                    y=y,
                    type_id=typ,
                    raw=raw,
                    label=f"c3[{n}] type={typ:02X} x={x} y={y}",
                )
            )
        if nonzero >= max(1, count // 2) and score >= count * 3:
            bonus = 10 if off in (0x1F, 0x23) else (3 if off in (0x20, 0x24) else 0)
            candidatescore = score + bonus
            yield PayloadCandidateTable(off, "compact3", count, candidatescore, points)


def _scan_typed6(data: bytes) -> Iterable[PayloadCandidateTable]:
    for off in range(0, min(0x80, len(data))):
        count = data[off]
        if not 1 <= count <= 12:
            continue
        start = off + 1
        end = start + count * 6
        if end > len(data):
            continue
        points: list[PayloadPoint] = []
        score = 0
        nonzero = 0
        for n in range(count):
            raw = data[start + n * 6:start + n * 6 + 6]
            typ, sub, x, y, a, b = raw
            if any(raw):
                nonzero += 1
            if not any(raw):
                score -= 8
            if _inside(x, y):
                score += 4
            if typ < 0x20:
                score += 3
            else:
                score -= 4
            if sub < 0x10:
                score += 2
            else:
                score -= 3
            if x % 8 == 0 or y % 8 == 0:
                score += 1
            points.append(
                PayloadPoint(
                    source_offset=start + n * 6,
                    schema="typed6",
                    x=x,
                    y=y,
                    type_id=typ,
                    subtype=sub,
                    raw=raw,
                    label=f"t6[{n}] type={typ:02X}/{sub:02X} x={x} y={y} a={a:02X} b={b:02X}",
                )
            )
        if nonzero >= max(1, count // 2) and score >= count * 4:
            bonus = 14 if off == 0x1F else (8 if off == 0x23 else (2 if off in (0x20, 0x24) else 0))
            candidatescore = score + bonus
            yield PayloadCandidateTable(off, "typed6", count, candidatescore, points)
