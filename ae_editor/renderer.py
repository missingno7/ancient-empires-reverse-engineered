from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image, ImageDraw

from .constants import CELL_SIZE, DEFAULT_TERRAIN_CODE_TO_SPRITE, ROOM_COLUMNS, ROOM_ROWS
from .graphics import GraphicsSet
from .level_format import Level


@dataclass
class RenderOptions:
    mode: str = "terrain"  # terrain | codes_hex | codes_dec
    zoom: int = 2
    grid: bool = False
    crop_left_columns: int = 0
    crop_width_columns: int | None = None
    header_probe: bool = False


@dataclass
class RoomRenderer:
    graphics: GraphicsSet
    code_to_sprite: dict[int, int | None] = field(default_factory=lambda: dict(DEFAULT_TERRAIN_CODE_TO_SPRITE))

    debug_colours = [
        (0, 0, 0), (60, 60, 60), (50, 170, 255), (110, 240, 255),
        (40, 80, 220), (255, 190, 60), (255, 80, 60), (0, 220, 80),
        (220, 0, 220), (255, 255, 255), (200, 200, 80), (80, 220, 220),
        (255, 120, 220), (140, 140, 255), (180, 90, 40), (255, 0, 0),
    ]

    def render_room(self, level: Level, room_index: int, options: RenderOptions | None = None) -> Image.Image:
        options = options or RenderOptions()
        width = ROOM_COLUMNS * CELL_SIZE
        height = ROOM_ROWS * CELL_SIZE
        image = Image.new("RGBA", (width, height), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        room = level.room(room_index)

        if options.mode in {"codes_hex", "codes_dec"}:
            self._render_codes(image, draw, room.tiles, options.mode)
        else:
            self._render_terrain(image, room.tiles, level.theme)

        if options.header_probe:
            self._draw_header_probe(image, level)
        if options.grid:
            self._draw_grid(image)

        image = self._crop(image, options.crop_left_columns, options.crop_width_columns)
        if options.zoom != 1:
            image = image.resize((image.width * options.zoom, image.height * options.zoom), Image.Resampling.NEAREST)
        return image

    def _render_codes(self, image: Image.Image, draw: ImageDraw.ImageDraw, tiles: list[int], mode: str) -> None:
        for y in range(ROOM_ROWS):
            for x in range(ROOM_COLUMNS):
                value = tiles[y * ROOM_COLUMNS + x]
                colour = self.debug_colours[value % len(self.debug_colours)]
                x0 = x * CELL_SIZE
                y0 = y * CELL_SIZE
                draw.rectangle([x0, y0, x0 + CELL_SIZE - 1, y0 + CELL_SIZE - 1], fill=colour + (255,))
                if value:
                    label = f"{value:02X}" if mode == "codes_hex" else str(value)
                    draw.text((x0, y0 - 1), label, fill=(255, 255, 255, 255))

    def _render_terrain(self, image: Image.Image, tiles: list[int], theme: int) -> None:
        background = self.graphics.terrain_background(theme)
        if background:
            for yy in range(0, image.height, background.height):
                for xx in range(0, image.width, background.width):
                    image.alpha_composite(background, (xx, yy))

        # Current best behaviour from v11/v15: use the full tile byte as a terrain
        # code. Terrain sprites are larger than one cell (often 18x17), but they
        # are placed on an 8px grid, so overlap order matters.
        for y in range(ROOM_ROWS):
            for x in range(ROOM_COLUMNS):
                code = tiles[y * ROOM_COLUMNS + x]
                sprite_index = self.code_to_sprite.get(code)
                if sprite_index is None:
                    continue
                sprite = self.graphics.terrain_sprite(theme, sprite_index)
                if sprite is not None:
                    image.alpha_composite(sprite, (x * CELL_SIZE, y * CELL_SIZE))

    def _draw_grid(self, image: Image.Image) -> None:
        draw = ImageDraw.Draw(image)
        for y in range(ROOM_ROWS):
            for x in range(ROOM_COLUMNS):
                draw.rectangle(
                    [x * CELL_SIZE, y * CELL_SIZE, x * CELL_SIZE + CELL_SIZE - 1, y * CELL_SIZE + CELL_SIZE - 1],
                    outline=(0, 0, 0, 100),
                )

    def _draw_header_probe(self, image: Image.Image, level: Level) -> None:
        draw = ImageDraw.Draw(image)
        colours = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 160, 255, 255), (255, 255, 0, 255), (255, 0, 255, 255), (255, 128, 0, 255)]
        for n, byte in enumerate(level.header[0x0E:0x1A]):
            # Visual-only hypothesis probe. Not a solved object format.
            for x, y, offset in [((byte >> 4), (byte & 0x0F), 0), ((byte & 0x0F), (byte >> 4), 4)]:
                if x < ROOM_COLUMNS and y < ROOM_ROWS:
                    px = x * CELL_SIZE + offset
                    py = y * CELL_SIZE + offset
                    colour = colours[n % len(colours)]
                    draw.rectangle([px, py, px + 7, py + 7], outline=colour, width=1)
                    draw.text((px, py - 8), f"{n}:{byte:02X}", fill=colour)

    @staticmethod
    def _crop(image: Image.Image, crop_left_columns: int, crop_width_columns: int | None) -> Image.Image:
        if not crop_left_columns and crop_width_columns is None:
            return image
        x0 = max(0, crop_left_columns) * CELL_SIZE
        x1 = image.width if crop_width_columns is None else min(image.width, x0 + crop_width_columns * CELL_SIZE)
        return image.crop((x0, 0, x1, image.height))
