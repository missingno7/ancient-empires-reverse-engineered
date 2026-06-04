from ancient_empires.engine.player import (
    JUMP_DELTAS,
    SFX_BOOTS_JUMP,
    TOOL_BOOTS,
    TOOL_FLASHLIGHT,
    PlayerController,
    PlayerInput,
    PlayerState,
)
from ancient_empires.constants import ROOM_COLUMNS, ROOM_ROWS


def _tiles_with_floor(row: int = 7) -> list[int]:
    tiles = [0] * (ROOM_COLUMNS * ROOM_ROWS)
    for x in range(10, 13):
        tiles[row * ROOM_COLUMNS + x] = 0x07
    return tiles


def _controller_at(x: int = 80, y: int = 32) -> PlayerController:
    controller = object.__new__(PlayerController)
    controller.state = PlayerState(x=x, y=y)
    controller.pending_sounds = []
    return controller


def test_player_walks_four_pixels_and_advances_frames():
    controller = _controller_at()
    tiles = _tiles_with_floor()

    controller.tick(PlayerInput(right=True), tiles)
    controller.tick(PlayerInput(right=True), tiles)

    assert controller.state.x == 88
    assert controller.state.facing == 0
    assert controller.state.frame == 2


def test_player_normal_jump_uses_exe_delta_table():
    controller = _controller_at()
    tiles = _tiles_with_floor()

    controller.tick(PlayerInput(jump=True), tiles)
    assert controller.state.jump_counter == 5
    assert controller.state.frame == 9

    y_positions = []
    for _ in range(5):
        controller.tick(PlayerInput(jump=True), tiles)
        y_positions.append(controller.state.y)

    expected = []
    y = 32
    for counter in range(5, 0, -1):
        y -= JUMP_DELTAS[counter]
        expected.append(y)
    assert y_positions == expected


def test_walk_probe_does_not_bleed_into_floor_below():
    # Regression: the vertical wall probe must stop at the body, not reach two
    # rows further down into the floor the player stands on (AEPROG 0x1fde).
    # Floor spans the whole width at row 7, including the probe column.
    tiles = [0] * (ROOM_COLUMNS * ROOM_ROWS)
    for col in range(ROOM_COLUMNS):
        tiles[7 * ROOM_COLUMNS + col] = 0x07
    controller = _controller_at(x=80, y=32)

    controller.tick(PlayerInput(right=True), tiles)

    assert controller.state.x == 84  # walked instead of being wall-blocked


def _tiles_with_ladder(col: int = 10, rows=range(0, 14)) -> list[int]:
    tiles = [0] * (ROOM_COLUMNS * ROOM_ROWS)
    for row in rows:
        tiles[row * ROOM_COLUMNS + col] = 0x80
    return tiles


def test_player_climbs_up_ladder_and_hangs():
    # Place the player so the ladder column sits under the climb probe.
    controller = _controller_at(x=72, y=48)
    tiles = _tiles_with_ladder(col=(72 + 0x10) // 8 - 1)

    controller.tick(PlayerInput(jump=True), tiles)
    assert controller.state.on_ladder  # grabbed the ladder
    grabbed_y = controller.state.y

    controller.tick(PlayerInput(jump=True), tiles)
    assert controller.state.y < grabbed_y  # ascended
    assert controller.state.frame in (0x14, 0x15)
    assert controller.state.move_amount == 8

    # Releasing keys keeps the player hanging on the ladder.
    controller.tick(PlayerInput(), tiles)
    assert controller.state.on_ladder


def test_player_leaves_ladder_when_walking():
    controller = _controller_at(x=72, y=48)
    controller.state.on_ladder = 1
    floor = _tiles_with_floor(row=(48 + 0x30) // 8)

    controller.tick(PlayerInput(right=True), floor)
    assert controller.state.on_ladder == 0


def _tiles_with_conveyor(code: int, row: int = 7) -> list[int]:
    tiles = [0] * (ROOM_COLUMNS * ROOM_ROWS)
    for x in range(4, 34):
        tiles[row * ROOM_COLUMNS + x] = code
    return tiles


def test_conveyor_drags_player_right_on_0x0f():
    controller = _controller_at(x=80, y=32)
    tiles = _tiles_with_conveyor(0x0F)  # bit 0x8 set, 0x10 clear -> right
    x0 = controller.state.x
    controller.tick(PlayerInput(), tiles)  # no input
    assert controller.state.x == x0 + 4


def test_conveyor_drags_player_left_on_0x1f():
    controller = _controller_at(x=80, y=32)
    tiles = _tiles_with_conveyor(0x1F)  # bit 0x8 set, 0x10 set -> left
    x0 = controller.state.x
    controller.tick(PlayerInput(), tiles)
    assert controller.state.x == x0 - 4


def test_conveyor_does_not_drag_into_a_wall():
    controller = _controller_at(x=80, y=32)
    tiles = _tiles_with_conveyor(0x0F)
    # Solid wall column just to the right of the player's right probe.
    for row in range(2, 13):
        tiles[row * ROOM_COLUMNS + (80 + 0x21) // 8 - 1] = 0x07
    x0 = controller.state.x
    controller.tick(PlayerInput(), tiles)
    assert controller.state.x == x0  # blocked, no drag


def test_boots_jump_is_higher_than_normal_jump():
    tiles = _tiles_with_floor()

    boots = _controller_at()
    boots.state.tool = TOOL_BOOTS
    boots.tick(PlayerInput(use_tool=True), tiles)
    assert boots.state.jump_counter == 8
    assert SFX_BOOTS_JUMP in boots.pending_sounds
    boots_rise = 0
    y = boots.state.y
    for _ in range(8):
        boots.tick(PlayerInput(use_tool=True), tiles)
    boots_rise = y - boots.state.y

    normal = _controller_at()
    normal.tick(PlayerInput(jump=True), tiles)
    assert normal.state.jump_counter == 5
    y = normal.state.y
    for _ in range(5):
        normal.tick(PlayerInput(jump=True), tiles)
    normal_rise = y - normal.state.y

    assert boots_rise == sum(JUMP_DELTAS[1:9])  # 48 px
    assert normal_rise == sum(JUMP_DELTAS[1:6])  # 24 px
    assert boots_rise > normal_rise


def test_space_only_jumps_with_boots_selected():
    tiles = _tiles_with_floor()
    controller = _controller_at()
    controller.state.tool = TOOL_FLASHLIGHT
    controller.tick(PlayerInput(use_tool=True), tiles)
    assert controller.state.jump_counter == 0  # flashlight space does not jump


def test_enter_cycles_tool_once_per_press():
    tiles = _tiles_with_floor()
    controller = _controller_at()
    controller.state.tool = 0

    controller.tick(PlayerInput(change_tool=True), tiles)
    assert controller.state.tool == 1
    controller.tick(PlayerInput(change_tool=True), tiles)  # held: no repeat
    assert controller.state.tool == 1
    controller.tick(PlayerInput(), tiles)  # release re-arms
    controller.tick(PlayerInput(change_tool=True), tiles)
    assert controller.state.tool == 2
    controller.tick(PlayerInput(), tiles)
    controller.tick(PlayerInput(change_tool=True), tiles)
    assert controller.state.tool == 0  # wraps 0..2


def test_player_falls_two_pixels_then_eight_pixels():
    controller = _controller_at()
    tiles = [0] * (ROOM_COLUMNS * ROOM_ROWS)

    controller.tick(PlayerInput(), tiles)
    assert controller.state.y == 34

    controller.tick(PlayerInput(), tiles)
    assert controller.state.y == 42


def test_running_jump_keeps_speed_eight_for_whole_arc():
    """AEPROG: the jump-start sets DS:0x734=8 while running and neither the jump
    ascent (0x3f8c) nor the fall (0x3fe9) resets it, so a running jump carries 8
    px/tick the whole arc (only landing at 0x41c1 restores 4)."""
    tiles = [0] * (ROOM_COLUMNS * ROOM_ROWS)
    floor_row = 14
    for c in range(ROOM_COLUMNS):
        for r in range(floor_row, ROOM_ROWS):
            tiles[r * ROOM_COLUMNS + c] = 0x07

    controller = _controller_at(x=80, y=(floor_row + 2) * 8 - 0x30)
    for _ in range(10):  # settle on the floor
        controller.tick(PlayerInput(), tiles)
    assert controller.state.move_amount == 4

    controller.tick(PlayerInput(right=True, jump=True), tiles)  # jump start
    speeds = []
    for _ in range(12):
        controller.tick(PlayerInput(right=True, jump=True), tiles)
        speeds.append(controller.state.move_amount)
        if controller.state.jump_counter == 0 and controller.state.move_amount == 4:
            break
    # The whole arc (ascent + descent) runs at 8 until the player lands.
    assert speeds[0] == 8 and speeds[3] == 8
    assert speeds.count(8) >= 5  # several airborne ticks at running speed
    assert speeds[-1] == 4       # reset only once grounded


def test_standing_jump_stays_four_pixels():
    tiles = [0] * (ROOM_COLUMNS * ROOM_ROWS)
    floor_row = 14
    for c in range(ROOM_COLUMNS):
        for r in range(floor_row, ROOM_ROWS):
            tiles[r * ROOM_COLUMNS + c] = 0x07
    controller = _controller_at(x=80, y=(floor_row + 2) * 8 - 0x30)
    for _ in range(10):
        controller.tick(PlayerInput(), tiles)
    x0 = controller.state.x
    for _ in range(12):
        controller.tick(PlayerInput(jump=True), tiles)
    assert controller.state.x == x0  # no horizontal drift on a standing jump
