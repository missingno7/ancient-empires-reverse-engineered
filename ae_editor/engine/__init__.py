"""Shared deterministic gameplay rules used by the editor and future game."""

from .runtime import ControlTarget, control_targets, decode_control_target, platform_motion_delta, platform_xy

__all__ = [
    "ControlTarget",
    "control_targets",
    "decode_control_target",
    "platform_motion_delta",
    "platform_xy",
]
