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
    # v21: the platform/control prefix is not always just two triplets.
    # L2 room 0 page B starts with five triplets before the zero padding:
    #   A0 80 60 / 40 30 48 / A0 70 60 / A0 78 60 / 80 90 20
    # Older builds only consumed the first 6 bytes, which made the visible
    # moving platforms appear missing or at the wrong place.  Stop at the
    # first all-zero triplet or at the known beginning of later tables.
    for i in range(0, min(0x1F, len(data) - 2), 3):
        flags, x, y = data[i], data[i + 1], data[i + 2]
        if flags == 0 and x == 0 and y == 0:
            break
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


@dataclass
class ObjectTableEntry:
    """A 3-byte room object/decor record from the trailing room payload.

    Best current interpretation for the early cavern rooms is:
        x_or_unit, y_px, code

    The x value is not fully uniform yet.  For many decoration entries it is
    a half-pixel coordinate (screen x = x_or_unit * 2).  Some gameplay entries
    with small x values appear to use tile units.  Renderer heuristics handle
    the observed cases but keep the raw values visible for research.
    """

    source_offset: int
    index: int
    x_raw: int
    y: int
    code: int
    raw: bytes

    @property
    def x_half_px(self) -> int:
        return self.x_raw * 2

    @property
    def x_tile_px(self) -> int:
        return self.x_raw * CELL_SIZE

    @property
    def label(self) -> str:
        return f"obj[{self.index}] code={self.code:02X} x={self.x_raw:02X} y={self.y:02X}"




KNOWN_DECOR_CODES = {0x02, 0x05, 0x09, 0x0E, 0x1A, 0x48, 0x49, 0x7D, 0x80, 0x88, 0x8E}


def parse_room_object_tables(room: Room) -> list[tuple[int, list[ObjectTableEntry]]]:
    """Return plausible count-prefixed compact3 object/decor tables.

    v20 picked one "best" table, which fails in rooms that contain both a
    control table and a later visible decoration table.  Example: level 2,
    room 0, page B has a strong visible compact3 table at payload +0x44:
        04 31 7B 1A 12 58 0E 15 1E 02 88 56 80
    This contains the vase (code 1A), a switch/button candidate (0E), a spider
    / enemy family entry (02), and the laser-trigger/pudding candidate (80).

    The function deliberately returns multiple tables so the renderer can draw
    known visual codes while the UI can still show raw data for research.
    """

    data = room.trailing
    out: list[tuple[int, list[ObjectTableEntry]]] = []
    for off in range(0x18, min(0x90, len(data))):
        count = data[off]
        if not 1 <= count <= 16:
            continue
        start = off + 1
        end = start + count * 3
        if end > len(data):
            continue
        entries: list[ObjectTableEntry] = []
        known = 0
        plausible = 0
        nonzero = 0
        for i in range(count):
            raw = data[start + i * 3:start + i * 3 + 3]
            x, y, code = raw
            if any(raw):
                nonzero += 1
            if code in KNOWN_DECOR_CODES:
                known += 1
            # Most compact3 visual records are either half-pixel x anchors or
            # small tile-ish actor positions. Keep this intentionally broad.
            if -32 <= x * 2 <= ROOM_WIDTH_PX + 96 and -48 <= y <= ROOM_HEIGHT_PX + 96:
                plausible += 1
            entries.append(ObjectTableEntry(start + i * 3, i, x, y, code, raw))
        if nonzero < max(1, count // 2):
            continue
        # Require at least one known visual code, or a very plausible all-on-screen table.
        if known == 0 and plausible < count:
            continue
        out.append((off, entries))
    # Prefer tables with many known codes, then canonical offsets observed so far.
    def score(item: tuple[int, list[ObjectTableEntry]]) -> tuple[int, int, int]:
        off, entries = item
        known = sum(1 for e in entries if e.code in KNOWN_DECOR_CODES)
        canonical = 3 if off in (0x23, 0x44) else (1 if off in (0x1F, 0x20, 0x24) else 0)
        return (known, canonical, len(entries))
    out.sort(key=score, reverse=True)
    return out[:4]

def parse_room_object_table(room: Room) -> list[ObjectTableEntry]:
    """Return the strongest known 3-byte object/decor table in a room.

    Observed examples:
    - L1 room 0 has count=03 at payload +0x23.
    - L1 room 2 has count=0A at payload +0x23.

    These records describe visible room items/decorations such as wall plaques,
    statues, crawlers/snakes, and probably additional trigger/control points.
    The exact code mapping is still incomplete, but the table location and the
    3-byte stride are now strong enough to treat it separately from terrain.
    """

    tables = parse_room_object_tables(room)
    if tables:
        return tables[0][1]

    data = room.trailing
    best: tuple[int, int, list[ObjectTableEntry]] | None = None
    # Strong prior from all verified early rooms.  Keep a fallback scan for
    # other rooms/levels where the table may shift slightly.
    offsets = [0x23, 0x1F, 0x20, 0x24] + list(range(0x18, 0x50))
    seen: set[int] = set()
    for off in offsets:
        if off in seen or off >= len(data):
            continue
        seen.add(off)
        count = data[off]
        if not 1 <= count <= 16:
            continue
        start = off + 1
        end = start + count * 3
        if end > len(data):
            continue
        entries: list[ObjectTableEntry] = []
        nonzero = 0
        score = 0
        for i in range(count):
            raw = data[start + i * 3:start + i * 3 + 3]
            x, y, code = raw
            if any(raw):
                nonzero += 1
            # Coarse plausibility.  x may be half-pixels or tile-ish units.
            if -16 <= x * 2 <= ROOM_WIDTH_PX + 80 or -16 <= x * CELL_SIZE <= ROOM_WIDTH_PX + 80:
                score += 2
            if -24 <= y <= ROOM_HEIGHT_PX + 80:
                score += 2
            if code in {0x00, 0x02, 0x05, 0x09, 0x48, 0x49, 0x88}:
                score += 3
            elif code < 0x90:
                score += 1
            entries.append(ObjectTableEntry(start + i * 3, i, x, y, code, raw))
        if nonzero < max(1, count // 2):
            continue
        if off == 0x23:
            score += 20
        elif off in (0x1F, 0x20, 0x24):
            score += 6
        if best is None or score > best[0]:
            best = (score, off, entries)
    return best[2] if best else []

# ---- v22: structures confirmed by static EXE disassembly -----------------

@dataclass
class PlatformTriplet:
    source_offset: int
    index: int
    flags: int
    x_raw: int
    y: int
    raw: bytes

    @property
    def active(self) -> bool:
        return (self.flags & 0x0F) != 0 or (self.flags & 0xF0) != 0

    @property
    def x_px_exe(self) -> int:
        # Kept for compatibility; canonical helper is coordinates.platform_xy().
        return self.x_raw * 2 - 4

    @property
    def label(self) -> str:
        return f"plat[{self.index}] f={self.flags:02X} x={self.x_raw:02X} y={self.y:02X}"


@dataclass
class Compact3Table:
    offset: int
    count: int
    entries: list[ObjectTableEntry]
    label: str = "compact3"


def parse_platform_triplets(room: Room) -> list[PlatformTriplet]:
    """Read the first ten 3-byte records at room + 0x2AC.

    This is no longer a heuristic.  The EXE routine at loaded-image offset
    0x25b3 iterates exactly ten records starting at current_room + 0x2AC,
    checks the low nibble as an active timer/state, and uses byte1/byte2 as
    X/Y for moving-platform control/collision updates.
    """
    data = room.trailing
    out: list[PlatformTriplet] = []
    for i in range(10):
        off = i * 3
        if off + 3 > len(data):
            break
        raw = data[off:off + 3]
        f, x, y = raw
        if raw == b"\x00\x00\x00":
            continue
        out.append(PlatformTriplet(off, i, f, x, y, raw))
    return out


def parse_counted_compact3_at(room: Room, off: int, *, max_count: int = 32) -> Compact3Table | None:
    data = room.trailing
    if off < 0 or off >= len(data):
        return None
    count = data[off]
    if not (0 <= count <= max_count):
        return None
    start = off + 1
    end = start + count * 3
    if end > len(data):
        return None
    entries = []
    for i in range(count):
        raw = data[start + i * 3:start + i * 3 + 3]
        entries.append(ObjectTableEntry(start + i * 3, i, raw[0], raw[1], raw[2], raw))
    return Compact3Table(off, count, entries)


def parse_visual_compact3_tables(room: Room) -> list[Compact3Table]:
    """Return likely visible count-prefixed 3-byte object/decor tables.

    Static EXE notes:
    - AEPROG 0x2bf7..0x2d9f draws compact3 tables as (x, y, code).
    - X is doubled before blitting.
    - Records with code >= 0x80 are drawn in the first pass using a sprite
      pointer table at EXE data 0x72b2.
    - A second pass draws code < 0x80 from the same table.

    The surrounding section directory is still partially unknown, so this
    returns canonical offsets observed in verified rooms plus scored fallbacks.
    """
    candidates: list[Compact3Table] = []
    # Canonical offsets observed in verified rooms:
    # 0x23: level 1 room 2 decor/enemies
    # 0x44: level 2 room 0 page B vase/button/spider/laser
    # 0x47: level 20 room 0 page A decor
    for off in (0x23, 0x44, 0x47):
        table = parse_counted_compact3_at(room, off)
        if table and table.count:
            candidates.append(table)
    # Broad fallback: require enough plausible coordinates and at least one
    # known-ish code or high-bit EXE visual code.
    for off in range(0x1F, min(0x90, len(room.trailing))):
        table = parse_counted_compact3_at(room, off, max_count=16)
        if not table or not table.count:
            continue
        if any(t.offset == table.offset for t in candidates):
            continue
        plausible = 0
        signal = 0
        for e in table.entries:
            if -32 <= e.x_raw * 2 <= ROOM_WIDTH_PX + 96 and -64 <= e.y <= ROOM_HEIGHT_PX + 128:
                plausible += 1
            if e.code >= 0x80 or e.code in KNOWN_DECOR_CODES or e.code in {0x0E, 0x1A, 0x7D, 0x93, 0x12, 0x04}:
                signal += 1
        if plausible >= max(1, table.count // 2) and signal:
            candidates.append(table)
    # De-duplicate overlapping false positives: favor canonical offsets and
    # tables with more signal entries.
    def table_score(t: Compact3Table) -> tuple[int, int, int]:
        canonical = {0x23: 5, 0x44: 5, 0x47: 4}.get(t.offset, 0)
        signal = sum(1 for e in t.entries if e.code >= 0x80 or e.code in KNOWN_DECOR_CODES)
        return (canonical, signal, t.count)
    candidates.sort(key=table_score, reverse=True)
    out: list[Compact3Table] = []
    occupied: set[int] = set()
    for t in candidates:
        span = set(range(t.offset, t.offset + 1 + t.count * 3))
        # Keep canonical tables even if overlap; otherwise suppress scans inside
        # an already selected canonical table.
        if t.offset not in {0x23, 0x44, 0x47} and len(span & occupied) > 2:
            continue
        out.append(t)
        occupied |= span
        if len(out) >= 5:
            break
    return out
