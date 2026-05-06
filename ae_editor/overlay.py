from __future__ import annotations

from dataclasses import dataclass

from .coordinates import actor_xy, control_xy, header_object_xy, platform_xy
from .level_format import Room
from .room_payload import (
    ACTOR_TABLE_OFFSET,
    ActorTableRecord,
    ControlCommand,
    actor_records_for_room,
    control_commands,
    header_object_candidates,
    laser_crystal_table,
    parse_platform_triplets,
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
class RoomOverlay:
    platforms: list[OverlayRect]
    controls: list[OverlayPoint]
    actors: list[OverlayRect]
    pickups: list[OverlayPoint]
    crystals: list[OverlayPoint]
    links: list[OverlayLine]
    exits: list[OverlayLine]


PLATFORM_SIZE = {
    "horizontal": (56, 16),
    "vertical": (16, 56),
    "unknown": (16, 16),
}


def actor_script_bytes(part, actor: ActorTableRecord, limit: int = 12) -> bytes:
    raw = getattr(part, "raw", b"")
    start = ACTOR_TABLE_OFFSET + actor.script_offset
    if start < 0 or start >= len(raw):
        return b""
    return bytes(raw[start:start + limit])


def control_link_ids(cmd: ControlCommand, platform_ids: set[int]) -> list[int]:
    """Return platform indices referenced by raw command metadata.

    This intentionally stays conservative: it only exposes bytes that already
    look like small platform ids instead of inventing semantic names.
    """
    values: list[int] = []
    if cmd.arg_b is not None:
        values.append(cmd.arg_b & 0x0F)
    values.extend(cmd.extra)

    out: list[int] = []
    for value in values:
        if value in platform_ids and value not in out:
            out.append(value)
    return out


def control_ref_values(cmd: ControlCommand) -> list[int]:
    values: list[int] = []
    if cmd.arg_b is not None:
        values.append(cmd.arg_b & 0x0F)
    values.extend(value for value in cmd.extra if value < 0x10)
    out: list[int] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def build_room_overlay(level, part, room: Room, *, include_hidden: bool = False) -> RoomOverlay:
    platforms: list[OverlayRect] = []
    controls: list[OverlayPoint] = []
    actors: list[OverlayRect] = []
    pickups: list[OverlayPoint] = []
    crystals: list[OverlayPoint] = []
    links: list[OverlayLine] = []
    exits: list[OverlayLine] = []

    platform_by_index: dict[int, OverlayRect] = {}
    for platform in parse_platform_triplets(room):
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
        refs = control_ref_values(cmd)
        if refs:
            label += " refs=" + ",".join(str(value) for value in refs)
        label += f" @{cmd.record.source_offset:02X}"
        point = OverlayPoint("control", f"{kind}{cmd.record.index}", x + 8, y + 8, label, "#00e0ff")
        controls.append(point)
        for target_id in control_link_ids(cmd, set(platform_by_index)):
            target = platform_by_index.get(target_id)
            if target is None:
                continue
            links.append(
                OverlayLine(
                    "trigger",
                    f"{point.ident}->{target.ident}",
                    (point.x, point.y),
                    target.center,
                    f"{point.ident}->{target.ident}",
                    "#00e0ff",
                    dashed=cmd.command != 0x02,
                )
            )

    for actor in actor_records_for_room(part, room.index):
        hidden = bool(actor.hidden)
        if hidden and not include_hidden:
            continue
        x, y = actor_xy(actor.x, actor.y)
        script = actor_script_bytes(part, actor)
        script_hex = " ".join(f"{value:02X}" for value in script[:8])
        name = actor.confirmed_name or f"frame {actor.frame:02X}"
        label = f"A{actor.index} {name} scr={actor.script_offset:04X} [{script_hex}]"
        actors.append(
            OverlayRect(
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
        )

    for cand in header_object_candidates(part.header):
        if cand.room_plus_one != room.index + 1:
            continue
        x, y = header_object_xy(cand.x_raw, cand.y_raw)
        pickups.append(OverlayPoint("pickup", f"D{cand.index}", x + 8, y + 8, f"D{cand.index}", "#ff40ff"))

    table = laser_crystal_table(room)
    if table:
        for entry in table.entries:
            x = entry.x_raw * 2
            y = entry.y
            crystals.append(
                OverlayPoint(
                    "crystal",
                    f"R{entry.index}",
                    x,
                    y,
                    f"R{entry.index} idx={entry.code & 0x3F:02X}",
                    "#44d7ff",
                )
            )

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

    return RoomOverlay(platforms, controls, actors, pickups, crystals, links, exits)
