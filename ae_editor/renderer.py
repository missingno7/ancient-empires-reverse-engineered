from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from PIL import Image, ImageDraw

from .constants import CELL_SIZE, DEFAULT_TERRAIN_CODE_TO_SPRITE, ROOM_COLUMNS, ROOM_ROWS
from .graphics import GraphicsSet
from .level_format import Level, LevelPart, Room
from .room_payload import PayloadPoint, parse_room_payload


@dataclass
class RenderOptions:
    # terrain            = terrain only, with known special tiles rendered as game sprites
    # terrain_payload    = terrain + debug markers from the room payload
    # terrain_objects    = terrain + first-pass known actor/control sprites from payload
    # payload_probe      = coordinate/table visualization of the trailing payload only
    mode: str = "terrain"
    zoom: int = 2
    grid: bool = False
    crop_left_columns: int = 0
    crop_width_columns: int | None = None
    header_probe: bool = False
    part_index: int = 0


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

    # v18: these values are not ordinary terrain in level 1 room 1. They form
    # a rope column. Older builds rendered them as the first large AE001 terrain
    # sprites, which is why the rope looked like “door/wall texture”.
    ROPE_CODES = {0x80, 0x90, 0xA0, 0xB0, 0xC0}
    PLATFORM_CODE = 0x07

    def render_room(self, level: Level, room_index: int, options: RenderOptions | None = None) -> Image.Image:
        options = options or RenderOptions()
        part = level.part(options.part_index)
        room = part.room(room_index)
        width = ROOM_COLUMNS * CELL_SIZE
        height = ROOM_ROWS * CELL_SIZE
        image = Image.new("RGBA", (width, height), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)

        if options.mode in {"codes_hex", "codes_dec"}:
            self._render_codes(image, draw, room.tiles, options.mode)
        elif options.mode == "trailing_hex":
            self._render_trailing_probe(image, draw, room)
        elif options.mode == "payload_probe":
            self._render_payload_probe(image, draw, room)
        else:
            self._render_terrain(image, room.tiles, part.theme)
            if options.mode == "terrain_payload":
                self._draw_payload_overlay(image, room)
            elif options.mode == "terrain_objects":
                self._draw_known_payload_objects(image, room)

        if options.header_probe:
            self._draw_header_probe(image, part)
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

    def _render_trailing_probe(self, image: Image.Image, draw: ImageDraw.ImageDraw, room: Room) -> None:
        draw.rectangle([0, 0, image.width, image.height], fill=(20, 20, 20, 255))
        cols = 19
        for i, value in enumerate(room.trailing[:cols * ROOM_ROWS]):
            x = i % cols
            y = i // cols
            colour = self.debug_colours[value % len(self.debug_colours)]
            x0 = x * 16
            y0 = y * 8
            draw.rectangle([x0, y0, x0 + 15, y0 + 7], fill=colour + (255,))
            if value:
                draw.text((x0, y0 - 1), f"{value:02X}", fill=(255, 255, 255, 255))

    def _render_terrain(self, image: Image.Image, tiles: list[int], theme: int) -> None:
        background = self.graphics.terrain_background(theme)
        if background:
            for yy in range(0, image.height, background.height):
                for xx in range(0, image.width, background.width):
                    image.alpha_composite(background, (xx, yy))

        platform_cells = self._platform_cells(tiles)
        rope_cells = self._rope_cells(tiles)

        # Main terrain pass. Known special/gameplay cells are deliberately not
        # passed through the terrain bank. They are rendered in later passes from
        # AE000 actor/control sprites.
        for y in range(ROOM_ROWS):
            for x in range(ROOM_COLUMNS):
                code = tiles[y * ROOM_COLUMNS + x]
                if (x, y) in platform_cells or (x, y) in rope_cells:
                    continue
                sprite_index = self.code_to_sprite.get(code)
                if sprite_index is None:
                    continue
                sprite = self.graphics.terrain_sprite(theme, sprite_index)
                if sprite is not None:
                    image.alpha_composite(sprite, (x * CELL_SIZE, y * CELL_SIZE))

        self._render_platform_runs(image, tiles)
        self._render_rope_codes(image, tiles)

    def _platform_cells(self, tiles: list[int]) -> set[tuple[int, int]]:
        return {(x, y) for y in range(ROOM_ROWS) for x in range(ROOM_COLUMNS) if tiles[y * ROOM_COLUMNS + x] == self.PLATFORM_CODE}

    def _rope_cells(self, tiles: list[int]) -> set[tuple[int, int]]:
        return {(x, y) for y in range(ROOM_ROWS) for x in range(ROOM_COLUMNS) if tiles[y * ROOM_COLUMNS + x] in self.ROPE_CODES}

    def _render_platform_runs(self, image: Image.Image, tiles: list[int]) -> None:
        horizontal = self.graphics.sprite("AE000", 47, 0)
        vertical = self.graphics.sprite("AE000", 48, 0)
        consumed: set[tuple[int, int]] = set()

        # Vertical first: the room-1 lift column is a vertical run of 0x07 cells.
        for x in range(ROOM_COLUMNS):
            y = 0
            while y < ROOM_ROWS:
                if tiles[y * ROOM_COLUMNS + x] != self.PLATFORM_CODE or (x, y) in consumed:
                    y += 1
                    continue
                y0 = y
                while y < ROOM_ROWS and tiles[y * ROOM_COLUMNS + x] == self.PLATFORM_CODE:
                    y += 1
                length = y - y0
                if length >= 3 and vertical is not None:
                    image.alpha_composite(vertical, (x * CELL_SIZE, y0 * CELL_SIZE))
                    for yy in range(y0, y):
                        consumed.add((x, yy))

        # Then horizontal runs. AE000:047 is 56x16, exactly a 7-cell platform.
        for y in range(ROOM_ROWS):
            x = 0
            while x < ROOM_COLUMNS:
                if tiles[y * ROOM_COLUMNS + x] != self.PLATFORM_CODE or (x, y) in consumed:
                    x += 1
                    continue
                x0 = x
                while x < ROOM_COLUMNS and tiles[y * ROOM_COLUMNS + x] == self.PLATFORM_CODE and (x, y) not in consumed:
                    x += 1
                length = x - x0
                if length >= 2 and horizontal is not None:
                    # Use one long platform sprite. If the data contains more
                    # than 7 cells, repeat the sprite every 7 cells; so far most
                    # observed moving platforms are exactly 7 cells wide.
                    remaining = length
                    px = x0
                    while remaining > 0:
                        image.alpha_composite(horizontal, (px * CELL_SIZE, y * CELL_SIZE))
                        px += 7
                        remaining -= 7

    def _render_rope_codes(self, image: Image.Image, tiles: list[int]) -> None:
        top = self.graphics.sprite("AE000", 5, 0)
        middle24 = self.graphics.sprite("AE000", 6, 0)
        middle8 = self.graphics.sprite("AE000", 7, 0)
        bottom = self.graphics.sprite("AE000", 8, 0)

        # Rope codes observed in level 1 room 1:
        #   90 = top cap, A0 = 24px middle segment, 80 = continuation/filler,
        #   B0 = short middle segment candidate, C0 = bottom cap.
        # Draw wide 16px rope sprites centered on the 8px map column.
        for y in range(ROOM_ROWS):
            for x in range(ROOM_COLUMNS):
                code = tiles[y * ROOM_COLUMNS + x]
                px = x * CELL_SIZE - 4
                py = y * CELL_SIZE
                if code == 0x90 and top is not None:
                    image.alpha_composite(top, (px, py))
                elif code == 0xA0 and middle24 is not None:
                    image.alpha_composite(middle24, (px, py))
                elif code == 0xB0 and middle8 is not None:
                    image.alpha_composite(middle8, (px, py))
                elif code == 0xC0 and bottom is not None:
                    image.alpha_composite(bottom, (px, py))
                # 0x80 is treated as continuation covered by the 24px segment.

    def _render_payload_probe(self, image: Image.Image, draw: ImageDraw.ImageDraw, room: Room) -> None:
        draw.rectangle([0, 0, image.width, image.height], fill=(8, 8, 18, 255))
        self._draw_grid(image)
        parsed = parse_room_payload(room)
        self._draw_payload_points(image, parsed.leading_triplets, (255, 180, 0, 255), "L")
        if parsed.best_table:
            colour = (0, 255, 160, 255) if parsed.best_table.schema == "typed6" else (0, 170, 255, 255)
            self._draw_payload_points(image, parsed.best_table.points, colour, parsed.best_table.schema)
        y = 2
        draw = ImageDraw.Draw(image)
        for item in parsed.candidate_tables[:5]:
            draw.text((2, y), f"off={item.offset:02X} {item.schema} count={item.count} score={item.score}", fill=(255, 255, 255, 255))
            y += 10

    def _draw_payload_overlay(self, image: Image.Image, room: Room) -> None:
        parsed = parse_room_payload(room)
        self._draw_payload_points(image, parsed.leading_triplets, (255, 180, 0, 255), "lead")
        if parsed.best_table:
            colour = (0, 255, 160, 255) if parsed.best_table.schema == "typed6" else (0, 170, 255, 255)
            self._draw_payload_points(image, parsed.best_table.points, colour, parsed.best_table.schema)

    def _draw_known_payload_objects(self, image: Image.Image, room: Room) -> None:
        """Very conservative first-pass payload rendering.

        The terrain grid now handles ropes and moving-platform graphics. The
        trailing room payload still contains real gameplay/control tables. The
        only object schema rendered as sprite here is the strong typed6 table at
        offset 0x1F, whose type 0x06 entries match switch/control coordinates in
        early rooms. Other candidate tables stay debug-only until verified.
        """
        parsed = parse_room_payload(room)
        switch_a = self.graphics.sprite("AE000", 40, 0)
        switch_b = self.graphics.sprite("AE000", 43, 0)
        if not parsed.best_table:
            return
        for p in parsed.best_table.points:
            if p.schema != "typed6" or p.type_id != 0x06:
                continue
            sprite = switch_b if p.subtype == 0 else switch_a
            if sprite is None:
                continue
            # Coordinates seem to be sprite anchors in pixels.  Draw with a tiny
            # left/up bias so the lever sits on the terrain instead of its center
            # point. This is marked research because exact anchor rules are not
            # fully proven yet.
            image.alpha_composite(sprite, (int(p.x) - 8, int(p.y) - 4))

    def _draw_payload_points(self, image: Image.Image, points: Iterable[PayloadPoint], colour, prefix: str) -> None:
        draw = ImageDraw.Draw(image)
        for p in points:
            x = int(p.x)
            y = int(p.y)
            if -24 <= x < image.width + 24 and -24 <= y < image.height + 24:
                draw.line([x - 5, y, x + 5, y], fill=colour, width=1)
                draw.line([x, y - 5, x, y + 5], fill=colour, width=1)
                draw.rectangle([x - 3, y - 3, x + 3, y + 3], outline=colour, width=1)
                label = f"{prefix}:{p.type_id:02X}" if p.type_id is not None else prefix
                draw.text((x + 4, y - 8), label, fill=colour)

    def _draw_grid(self, image: Image.Image) -> None:
        draw = ImageDraw.Draw(image)
        for y in range(ROOM_ROWS):
            for x in range(ROOM_COLUMNS):
                draw.rectangle(
                    [x * CELL_SIZE, y * CELL_SIZE, x * CELL_SIZE + CELL_SIZE - 1, y * CELL_SIZE + CELL_SIZE - 1],
                    outline=(0, 0, 0, 100),
                )

    def _draw_header_probe(self, image: Image.Image, part: LevelPart) -> None:
        draw = ImageDraw.Draw(image)
        colours = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 160, 255, 255), (255, 255, 0, 255), (255, 0, 255, 255), (255, 128, 0, 255)]
        for n, byte in enumerate(part.header[0x0E:0x1A]):
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
