"""Screen-edge room transitions recovered from AEPROG 0x4240..0x4372.

When the player walks past a screen edge the original game looks up the
directional link for the current room (the four 10-byte arrays at DS:438c/4396/
43a0/43aa for left/right/up/down) and, if a link exists, swaps to that room and
re-enters from the opposite side.  When no link exists the player is clamped at
the boundary instead.
"""
from __future__ import annotations

from dataclasses import dataclass


# Player coordinate bounds (AEPROG compares DS:0736/0738 against these).
ROOM_X_MIN = -0x10   # 0xfff0
ROOM_X_MAX = 0x130   # 304
ROOM_Y_MIN = 0
ROOM_Y_MAX = 0x90    # 144

# Where the player re-enters the destination room (AEPROG 0x4252/0x42a0/...).
ENTER_FROM_RIGHT_X = 0x120
ENTER_FROM_LEFT_X = 0
ENTER_FROM_BOTTOM_Y = 0x90
ENTER_FROM_TOP_Y = 0


@dataclass(frozen=True)
class RoomTransition:
    direction: str
    to_room: int


def resolve_room_edge(state, links) -> RoomTransition | None:
    """Detect an edge crossing, repositioning ``state`` and returning the move.

    ``links`` exposes 1-based ``left``/``right``/``up``/``down`` room indices
    (0 = no link), matching ``RoomTransitionLinks``.  The player is repositioned
    on the entry side when a link exists, or clamped to the boundary otherwise.
    Vertical edges are checked before horizontal, mirroring the EXE order.
    """
    # Vertical edges (AEPROG 0x4240 / 0x428d).
    if state.y < ROOM_Y_MIN:
        if links.up:
            state.y = ENTER_FROM_BOTTOM_Y
            return RoomTransition("up", links.up - 1)
        state.y = ROOM_Y_MIN
    elif state.y > ROOM_Y_MAX:
        if links.down:
            state.y = ENTER_FROM_TOP_Y
            return RoomTransition("down", links.down - 1)
        state.y = ROOM_Y_MAX

    # Horizontal edges (AEPROG 0x42d9 / 0x4326).
    if state.x < ROOM_X_MIN:
        if links.left:
            state.x = ENTER_FROM_RIGHT_X
            return RoomTransition("left", links.left - 1)
        state.x = ROOM_X_MIN
    elif state.x > ROOM_X_MAX:
        if links.right:
            state.x = ENTER_FROM_LEFT_X
            return RoomTransition("right", links.right - 1)
        state.x = ROOM_X_MAX

    return None
