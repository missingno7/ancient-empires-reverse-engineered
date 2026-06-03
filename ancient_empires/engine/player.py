"""Recovered room-local player movement from AEPROG 0x3A75."""
from __future__ import annotations

from dataclasses import dataclass

from ..constants import CELL_SIZE, ROOM_COLUMNS, ROOM_ROWS
from ..game_data.room_payload import header_player_start


SOLID_MASK = 0x07
LADDER_MASK = 0x80
CONVEYOR_MASK = 0x08       # floor tile bit marking a conveyor belt
CONVEYOR_LEFT_MASK = 0x10  # belt direction: set = left (0x1F), clear = right (0x0F)
JUMP_DELTAS = (0, 2, 2, 4, 8, 8, 8, 8, 8)

# Tool indices (DS:0b7e), drawn as AE000:063 sprites 3 + tool.
TOOL_FLASHLIGHT = 0  # sprite 3 - fires lasers (0x5a3b)
TOOL_BOOTS = 1       # sprite 4 - high jump
TOOL_IMMORTALITY = 2  # sprite 5 - temporary invulnerability, 4 uses/level
TOOL_COUNT = 3

# Sound effect ids played by tool use (AEPROG 0xcaf1 calls).
SFX_JUMP = 0x0C       # normal up-jump (0x410C/0x4133)
SFX_BOOTS_JUMP = 0x10  # boots high jump (0x40B3)
SFX_LASER = 0x14       # flashlight laser (0x421b)


@dataclass(frozen=True)
class PlayerInput:
    left: bool = False
    right: bool = False
    jump: bool = False
    down: bool = False
    change_tool: bool = False  # Enter (key 0x0d -> 0x727d cycles DS:0b7e)
    use_tool: bool = False     # Space (key 0x20 activates the current tool)


@dataclass
class PlayerState:
    x: int
    y: int
    facing: int = 0
    frame: int = 0
    jump_counter: int = 0
    move_amount: int = 4
    fall_started: bool = False
    jump_ready: bool = True
    on_ladder: int = 0
    tool: int = TOOL_BOOTS
    tool_ready: bool = True
    change_ready: bool = True
    fired_laser: bool = False


class PlayerController:
    """Deterministic subset of the original player loop.

    This covers ordinary left/right walking, gravity, floor snapping, normal
    jump and frames 0..11. Ladders, conveyors, room transitions, items and
    hazards remain separate recovery work.
    """

    def __init__(self, level, part_index: int = 0, room_index: int = 0):
        self.level = level
        self.part_index = part_index
        self.room_index = room_index
        self.part = level.part(part_index)
        self.state = self._initial_state()
        self.pending_sounds: list[int] = []

    def _initial_state(self) -> PlayerState:
        start = header_player_start(self.part.header)
        if start is not None and start.room_index == self.room_index:
            # AEPROG 0x471A..0x473C.
            x = ((start.x_raw * 2 + 3) // 4) * 4
            return PlayerState(x=x, y=start.y_raw)
        return PlayerState(x=ROOM_COLUMNS * CELL_SIZE // 2, y=ROOM_ROWS * CELL_SIZE // 2)

    def tick(self, command: PlayerInput, tiles: list[int]) -> PlayerState:
        state = self.state
        moved = 0

        # Enter cycles the selected tool (AEPROG 0x3ad1 -> 0x727d), one step per
        # keypress.  Handled at the top of the loop like the original.
        if command.change_tool:
            if state.change_ready:
                state.change_ready = False
                state.tool = (state.tool + 1) % TOOL_COUNT
        else:
            state.change_ready = True
        if not command.use_tool:
            state.tool_ready = True

        # Flashlight fires a laser on Space (AEPROG 0x421b).  The actual beam is
        # spawned by the simulation from the post-tick position; here we only
        # latch the one-shot intent and play the SFX.
        state.fired_laser = False
        if command.use_tool and state.tool_ready and state.tool == TOOL_FLASHLIGHT:
            state.tool_ready = False
            state.fired_laser = True
            self.pending_sounds.append(SFX_LASER)

        # While climbing with up held, left/right is ignored (AEPROG 0x3db6,
        # 0x3e10); otherwise entering a walk branch releases the ladder
        # (AEPROG 0x3dc1, 0x3e21 clear the on-ladder register).
        climb_locks_walk = bool(state.on_ladder) and command.jump
        if command.right and not command.left and not climb_locks_walk:
            state.on_ladder = 0
            state.facing = 0
            if not self._vertical_span(tiles, state.x + 0x21, state.y + 1, 0x27) & SOLID_MASK:
                state.x += state.move_amount
                moved = 1
                self._advance_walk_frame()
        elif command.left and not command.right and not climb_locks_walk:
            state.on_ladder = 0
            state.facing = 1
            if not self._vertical_span(tiles, state.x, state.y + 1, 0x27) & SOLID_MASK:
                state.x -= state.move_amount
                moved = -1
                self._advance_walk_frame()

        if self._climb(command, tiles):
            return state

        if not command.jump:
            state.jump_ready = True

        if state.jump_counter:
            if not self._horizontal_span(tiles, state.x + 8, state.y - 1, 9) & SOLID_MASK:
                state.y -= JUMP_DELTAS[state.jump_counter]
                state.jump_counter -= 1
                state.frame = min(11, state.frame + 1)
                if not moved:
                    state.frame = 10
            else:
                state.jump_counter = 0
            state.move_amount = 4
            return state

        below = self._horizontal_span(tiles, state.x + 8, state.y + 0x2F, 9)
        if not below & SOLID_MASK:
            if state.fall_started:
                state.y += 8
            else:
                state.fall_started = True
                state.y += 2
            state.frame = 10 + (moved & 1)
            state.move_amount = 4
            return state

        near_floor = self._horizontal_span(tiles, state.x + 8, state.y + 0x28, 9)
        if not near_floor & SOLID_MASK:
            state.y += ((state.y + 0x30) // 8) * 8 - (state.y + 0x28)
            state.fall_started = False
            state.frame = 10 + (moved & 1)
            state.move_amount = 4
            return state

        state.fall_started = False
        # Boots high-jump on Space (AEPROG 0x408a): only with the boots tool
        # selected, and only if there is headroom.  Jump counter 8 rises ~48 px,
        # double the normal jump's 24 px.
        if command.use_tool and state.tool_ready and state.tool == TOOL_BOOTS:
            state.tool_ready = False
            if not self._horizontal_span(tiles, state.x + 8, state.y - 1, 9) & SOLID_MASK:
                state.jump_counter = 8
                state.frame = 9
                state.move_amount = 8 if moved else 4
                self.pending_sounds.append(SFX_BOOTS_JUMP)
                return state
        # Normal up-jump (AEPROG 0x40e3): jump counter 5.
        if command.jump and state.jump_ready:
            state.jump_ready = False
            if not self._horizontal_span(tiles, state.x + 8, state.y - 1, 9) & SOLID_MASK:
                state.jump_counter = 5
                state.frame = 9
                state.move_amount = 8 if moved else 4
                self.pending_sounds.append(SFX_JUMP)
                return state

        if moved:
            if state.frame > 8:
                state.frame = 1
        else:
            state.frame = 0

        # Conveyor drag (AEPROG 0x4155): a conveyor floor tile (bit 0x8) carries
        # the player along the belt - bit 0x10 set drags left (tile 0x1F), clear
        # drags right (tile 0x0F) - with the same wall checks and edge clamps as
        # walking.  Conveyor controls flip the direction by toggling 0x0F<->0x1F.
        if near_floor & CONVEYOR_MASK:
            if near_floor & CONVEYOR_LEFT_MASK:
                if not self._vertical_span(tiles, state.x, state.y + 1, 0x27) & SOLID_MASK:
                    state.x -= state.move_amount
                    if state.x <= -4:
                        state.x = -17
            else:
                if not self._vertical_span(tiles, state.x + 0x21, state.y + 1, 0x27) & SOLID_MASK:
                    state.x += state.move_amount
                    if state.x >= 0x130:
                        state.x = 0x131

        state.move_amount = 4
        return state

    def _climb(self, command: PlayerInput, tiles: list[int]) -> bool:
        """Ladder climbing recovered from AEPROG 0x3e60..0x3f85.

        Returns True when the player is on a ladder, in which case the caller
        skips the jump/gravity branches (AEPROG 0x3f85 ``or si,si`` short
        circuit). ``on_ladder`` mirrors the original ``si`` register: 0 off the
        ladder, 1/2 alternating the two climb frames.
        """
        state = self.state

        if command.jump:
            # Climb up: probe the ladder column ahead of the body (0x3e6a).
            grab_x = state.x + 0x10 - state.facing * 4
            if self._vertical_span(tiles, grab_x, state.y + 1, 0x27) & LADDER_MASK:
                if state.on_ladder:
                    # Already climbing: ascend 4 or 2 px (0x3ecf..0x3f26).
                    if self._horizontal_span(tiles, state.x + 0xF, state.y - 4, 2) & LADDER_MASK:
                        state.y -= 4
                        state.on_ladder = state.on_ladder % 2 + 1
                    elif self._horizontal_span(tiles, state.x + 0xF, state.y - 2, 2) & LADDER_MASK:
                        state.y -= 2
                        state.on_ladder = state.on_ladder % 2 + 1
                else:
                    # First grab: snap onto the ladder centre (0x3e96).
                    if state.x % 8 == 0:
                        if self._vertical_span(tiles, state.x + 0x14, state.y + 1, 0x1D) & LADDER_MASK:
                            state.x += 4
                        else:
                            state.x -= 4
                    state.on_ladder = 1
                state.move_amount = 8
                state.jump_counter = 0
                state.frame = 0x13 + state.on_ladder
                return True
        elif command.down and state.on_ladder:
            # Climb down: probe the ladder below the feet (0x3f48..0x3f7e).
            if self._horizontal_span(tiles, state.x + 0xF, state.y + 0x26, 2) & LADDER_MASK:
                state.on_ladder = state.on_ladder % 2 + 1
                state.y += 4
                state.frame = 0x13 + state.on_ladder
                return True
            # Ran off the bottom of the ladder: hand back to gravity (0x3f83).
            state.on_ladder = 0
            return False

        # Idle on the ladder keeps the player hanging (0x3f85 ``or si,si``).
        return bool(state.on_ladder)

    def _advance_walk_frame(self) -> None:
        state = self.state
        if state.frame <= 8:
            state.frame += 1
            if state.frame > 8:
                state.frame = 1

    @staticmethod
    def _horizontal_span(tiles: list[int], x: int, y: int, width: int) -> int:
        """AEPROG 0x1F17: OR terrain bytes across one horizontal span."""
        x = max(8, min(0x137, x))
        y = max(0x10, min(0x9F, y))
        start_x = x // 8 - 1
        # The original derives the cell count from the un-offset column
        # (cap - x/8 + 1) but indexes from x/8 - 1, so the last column carries
        # the same -1 border shift (AEPROG 0x1f64..0x1f70).
        end_x = min(0x26, (x // 2 + width - 1) // 4) - 1
        row = y // 8 - 2
        return PlayerController._or_cells(tiles, ((col, row) for col in range(start_x, end_x + 1)))

    @staticmethod
    def _vertical_span(tiles: list[int], x: int, y: int, height: int) -> int:
        """AEPROG 0x1F91: OR terrain bytes down one vertical span."""
        x = max(8, min(0x137, x))
        y = max(0x10, min(0x9F, y))
        col = x // 8 - 1
        start_y = y // 8 - 2
        # As with the horizontal span, the row count comes from the un-offset
        # row (cap - y/8 + 1) but indexing starts at y/8 - 2, so the last row
        # carries the same -2 border shift (AEPROG 0x1fde..0x1fe9). Without it
        # the span bleeds two rows past the body into the floor below.
        end_y = min(0x13, (y + height - 1) // 8) - 2
        return PlayerController._or_cells(tiles, ((col, row) for row in range(start_y, end_y + 1)))

    @staticmethod
    def _or_cells(tiles: list[int], cells) -> int:
        value = 0
        for x, y in cells:
            if 0 <= x < ROOM_COLUMNS and 0 <= y < ROOM_ROWS:
                value |= tiles[y * ROOM_COLUMNS + x]
        return value
