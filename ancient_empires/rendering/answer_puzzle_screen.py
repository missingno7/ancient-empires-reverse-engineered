"""Rendering for the playable three-door answer puzzle."""
from __future__ import annotations

import copy

from PIL import Image, ImageDraw

from ..engine.answer_puzzle import AnswerPuzzleState, AnswerSymbol, parse_answer_puzzle_room
from ..game_data.graphics import GraphicsSet
from .game_screen import BACKGROUND_COLOR, GameHudState, GameScreenRenderer
from .room_renderer import RenderOptions


QUESTION_MARK_SPRITE = 145
BOARD_POSITIONS = tuple(
    (36 + column * 50, 41 + row * 36)
    for row in range(3)
    for column in range(3)
)
ANSWER_POSITIONS = ((246, 20), (246, 68), (246, 116))


class AnswerPuzzleScreenRenderer:
    def __init__(self, graphics: GraphicsSet, game_screen: GameScreenRenderer, answer_room_data: bytes):
        self.graphics = graphics
        self.game_screen = game_screen
        self.answer_room = parse_answer_puzzle_room(answer_room_data)

    def render(
        self,
        puzzle: AnswerPuzzleState,
        *,
        level,
        part_index: int,
        hud: GameHudState,
        display_mode: str = "vga",
        show_player: bool = True,
    ) -> Image.Image:
        previous_display_mode = self.graphics.display_mode
        self.graphics.set_display_mode(display_mode)
        try:
            screen = Image.new("RGBA", (320, 200), BACKGROUND_COLOR)
            draw = ImageDraw.Draw(screen)
            draw.rectangle((28, 40, 176, 148), fill="white")
            for top in (20, 68, 116):
                draw.rectangle((244, top, 290, top + 32), fill="white")
            background = self.graphics.sprite("AE001", puzzle.background_resource, 0)
            if background is not None:
                screen.alpha_composite(background, (8, 16))

            room_level = copy.copy(level)
            room_part = copy.copy(level.part(part_index))
            room_part.rooms = [self.answer_room]
            room_level.parts = [room_part]
            room = self.game_screen.room_renderer.render_room(
                room_level,
                0,
                RenderOptions(
                    mode="game",
                    zoom=1,
                    grid=False,
                    part_index=0,
                    draw_actors=False,
                    draw_player_start=False,
                    draw_background=False,
                    show_exit_door=False,
                    transparent_background=True,
                    display_mode=display_mode,
                ),
            )
            screen.alpha_composite(room, (8, 16))

            for index, symbol in enumerate(puzzle.question.cells[:9]):
                if index == puzzle.missing_cell:
                    self._draw_sprite(screen, QUESTION_MARK_SPRITE, 0, BOARD_POSITIONS[index])
                else:
                    self._draw_symbol(screen, symbol, BOARD_POSITIONS[index])
            for symbol, position in zip(puzzle.answers, ANSWER_POSITIONS):
                self._draw_symbol(screen, symbol, position)
            if puzzle.solved:
                self._draw_answer_door(screen, puzzle)

            if show_player:
                self._draw_player(screen, puzzle)
            self.game_screen.draw_hud(screen, hud)
            return screen
        finally:
            self.graphics.set_display_mode(previous_display_mode)

    def _draw_symbol(self, screen: Image.Image, symbol: AnswerSymbol, position: tuple[int, int]) -> None:
        self._draw_sprite(screen, symbol.sprite_index, symbol.transform, position)

    def _draw_sprite(
        self,
        screen: Image.Image,
        sprite_index: int,
        transform: int,
        position: tuple[int, int],
    ) -> None:
        sprite = self.graphics.sprite("AE001", 34, sprite_index)
        if sprite is None:
            return
        sprite = self._transform(sprite, transform)
        screen.alpha_composite(sprite, position)

    @staticmethod
    def _transform(sprite: Image.Image, transform: int) -> Image.Image:
        # AEPROG dispatches transform codes 0..5 through the table at DS:12A1.
        transform %= 6
        if transform == 1:
            return sprite.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if transform == 2:
            return sprite.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        if transform == 3:
            return sprite.transpose(Image.Transpose.ROTATE_180)
        if transform == 4:
            return sprite.rotate(90, resample=Image.Resampling.NEAREST, expand=False)
        if transform == 5:
            return sprite.rotate(270, resample=Image.Resampling.NEAREST, expand=False)
        return sprite

    def _draw_player(self, screen: Image.Image, puzzle: AnswerPuzzleState) -> None:
        player = self.graphics.sprite("AE000", 4, puzzle.player.frame)
        if player is not None:
            if puzzle.player.facing:
                player = player.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            screen.alpha_composite(player, (8 + puzzle.player.x - 8, 16 + puzzle.player.y - 16))

    def _draw_answer_door(self, screen: Image.Image, puzzle: AnswerPuzzleState) -> None:
        door = self.graphics.terrain_sprite(puzzle.theme, max(0, min(4, puzzle.door_frame)))
        if door is None:
            return
        screen.alpha_composite(door, ((244, 18), (244, 66), (244, 114))[puzzle.correct_door])
