"""Small shared runtime rules independent of asset loading and presentation."""
from __future__ import annotations

from dataclasses import dataclass

from ..game_data.room_payload import ControlCommand, PlatformTriplet


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


def decode_control_target(value: int) -> ControlTarget:
    """Decode one target byte used by button, switch and jello commands."""
    value &= 0xFF
    if value < 0x10:
        return ControlTarget(value, "platform", value)
    if value < 0x20:
        return ControlTarget(value, "conveyor", value - 0x10)
    if 0x40 <= value < 0x50:
        return ControlTarget(value, "reflector", value - 0x40)
    return ControlTarget(value, "unknown", value)


def control_targets(cmd: ControlCommand) -> list[ControlTarget]:
    """Return unique decoded targets from body bytes after type/x/y/state."""
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


PLATFORM_TRAVEL_DISTANCE = 48
PLATFORM_TRAVEL_BY_FLAGS: dict[int, tuple[int, int]] = {
    0x40: (+PLATFORM_TRAVEL_DISTANCE, 0),
    0x60: (-PLATFORM_TRAVEL_DISTANCE, 0),
    0x80: (0, +PLATFORM_TRAVEL_DISTANCE),
    0xA0: (0, -PLATFORM_TRAVEL_DISTANCE),
}


def platform_xy(platform: PlatformTriplet) -> tuple[int, int]:
    """Resting platform top-left in room-view pixels."""
    return platform.x_raw * 2 - 12, platform.y - 20


def platform_motion_delta(platform: PlatformTriplet) -> tuple[int, int]:
    """Platform travel vector from its runtime flag family."""
    return PLATFORM_TRAVEL_BY_FLAGS.get(platform.flags & 0xF0, (0, 0))
