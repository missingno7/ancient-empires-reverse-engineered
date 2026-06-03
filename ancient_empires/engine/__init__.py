"""Shared deterministic gameplay rules used by the editor and future game."""

from .runtime import ControlTarget, control_targets, decode_control_target, platform_motion_delta, platform_xy
from .room_simulation import RoomSimulation
from .player import PlayerController, PlayerInput, PlayerState
from .transitions import RoomTransition, resolve_room_edge

__all__ = [
    "ControlTarget",
    "control_targets",
    "decode_control_target",
    "platform_motion_delta",
    "platform_xy",
    "RoomSimulation",
    "PlayerController",
    "PlayerInput",
    "PlayerState",
    "RoomTransition",
    "resolve_room_edge",
]
