"""Recovered end-of-artifact puzzle state.

AEPROG stores the puzzle board at DS:C316 as a 4x6 table of 2-byte cells:
tile id and orientation.  The left three columns are the shuffled loose-piece
area; the right three columns are the solved assembly area.
"""
from __future__ import annotations

from dataclasses import dataclass
import random


PUZZLE_ROWS = 4
PUZZLE_COLUMNS = 6
PUZZLE_EMPTY = 0xFF


@dataclass
class ArtifactPuzzleCell:
    tile: int = PUZZLE_EMPTY
    orientation: int = 0


class ArtifactPuzzleState:
    def __init__(self, *, level_index: int, expert: bool):
        self.level_index = level_index
        self.expert = expert
        self.cursor_row = 0
        self.cursor_col = 0
        self.held_tile = PUZZLE_EMPTY
        self.held_orientation = 0
        self.solved = False
        self.cells = [
            [ArtifactPuzzleCell() for _col in range(PUZZLE_COLUMNS)]
            for _row in range(PUZZLE_ROWS)
        ]
        self._shuffle_initial_tiles()

    @property
    def resource_id(self) -> int:
        region = max(0, min(4, self.level_index // 4))
        chamber = max(0, min(3, self.level_index % 4))
        return 65 + chamber + region * 8 + (4 if self.expert else 0)

    def _shuffle_initial_tiles(self) -> None:
        positions = [(row, col) for row in range(PUZZLE_ROWS) for col in range(3)]
        rng = random.Random((self.level_index + 1) * 17 + (1 if self.expert else 0))
        rng.shuffle(positions)
        for tile, (row, col) in enumerate(positions):
            self.cells[row][col].tile = tile
            self.cells[row][col].orientation = rng.randrange(4) if self.expert else 0

    def move_cursor(self, d_row: int, d_col: int) -> None:
        self.cursor_row = (self.cursor_row + d_row) % PUZZLE_ROWS
        self.cursor_col = (self.cursor_col + d_col) % PUZZLE_COLUMNS

    def take_or_drop(self) -> None:
        cell = self.cells[self.cursor_row][self.cursor_col]
        if self.held_tile == PUZZLE_EMPTY:
            if cell.tile == PUZZLE_EMPTY:
                return
            self.held_tile = cell.tile
            self.held_orientation = cell.orientation
            cell.tile = PUZZLE_EMPTY
            cell.orientation = 0
            return
        if cell.tile != PUZZLE_EMPTY:
            return
        cell.tile = self.held_tile
        cell.orientation = self.held_orientation
        self.held_tile = PUZZLE_EMPTY
        self.held_orientation = 0
        self.solved = self.is_solved()

    def flip_held_piece(self) -> None:
        if self.held_tile == PUZZLE_EMPTY or not self.expert:
            return
        self.held_orientation = (self.held_orientation + 1) % 4

    def is_solved(self) -> bool:
        orientation_mode = self._target_orientation_mode()
        expected = 0
        if orientation_mode == 0:
            for row in range(PUZZLE_ROWS):
                for col in range(3, 6):
                    if not self._matches(row, col, expected, 0):
                        return False
                    expected += 1
        elif orientation_mode == 1:
            for row in range(PUZZLE_ROWS):
                for col in range(5, 2, -1):
                    if not self._matches(row, col, expected, 1):
                        return False
                    expected += 1
        elif orientation_mode == 2:
            for row in range(3, -1, -1):
                for col in range(5, 2, -1):
                    if not self._matches(row, col, expected, 2):
                        return False
                    expected += 1
        else:
            for row in range(3, -1, -1):
                for col in range(3, 6):
                    if not self._matches(row, col, expected, 3):
                        return False
                    expected += 1
        return True

    def _matches(self, row: int, col: int, tile: int, orientation: int) -> bool:
        cell = self.cells[row][col]
        return cell.tile == tile and cell.orientation == orientation

    def _target_orientation_mode(self) -> int:
        # ASM reads byte DS:C31D, which is the orientation byte of cell (0, 3).
        # Solving therefore depends on how the player orients the first target
        # tile, then validates the matching transformed order.
        return self.cells[0][3].orientation & 0x03
