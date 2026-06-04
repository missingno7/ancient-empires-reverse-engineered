"""Renderer for the recovered Ancient Artifact puzzle screen."""
from __future__ import annotations

from PIL import Image, ImageDraw

from ..engine.artifact_puzzle import ArtifactPuzzleState, PUZZLE_EMPTY
from ..game_data.graphics import GraphicsSet
from .game_screen import BACKGROUND_COLOR, SCREEN_HEIGHT, SCREEN_WIDTH


class ArtifactPuzzleScreenRenderer:
    def __init__(self, graphics: GraphicsSet):
        self.graphics = graphics

    def render(self, puzzle: ArtifactPuzzleState, *, display_mode: str = "vga") -> Image.Image:
        previous_display_mode = self.graphics.display_mode
        self.graphics.set_display_mode(display_mode)
        try:
            screen = Image.new("RGBA", (SCREEN_WIDTH, SCREEN_HEIGHT), BACKGROUND_COLOR)
            self._draw_frame(screen, puzzle)
            artifact = self.graphics.sprite("AE001", puzzle.resource_id, 0)
            title = self.graphics.sprite("AE001", puzzle.resource_id, 1)
            if artifact is not None:
                self._draw_cells(screen, puzzle, artifact)
                self._draw_held_piece(screen, puzzle, artifact)
            if title is not None:
                screen.alpha_composite(title, (140, 44))
            self._draw_cursor(screen, puzzle)
            return screen
        finally:
            self.graphics.set_display_mode(previous_display_mode)

    def _draw_frame(self, screen: Image.Image, puzzle: ArtifactPuzzleState) -> None:
        background = self.graphics.sprite("AE001", 63, 0)
        if background is not None:
            screen.alpha_composite(background, (8, 16))
        bands = self.graphics.ae001_banks.get(64, [])
        if bands:
            screen.alpha_composite(bands[1 if puzzle.expert and len(bands) > 1 else 0], (6, 162))

    def _draw_cells(self, screen: Image.Image, puzzle: ArtifactPuzzleState, artifact: Image.Image) -> None:
        for row in range(4):
            for col in range(6):
                cell = puzzle.cells[row][col]
                if cell.tile == PUZZLE_EMPTY:
                    continue
                piece = self._piece_image(artifact, cell.tile, cell.orientation)
                x, y = self._cell_xy(row, col)
                screen.alpha_composite(piece, (x, y))

    def _draw_held_piece(self, screen: Image.Image, puzzle: ArtifactPuzzleState, artifact: Image.Image) -> None:
        if puzzle.held_tile == PUZZLE_EMPTY:
            return
        piece = self._piece_image(artifact, puzzle.held_tile, puzzle.held_orientation)
        screen.alpha_composite(piece, self._cell_xy(puzzle.cursor_row, puzzle.cursor_col))

    def _draw_cursor(self, screen: Image.Image, puzzle: ArtifactPuzzleState) -> None:
        x, y = self._cell_xy(puzzle.cursor_row, puzzle.cursor_col)
        draw = ImageDraw.Draw(screen)
        draw.rectangle((x - 1, y - 1, x + 32, y + 24), outline=(255, 255, 85, 255), width=1)

    @staticmethod
    def _piece_image(artifact: Image.Image, tile: int, orientation: int) -> Image.Image:
        sx = (tile % 3) * 32
        sy = (tile // 3) * 24
        piece = artifact.crop((sx, sy, sx + 32, sy + 24))
        orientation &= 0x03
        if orientation & 0x01:
            piece = piece.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if orientation & 0x02:
            piece = piece.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        return piece

    @staticmethod
    def _cell_xy(row: int, col: int) -> tuple[int, int]:
        if col < 3:
            return 28 + col * 36, 43 + row * 28
        return 140 + (col - 3) * 32, 54 + row * 24
