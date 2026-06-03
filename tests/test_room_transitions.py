from dataclasses import dataclass

from ancient_empires.engine import PlayerState, resolve_room_edge
from ancient_empires.engine.transitions import (
    ENTER_FROM_LEFT_X,
    ENTER_FROM_RIGHT_X,
    ROOM_X_MAX,
    ROOM_X_MIN,
    ROOM_Y_MAX,
)


@dataclass
class Links:
    left: int = 0
    right: int = 0
    up: int = 0
    down: int = 0


def test_right_edge_with_link_transitions_and_reenters_left():
    state = PlayerState(x=ROOM_X_MAX + 4, y=60)
    transition = resolve_room_edge(state, Links(right=2))
    assert transition is not None
    assert transition.direction == "right"
    assert transition.to_room == 1  # 1-based link 2 -> room index 1
    assert state.x == ENTER_FROM_LEFT_X


def test_left_edge_with_link_reenters_from_right():
    state = PlayerState(x=ROOM_X_MIN - 4, y=60)
    transition = resolve_room_edge(state, Links(left=3))
    assert transition.direction == "left"
    assert transition.to_room == 2
    assert state.x == ENTER_FROM_RIGHT_X


def test_edge_without_link_clamps_and_stays():
    state = PlayerState(x=ROOM_X_MAX + 20, y=60)
    assert resolve_room_edge(state, Links()) is None
    assert state.x == ROOM_X_MAX


def test_down_edge_with_link_reenters_top():
    state = PlayerState(x=80, y=ROOM_Y_MAX + 10)
    transition = resolve_room_edge(state, Links(down=7))
    assert transition.direction == "down"
    assert transition.to_room == 6
    assert state.y == 0
