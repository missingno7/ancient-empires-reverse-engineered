from pathlib import Path

from ae_game.app.main_window import (
    EXIT_ANIMATION_STEPS,
    EXIT_KEEP_PLAYER_FRAME,
    exit_animation_step,
    player_aligned_with_exit_door,
)
from ancient_empires.engine.answer_puzzle import (
    AnswerPuzzleState,
    answer_room_player_start,
    load_answer_questions,
    parse_answer_puzzle_room,
)
from ancient_empires.project import AncientEmpiresProject
from ancient_empires.engine.player import PlayerState
from ancient_empires.engine.player import PlayerController, PlayerInput
from ancient_empires.game_data.room_payload import HeaderExitDoor
from ancient_empires.rendering.answer_puzzle_screen import AnswerPuzzleScreenRenderer
from ancient_empires.rendering.game_screen import GameHudState, GameScreenRenderer


EXE = Path("game_data/AEPROG.EXE")
DATS = [Path("game_data/AE000.DAT"), Path("game_data/AE001.DAT")]


def test_question_table_contains_explorer_and_expert_records():
    questions = load_answer_questions(EXE)

    assert len(questions) == 40
    assert len(questions[0].cells) == 11
    assert questions[0].missing_mask == 0x80


def test_answer_puzzle_randomizes_missing_cell_and_correct_door_from_asm_data():
    puzzle = AnswerPuzzleState(EXE, level_index=0, expert=False, theme=0, seed=3)

    assert puzzle.question.missing_mask & (1 << (puzzle.missing_cell - 1))
    assert puzzle.answers[puzzle.correct_door] == puzzle.question.cells[puzzle.missing_cell]
    assert puzzle.background_resource == 30


def test_answer_puzzle_room_comes_from_special_resource_20():
    project = AncientEmpiresProject(EXE, DATS)
    room = parse_answer_puzzle_room(project.ae001[20].decoded)

    assert room.nonzero_tile_count > 0
    assert any(code in (0x90, 0xA0, 0xB0, 0xC0) for code in room.tiles)


def test_answer_room_player_start_comes_from_resource_header():
    project = AncientEmpiresProject(EXE, DATS)

    # AE001:020 header bytes 1/2 are 0x0C / 0x70 -> (24, 112), the lower-left
    # floor spawn (AEPROG 0x471a), not the (0, 0) upper-left corner.
    assert answer_room_player_start(project.ae001[20].decoded) == (24, 112)


def test_exit_animation_opens_lets_player_enter_then_closes_with_no_player():
    # AEPROG 0x233e: door opens 1->4 (player standing), player walks in
    # (frames 12->15), then the door closes 3->0 with the player gone.
    assert EXIT_ANIMATION_STEPS == 12
    door_frames = [exit_animation_step(s)[0] for s in range(EXIT_ANIMATION_STEPS)]
    assert door_frames == [1, 2, 3, 4, 4, 4, 4, 4, 3, 2, 1, 0]

    # Opening phase keeps the standing frame.
    assert all(exit_animation_step(s)[1] == EXIT_KEEP_PLAYER_FRAME for s in range(4))
    # Enter phase plays the walk-in frames.
    assert [exit_animation_step(s)[1] for s in range(4, 8)] == [12, 13, 14, 15]
    # Closing phase hides the player.
    assert all(exit_animation_step(s)[1] is None for s in range(8, 12))


def test_answer_puzzle_room_uses_normal_player_rope_climbing():
    project = AncientEmpiresProject(EXE, DATS)
    room = parse_answer_puzzle_room(project.ae001[20].decoded)
    controller = PlayerController(project.levels[0], 0, 0)
    # The rope sits at terrain column 25 (x=192); see parse_answer_puzzle_room,
    # which no longer shifts the grid two columns left.
    controller.state = PlayerState(x=192, y=40)

    controller.tick(PlayerInput(jump=True), room.tiles)

    assert controller.state.on_ladder


def test_exit_door_requires_the_narrow_asm_player_anchor_box():
    door = HeaderExitDoor(room_index=0, x_raw=40, y_raw=80)

    assert player_aligned_with_exit_door(PlayerState(x=80, y=80), door)
    assert not player_aligned_with_exit_door(PlayerState(x=76, y=80), door)
    # Our PlayerController grounds a pixel or two above the door's y_raw floor
    # line, so the box has a 4px slack on the upper edge (y_raw - 4).
    assert player_aligned_with_exit_door(PlayerState(x=80, y=78), door)
    assert not player_aligned_with_exit_door(PlayerState(x=80, y=75), door)
    assert not player_aligned_with_exit_door(PlayerState(x=80, y=97), door)
    # AEPROG does not add movement-state exclusions after the coordinate test.
    assert player_aligned_with_exit_door(PlayerState(x=80, y=80, on_ladder=1), door)


def test_only_correct_door_solves_answer_puzzle():
    puzzle = AnswerPuzzleState(EXE, level_index=0, expert=False, theme=0, seed=3)
    wrong = (puzzle.correct_door + 1) % 3

    assert not puzzle.choose(wrong)
    assert puzzle.choose(puzzle.correct_door)
    assert puzzle.solved


def test_answer_puzzle_renderer_uses_symbols_background_and_hud():
    project = AncientEmpiresProject(EXE, DATS)
    game_screen = GameScreenRenderer(project.graphics, project.renderer)
    renderer = AnswerPuzzleScreenRenderer(project.graphics, game_screen, project.ae001[20].decoded)
    puzzle = AnswerPuzzleState(EXE, level_index=0, expert=False, theme=0, seed=3)

    image = renderer.render(
        puzzle,
        level=project.levels[0],
        part_index=0,
        hud=GameHudState(artifact_pieces=6),
    )

    assert image.size == (320, 200)
    assert project.graphics.sprite("AE001", 34, 145) is not None
    assert image.getbbox() is not None


def test_interpolation_treats_large_jumps_as_teleport():
    from ae_game.app.main_window import GameWindow, INTERPOLATION_SNAP_DISTANCE

    # Small steps interpolate; a reset/respawn jump (e.g. a projectile snapping
    # back to its origin) must not be smoothed.
    assert not GameWindow._is_teleport((100, 100), (104, 100))
    assert not GameWindow._is_teleport((100, 100), (100 + INTERPOLATION_SNAP_DISTANCE, 100))
    assert GameWindow._is_teleport((100, 100), (100 + INTERPOLATION_SNAP_DISTANCE + 1, 100))
    assert GameWindow._is_teleport((100, 100), (100, 200))
