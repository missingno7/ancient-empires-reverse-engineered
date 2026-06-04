"""Recovered exit-door sequence puzzle state."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random

from ..constants import ROOM_RECORD_SIZE, ROOM_TILE_COUNT
from .player import PlayerState
from ..game_data.level_format import Room


QUESTION_RECORD_COUNT = 40
QUESTION_RECORD_SIZE = 0x18
QUESTION_TABLE_OFFSET = 0x0DCC
GAME_DATA_SEGMENT = 0x0FA3
MZ_HEADER_SIZE = 0x200
ANSWER_ROOM_HEADER_SIZE = 0x40


@dataclass(frozen=True)
class AnswerSymbol:
    sprite_index: int
    transform: int


@dataclass(frozen=True)
class AnswerQuestion:
    cells: tuple[AnswerSymbol, ...]
    missing_mask: int
    hint_resource: int


def load_answer_questions(exe_path: Path | str) -> tuple[AnswerQuestion, ...]:
    """Read the 40 question records addressed at DS:0DCC by AEPROG 0x9b68."""
    blob = Path(exe_path).read_bytes()
    start = MZ_HEADER_SIZE + GAME_DATA_SEGMENT * 16 + QUESTION_TABLE_OFFSET
    end = start + QUESTION_RECORD_COUNT * QUESTION_RECORD_SIZE
    if end > len(blob):
        raise ValueError("AEPROG.EXE is too short for the answer-question table")

    questions: list[AnswerQuestion] = []
    for offset in range(start, end, QUESTION_RECORD_SIZE):
        record = blob[offset:offset + QUESTION_RECORD_SIZE]
        cells = tuple(
            AnswerSymbol(record[index * 2], record[index * 2 + 1])
            for index in range(11)
        )
        questions.append(AnswerQuestion(cells, record[0x16], record[0x17]))
    return tuple(questions)


def answer_room_player_start(decoded: bytes) -> tuple[int, int]:
    """Player spawn for the answer-puzzle room (AEPROG 0x471a).

    The room loader reads the start from the resource header: byte 1 is the
    half-resolution x (doubled and rounded down to a multiple of 4, like every
    other actor x), byte 2 is the raw y.  For AE001:020 these are 0x0C / 0x70,
    i.e. (24, 112) — lower-left on the floor, not the (0, 0) upper-left corner.
    """
    x = (decoded[1] * 2) & ~0x03
    y = decoded[2]
    return x, y


def parse_answer_puzzle_room(decoded: bytes) -> Room:
    """Parse room 0 from the special AE001:020 post-exit puzzle resource.

    Unlike a level's room records, the answer-puzzle room has *no* 2-byte room
    preamble: its 38x18 terrain grid begins immediately after the 0x40-byte
    header.  Applying the level ``ROOM_TERRAIN_OFFSET`` here read two bytes too
    far and shifted the whole grid two columns to the left (the bordering 0x07
    walls landed at columns 35/0 instead of 0/37).
    """
    start = ANSWER_ROOM_HEADER_SIZE
    record = decoded[start:start + ROOM_RECORD_SIZE]
    if len(record) != ROOM_RECORD_SIZE:
        raise ValueError("AE001:020 is too short for its answer-puzzle room")
    terrain_end = ROOM_TILE_COUNT
    return Room(
        part_index=0,
        index=0,
        record_offset=start,
        terrain_offset=start,
        preamble=b"",
        tiles=list(record[:terrain_end]),
        trailing=record[terrain_end:],
    )


class AnswerPuzzleState:
    """One playable three-door answer puzzle.

    AEPROG selects question ``level + expert*20``, hides one of the allowed
    cells, and randomizes the correct answer among door positions 9..11.
    """

    def __init__(
        self,
        exe_path: Path | str,
        *,
        level_index: int,
        expert: bool,
        theme: int,
        seed: int | None = None,
    ):
        questions = load_answer_questions(exe_path)
        question_index = max(0, min(19, int(level_index))) + (20 if expert else 0)
        self.question = questions[question_index]
        self.level_index = max(0, min(19, int(level_index)))
        self.expert = bool(expert)
        self.theme = int(theme) & 0x03
        self.background_resource = 30 + self.theme

        rng = random.Random(seed)
        allowed = [index for index in range(1, 9) if self.question.missing_mask & (1 << (index - 1))]
        self.missing_cell = rng.choice(allowed or list(range(1, 9)))
        self.correct_door = rng.randrange(3)
        distractors = [self.question.cells[9], self.question.cells[10]]
        rng.shuffle(distractors)
        answers: list[AnswerSymbol] = []
        for door in range(3):
            if door == self.correct_door:
                answers.append(self.question.cells[self.missing_cell])
            else:
                answers.append(distractors.pop())
        self.answers = tuple(answers)

        # AE001:020's special header spawns the player at the upper-left. The
        # normal player loop then applies gravity and lets the player traverse
        # the stored terrain and rope layout.
        self.player = PlayerState(x=0, y=0)
        self.attempts = 0
        self.solved = False
        self.door_frame = 0
        self.last_answer_correct: bool | None = None

    def choose(self, door: int) -> bool:
        self.attempts += 1
        self.last_answer_correct = int(door) == self.correct_door
        self.solved = self.last_answer_correct
        return self.solved
