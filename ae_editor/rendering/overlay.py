from __future__ import annotations

from dataclasses import dataclass

from .coordinates import actor_origin, actor_xy, control_xy, header_object_xy, platform_xy, platform_motion_delta
from ..constants import CELL_SIZE, ROOM_COLUMNS, ROOM_ROWS, ROOM_SCREEN_HEIGHT_PX as ROOM_HEIGHT_PX, ROOM_SCREEN_WIDTH_PX as ROOM_WIDTH_PX
from ..game_data.level_format import Room
from ..game_data.actor_scripts import actor_script_bytes, decode_actor_script
from ..game_data.conveyors import iter_conveyor_runs
from ..game_data.room_payload import (
    ActorTableRecord,
    ControlCommand,
    actor_records_for_room,
    control_commands,
    header_object_candidates,
    header_exit_door,
    laser_crystal_table,
    parse_exe_payload_directory,
    parse_platform_triplets,
    parse_conveyor_visual_records,
    transition_links_for_room,
)


@dataclass(frozen=True)
class OverlayRect:
    kind: str
    ident: str
    x: int
    y: int
    width: int
    height: int
    label: str
    colour: str
    hidden: bool = False

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2


@dataclass(frozen=True)
class OverlayPoint:
    kind: str
    ident: str
    x: int
    y: int
    label: str
    colour: str
    hidden: bool = False


@dataclass(frozen=True)
class OverlayLine:
    kind: str
    ident: str
    start: tuple[int, int]
    end: tuple[int, int]
    label: str
    colour: str
    dashed: bool = False


@dataclass(frozen=True)
class ControlTarget:
    raw: int
    kind: str
    index: int

    @property
    def label(self) -> str:
        if self.kind == "platform":
            return f"P{self.index}"
        if self.kind == "conveyor":
            return f"CV{self.index}"
        if self.kind == "reflector":
            return f"R{self.index}"
        return f"?{self.raw:02X}"


@dataclass(frozen=True)
class RoomOverlay:
    platforms: list[OverlayRect]
    conveyors: list[OverlayRect]
    puzzle_blocks: list[OverlayRect]
    puzzle_destinations: list[OverlayRect]
    controls: list[OverlayPoint]
    actors: list[OverlayRect]
    pickups: list[OverlayPoint]
    crystals: list[OverlayPoint]
    links: list[OverlayLine]
    actor_paths: list[OverlayLine]
    platform_paths: list[OverlayLine]
    exit_doors: list[OverlayRect]
    exits: list[OverlayLine]


PLATFORM_SIZE = {
    "horizontal": (56, 16),
    "vertical": (16, 56),
    "unknown": (16, 16),
}


def _conveyor_runs(room: Room) -> list[tuple[int, int, int, int]]:
    runs: list[tuple[int, int, int, int]] = []
    for cv in parse_conveyor_visual_records(room):
        runs.append((cv.index, cv.x_raw * 2 - 8, cv.y - 18, max(8, (cv.length + 1) * CELL_SIZE)))
    return runs

def _invisible_clusters(room: Room) -> list[tuple[int, int, int, int]]:
    cells = {(x, y) for y in range(ROOM_ROWS) for x in range(ROOM_COLUMNS) if room.get(x, y) == 0x07}
    clusters: list[tuple[int, int, int, int]] = []
    while cells:
        seed = next(iter(cells))
        stack = [seed]
        cluster = set()
        cells.remove(seed)
        while stack:
            cx, cy = stack.pop()
            cluster.add((cx, cy))
            for nx, ny in ((cx-1, cy), (cx+1, cy), (cx, cy-1), (cx, cy+1)):
                if (nx, ny) in cells:
                    cells.remove((nx, ny))
                    stack.append((nx, ny))
        xs = [x for x, _ in cluster]
        ys = [y for _, y in cluster]
        clusters.append((min(xs) * CELL_SIZE, min(ys) * CELL_SIZE, (max(xs) - min(xs) + 1) * CELL_SIZE, (max(ys) - min(ys) + 1) * CELL_SIZE))
    clusters.sort(key=lambda r: (r[1], r[0]))
    return clusters


def _green_block_xy(raw_x: int, raw_y: int) -> tuple[int, int]:
    return raw_x * 2 - 8, raw_y - 12


def _record12_default_rect(rec: bytes) -> tuple[int, int, int, int] | None:
    if len(rec) < 2:
        return None
    x, y = _green_block_xy(rec[0], rec[1])
    return x, y, 56, 16


def _record12_alternate_rect(rec: bytes) -> tuple[int, int, int, int] | None:
    if len(rec) < 4:
        return None
    x, y = _green_block_xy(rec[2], rec[3])
    return x, y, 56, 16


def decode_control_target(value: int) -> ControlTarget:
    """Decode one target byte used by button/switch/jello commands.

    Current reverse-engineering model:
      * 00..0F -> runtime platform slots P0..P15
      * 10..1F -> conveyor/CV slots CV0..CV15
      * 40..4F -> section_c reflector slots R0..R15

    The exact high-nibble classes may still grow, but keeping the raw byte while
    exposing the class makes trigger editing much less ambiguous than a flat
    numeric id.
    """
    value &= 0xFF
    if value < 0x10:
        return ControlTarget(value, "platform", value)
    if 0x10 <= value < 0x20:
        return ControlTarget(value, "conveyor", value - 0x10)
    if 0x40 <= value < 0x50:
        return ControlTarget(value, "reflector", value - 0x40)
    return ControlTarget(value, "unknown", value)


def control_targets(cmd: ControlCommand) -> list[ControlTarget]:
    """Return decoded control targets from body bytes after type/x/y/state."""
    if len(cmd.body) < 5:
        return []
    out: list[ControlTarget] = []
    seen: set[int] = set()
    for raw in cmd.body[4:]:
        if raw in seen:
            continue
        seen.add(raw)
        out.append(decode_control_target(raw))
    return out


def control_ref_values(cmd: ControlCommand) -> list[int]:
    """Backward-compatible raw target byte list."""
    return [target.raw for target in control_targets(cmd)]


def reflector_target_indices(level, part, room: Room, target_index: int) -> list[int]:
    # Static analysis confirms target byte 0x40|n rotates section_c entry n.
    return [target_index]


def _is_projectile_actor(actor: ActorTableRecord) -> bool:
    name = actor.confirmed_name or ""
    projectile_names = {"Pill Projectile", "Energy Orb", "Fireball", "Sparkles"}
    return actor.actor_type == 1 or name in projectile_names


def _looks_like_projectile_source(actor: ActorTableRecord) -> bool:
    name = actor.confirmed_name or ""
    return name in {"Praying Mantis", "Scorpion"} or name.endswith("Mantis") or name.endswith("Scorpion")


def _match_projectile_source(actor: ActorTableRecord, actor_rects: list[tuple[ActorTableRecord, OverlayRect]]) -> OverlayRect | None:
    preferred = [(a, r) for a, r in actor_rects if a.index != actor.index and _looks_like_projectile_source(a)]
    candidates = preferred or [(a, r) for a, r in actor_rects if a.index != actor.index and not _is_projectile_actor(a)]
    best_rect: OverlayRect | None = None
    best_dist: int | None = None
    for candidate_actor, candidate_rect in candidates:
        dx = candidate_actor.x - actor.x
        dy = candidate_actor.y - actor.y
        dist = dx * dx + dy * dy
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_rect = candidate_rect
    return best_rect


def _sequence_label_from_record(rec: bytes, markers) -> str:
    if len(rec) < 10 or not markers:
        return ""
    seq_vals: list[int] = []
    for value in rec[5:10]:
        if value == 0:
            break
        seq_vals.append(value)
    if not seq_vals:
        return ""
    parts: list[str] = []
    for value in seq_vals:
        marker = next((m for m in markers if ((m[1].code & 0x07) + 1) == value), None)
        if marker is None:
            parts.append(str(value))
        else:
            _idx, entry = marker
            parts.append(f"S{(entry.code & 0x07) + 1}")
    return " -> ".join(parts)


def build_room_overlay(level, part, room: Room, *, include_hidden: bool = False) -> RoomOverlay:
    platforms: list[OverlayRect] = []
    conveyors: list[OverlayRect] = []
    controls: list[OverlayPoint] = []
    puzzle_blocks: list[OverlayRect] = []
    puzzle_destinations: list[OverlayRect] = []
    actors: list[OverlayRect] = []
    pickups: list[OverlayPoint] = []
    crystals: list[OverlayPoint] = []
    links: list[OverlayLine] = []
    actor_paths: list[OverlayLine] = []
    platform_paths: list[OverlayLine] = []
    exit_doors: list[OverlayRect] = []
    exits: list[OverlayLine] = []
    actor_rects: list[tuple[ActorTableRecord, OverlayRect]] = []

    platform_by_index: dict[int, OverlayRect] = {}
    conveyor_by_index: dict[int, OverlayRect] = {}
    crystal_by_index: dict[int, OverlayPoint] = {}
    for cid, x, y, width in _conveyor_runs(room):
        rect = OverlayRect("conveyor", f"CV{cid}", x, y, width, 16, f"CV{cid}", "#4aa8ff")
        conveyors.append(rect)
        conveyor_by_index[cid] = rect

    for platform in parse_platform_triplets(room):
        if not platform.visible:
            continue
        x, y = platform_xy(platform)
        width, height = PLATFORM_SIZE[platform.orientation]
        rect = OverlayRect(
            "platform",
            f"P{platform.index}",
            x,
            y,
            width,
            height,
            f"P{platform.index} {platform.flags:02X}",
            "#ffb000",
        )
        platforms.append(rect)
        platform_by_index[platform.index] = rect
        dx, dy = platform_motion_delta(platform)
        if dx or dy:
            start = rect.center
            end = (start[0] + dx, start[1] + dy)
            platform_paths.append(
                OverlayLine(
                    "platform_path",
                    f"{rect.ident}m",
                    start,
                    end,
                    f"{rect.ident} Δ{dx:+d},{dy:+d}",
                    "#ffb000",
                    dashed=True,
                )
            )


    # Pre-index reflectors before processing control links, because control
    # commands can target them with R0/R1/... bytes (0x40|index).  The visible points are
    # still appended in the normal crystal overlay block below.
    _crystal_table_for_links = laser_crystal_table(room)
    if _crystal_table_for_links:
        for _entry in _crystal_table_for_links.entries:
            crystal_by_index[_entry.index] = OverlayPoint(
                "crystal",
                f"R{_entry.index}",
                _entry.x_raw * 2,
                _entry.y,
                f"R{_entry.index} orient={_entry.code & 0x1F:02X} flags={_entry.code & 0xE0:02X}",
                "#44d7ff",
            )

    for cmd in control_commands(room):
        if cmd.command is None or cmd.x_raw is None or cmd.y_raw is None:
            continue
        mode = "button"
        kind = "C"
        if cmd.command == 0x00:
            mode = "ceiling_button"
            kind = "B"
        elif cmd.command == 0x01:
            mode = "floor_switch"
            kind = "S"
        elif cmd.command == 0x02:
            mode = "laser_trigger"
            kind = "J"
        x, y = control_xy(cmd, mode=mode)
        label = f"{kind}{cmd.record.index} cmd={cmd.command:02X}"
        targets = control_targets(cmd)
        if targets:
            label += " refs=" + ",".join(target.label for target in targets)
        label += f" @{cmd.record.source_offset:02X}"
        point = OverlayPoint("control", f"{kind}{cmd.record.index}", x + 8, y + 8, label, "#00e0ff")
        controls.append(point)
        for target_ref in targets:
            if target_ref.kind == "platform":
                target = platform_by_index.get(target_ref.index)
            elif target_ref.kind == "conveyor":
                target = conveyor_by_index.get(target_ref.index)
            elif target_ref.kind == "reflector":
                for reflector_index in reflector_target_indices(level, part, room, target_ref.index):
                    target = crystal_by_index.get(reflector_index)
                    if target is None:
                        continue
                    links.append(
                        OverlayLine(
                            "trigger",
                            f"{point.ident}->{target.ident}",
                            (point.x, point.y),
                            (target.x, target.y),
                            f"{point.ident}->{target.ident}",
                            "#00e0ff",
                            dashed=cmd.command != 0x02,
                        )
                    )
                continue
            else:
                target = None
            if target is None:
                continue
            target_center = target.center if hasattr(target, "center") else (target.x, target.y)
            links.append(
                OverlayLine(
                    "trigger",
                    f"{point.ident}->{target.ident}",
                    (point.x, point.y),
                    target_center,
                    f"{point.ident}->{target.ident}",
                    "#00e0ff",
                    dashed=cmd.command != 0x02,
                )
            )

    for actor in actor_records_for_room(part, room.index):
        hidden = bool(actor.hidden)
        if hidden and not include_hidden:
            continue
        x, y = actor_xy(actor.x, actor.y, frame_min=actor.frame_min)
        _, script = actor_script_bytes(part, actor, limit=12)
        decoded = decode_actor_script(part, actor, max_bytes=96, max_segments=8)
        script_hex = " ".join(f"{value:02X}" for value in script[:8])
        name = actor.confirmed_name or f"frame {actor.frame:02X}"
        label = f"A{actor.index} {name} d={actor.delay} scr={actor.script_offset:04X} [{script_hex}]"
        if decoded.segments:
            label += f" segs={len(decoded.segments)}"
        rect = OverlayRect(
            "actor",
            f"A{actor.index}",
            x,
            y,
            24,
            16,
            label,
            "#7cff6b" if not hidden else "#7a7a7a",
            hidden=hidden,
        )
        actors.append(rect)
        actor_rects.append((actor, rect))
        traces = decoded.traces or []
        if traces:
            for trace_index, trace in enumerate(traces[:6]):
                if not trace.segments or len(trace.points) < 2:
                    continue
                visible_points = [
                    (max(-64, min(ROOM_WIDTH_PX + 64, px)), max(-64, min(ROOM_HEIGHT_PX + 64, py)))
                    for px, py in trace.points
                ]
                for idx, (start_pt, end_pt) in enumerate(zip(visible_points, visible_points[1:])):
                    if idx >= len(trace.segments):
                        break
                    seg = trace.segments[idx]
                    cond = ""
                    if trace.conditions:
                        cond = " if " + "; ".join(trace.conditions[:2])
                        if len(trace.conditions) > 2:
                            cond += " ..."
                    actor_paths.append(
                        OverlayLine(
                            "actor_path",
                            f"A{actor.index}t{trace_index}p{idx}",
                            start_pt,
                            end_pt,
                            f"A{actor.index}.{trace_index}.{idx} {seg.dx:+d},{seg.dy:+d}×{seg.duration}{cond}",
                            "#7cff6b" if not hidden else "#7a7a7a",
                            dashed=hidden or bool(trace.conditions),
                        )
                    )
        elif decoded.segments and len(decoded.points) >= 2:
            visible_points = [
                (max(-64, min(ROOM_WIDTH_PX + 64, px)), max(-64, min(ROOM_HEIGHT_PX + 64, py)))
                for px, py in decoded.points
            ]
            for idx, (start_pt, end_pt) in enumerate(zip(visible_points, visible_points[1:])):
                actor_paths.append(
                    OverlayLine(
                        "actor_path",
                        f"A{actor.index}p{idx}",
                        start_pt,
                        end_pt,
                        f"A{actor.index}.{idx} {decoded.segments[idx].dx:+d},{decoded.segments[idx].dy:+d}×{decoded.segments[idx].duration}",
                        "#7cff6b" if not hidden else "#7a7a7a",
                        dashed=hidden,
                    )
                )

    for actor, rect in actor_rects:
        if not _is_projectile_actor(actor):
            continue
        source_rect = _match_projectile_source(actor, actor_rects)
        if source_rect is None:
            continue
        links.append(
            OverlayLine(
                "projectile",
                f"{source_rect.ident}->{rect.ident}",
                source_rect.center,
                rect.center,
                f"{source_rect.ident}->{rect.ident} projectile",
                "#ff7a00",
                dashed=bool(actor.hidden),
            )
        )

    directory = parse_exe_payload_directory(room)
    if directory and directory.sections and directory.sections.section_a and directory.sections.section_a.entries:
        markers = list(enumerate(directory.sections.section_a.entries))
        panel_centers: list[tuple[int, int]] = []
        if directory.sections.section_b_records:
            for rec_index, rec in enumerate(directory.sections.section_b_records):
                default_rect = _record12_default_rect(rec)
                alternate_rect = _record12_alternate_rect(rec)
                if default_rect is None:
                    continue
                dx, dy, dw, dh = default_rect
                panel_centers.append((dx + dw // 2, dy + dh // 2))
                seq_label = _sequence_label_from_record(rec, markers)

                # event09 operates on the record12 green-block mechanism.
                # byte0/byte1 are the default/current position seen in-game;
                # byte2/byte3 are the alternate position the block swaps to after
                # the configured symbol sequence is emitted/pressed.
                default = OverlayRect(
                    "puzzle_dest",
                    f"PD{rec_index}",
                    dx,
                    dy,
                    dw,
                    dh,
                    (f"seq={seq_label}" if seq_label else f"PD{rec_index}"),
                    "#ffd84d",
                )
                puzzle_destinations.append(default)
                # Do not add a second point label on top of the default block.
                # The rectangle label already carries PDn + sequence info; adding
                # a puzzle_panel point made labels look duplicated in the editor.

                if alternate_rect is not None:
                    ax, ay, aw, ah = alternate_rect
                    alt = OverlayRect("puzzle_block", f"PB{rec_index}", ax, ay, aw, ah, f"PB{rec_index} alternate", "#ffd84d", hidden=True)
                    puzzle_blocks.append(alt)
        for marker_index, entry in markers:
            mx = entry.x_raw * 2
            my = entry.y
            symbol_id = (entry.code & 0x07) + 1
            controls.append(OverlayPoint("puzzle_marker", f"S{symbol_id}", mx, my, f"S{symbol_id} / M{marker_index}", "#ffd84d"))
            for panel_index, center in enumerate(panel_centers):
                links.append(
                    OverlayLine(
                        "puzzle_link",
                        f"S{symbol_id}->PB{panel_index}",
                        (mx, my),
                        center,
                        f"S{symbol_id}->PB{panel_index}",
                        "#ffd84d",
                        dashed=True,
                    )
                )

    for cand in header_object_candidates(part.header):
        if cand.room_plus_one != room.index + 1:
            continue
        x, y = header_object_xy(cand.x_raw, cand.y_raw)
        pickups.append(OverlayPoint("pickup", f"D{cand.index}", x + 8, y + 8, f"D{cand.index}", "#ff40ff"))

    door = header_exit_door(part.header)
    if door is not None and door.room_index == room.index:
        width, height = 46, 33
        x = door.x_raw * 2 - 12
        y = door.y_raw - 16
        exit_doors.append(OverlayRect("exit_door", "Exit", x, y, width, height, "Exit door", "#ffffff"))

    table = laser_crystal_table(room)
    if table:
        for entry in table.entries:
            x = entry.x_raw * 2
            y = entry.y
            point = OverlayPoint(
                "crystal",
                f"R{entry.index}",
                x,
                y,
                f"R{entry.index} orient={entry.code & 0x1F:02X} flags={entry.code & 0xE0:02X}",
                "#44d7ff",
            )
            crystals.append(point)
            crystal_by_index[entry.index] = point

    room_links = transition_links_for_room(part, room.index)
    if room_links:
        edge_points = {
            "L": ((0, 72), (18, 72), room_links.left),
            "R": ((304, 72), (286, 72), room_links.right),
            "U": ((152, 0), (152, 18), room_links.up),
            "D": ((152, 144), (152, 126), room_links.down),
        }
        for side, (start, end, target) in edge_points.items():
            if not target:
                continue
            exits.append(
                OverlayLine(
                    "exit",
                    f"{side}{target - 1}",
                    start,
                    end,
                    f"{side}->{target - 1}",
                    "#ffffff",
                )
            )

    return RoomOverlay(platforms, conveyors, puzzle_blocks, puzzle_destinations, controls, actors, pickups, crystals, links, actor_paths, platform_paths, exit_doors, exits)
