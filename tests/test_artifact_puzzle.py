from pathlib import Path

import pytest

from ancient_empires.engine.artifact_puzzle import ArtifactPuzzleState, PUZZLE_EMPTY
from ancient_empires.project import AncientEmpiresProject
from ancient_empires.rendering.artifact_puzzle_screen import ArtifactPuzzleScreenRenderer


EXE = Path("game_data/AEPROG.EXE")
DATS = [Path("game_data/AE000.DAT"), Path("game_data/AE001.DAT")]
pytestmark = pytest.mark.game_data


def test_level_1_expert_uses_recovered_puzzle_resource():
    puzzle = ArtifactPuzzleState(level_index=0, expert=True)

    assert puzzle.resource_id == 69


def test_level_1_explorer_uses_resource_65_and_cannot_flip():
    puzzle = ArtifactPuzzleState(level_index=0, expert=False)
    puzzle.take_or_drop()
    before = puzzle.held_orientation

    puzzle.flip_held_piece()

    assert puzzle.resource_id == 65
    assert puzzle.held_orientation == before


def test_puzzle_success_matches_right_side_tile_order():
    puzzle = ArtifactPuzzleState(level_index=0, expert=True)
    for row in range(4):
        for col in range(6):
            puzzle.cells[row][col].tile = PUZZLE_EMPTY
            puzzle.cells[row][col].orientation = 0

    tile = 0
    for row in range(4):
        for col in range(3, 6):
            puzzle.cells[row][col].tile = tile
            puzzle.cells[row][col].orientation = 0
            tile += 1

    assert puzzle.is_solved()


def test_artifact_puzzle_renderer_draws_screen():
    project = AncientEmpiresProject(EXE, DATS)
    puzzle = ArtifactPuzzleState(level_index=0, expert=True)
    image = ArtifactPuzzleScreenRenderer(project.graphics).render(puzzle)

    assert image.size == (320, 200)
    assert image.getbbox() is not None


def test_held_piece_moves_with_cursor_and_instruction_band_matches_difficulty():
    project = AncientEmpiresProject(EXE, DATS)
    renderer = ArtifactPuzzleScreenRenderer(project.graphics)
    explorer = ArtifactPuzzleState(level_index=0, expert=False)
    expert = ArtifactPuzzleState(level_index=0, expert=True)

    explorer.take_or_drop()
    held_left = renderer.render(explorer).tobytes()
    explorer.move_cursor(0, 1)
    held_right = renderer.render(explorer).tobytes()

    assert held_left != held_right
    assert renderer.render(explorer).tobytes() != renderer.render(expert).tobytes()
