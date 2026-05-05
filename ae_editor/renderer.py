from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image, ImageDraw

from .constants import CELL_SIZE, DEFAULT_TERRAIN_CODE_TO_SPRITE, ROOM_COLUMNS, ROOM_ROWS
from .coordinates import TERRAIN_ANCHOR, compact3_xy, platform_xy
from .graphics import GraphicsSet
from .level_format import Level, Room
from .object_mapping import visual_sprite_ref
from .room_payload import (
    ObjectTableEntry,
    parse_exe_payload_directory,
    parse_platform_triplets,
    visual_compact3_table,
    laser_crystal_table,
)


@dataclass
class RenderOptions:
    """Rendering options exposed by the cleaned-up viewer."""

    mode: str = "game"  # game, collision, payload_debug, codes_hex, trailing_hex
    zoom: int = 2
    grid: bool = False
    part_index: int = 0  # 0 = Explorer, 1 = Expert


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

    ROPE_CODES = {0x80, 0x90, 0xA0, 0xB0, 0xC0}
    ROPE_X_BIAS = 0
    SOLID_INVISIBLE_CODE = 0x07

    def render_room(self, level: Level, room_index: int, options: RenderOptions | None = None) -> Image.Image:
        options = options or RenderOptions()
        part = level.part(options.part_index)
        room = part.room(room_index)
        image = Image.new("RGBA", (ROOM_COLUMNS * CELL_SIZE, ROOM_ROWS * CELL_SIZE), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        self._current_theme = part.theme
        self._current_level_index = level.index

        if options.mode == "codes_hex":
            self._render_codes(image, draw, room)
        elif options.mode == "trailing_hex":
            self._render_trailing_probe(image, draw, room)
        else:
            self._render_terrain(image, room, part.theme)
            if options.mode == "game":
                self._draw_platforms(image, room)
                self._draw_control_records(image, room, labels=False)
                self._draw_section_a_markers(image, room, labels=False)
                self._draw_laser_crystals(image, room, labels=False)
                self._draw_visual_objects(image, room, labels=False)
            elif options.mode == "collision":
                self._draw_collision_debug(image, room)
            elif options.mode == "payload_debug":
                self._draw_platforms(image, room)
                self._draw_control_records(image, room, labels=True)
                self._draw_section_a_markers(image, room, labels=True)
                self._draw_laser_crystals(image, room, labels=True)
                self._draw_visual_objects(image, room, labels=True)
                self._draw_payload_debug(image, room)

        if options.grid:
            self._draw_grid(image)
        if options.zoom != 1:
            image = image.resize((image.width * options.zoom, image.height * options.zoom), Image.Resampling.NEAREST)
        return image

    def _blit(self, image: Image.Image, sprite: Image.Image, x: int, y: int) -> None:
        image.alpha_composite(sprite, (x, y))

    def _render_terrain(self, image: Image.Image, room: Room, theme: int) -> None:
        background = self.graphics.terrain_background(theme)
        if background:
            for yy in range(0, image.height, background.height):
                for xx in range(0, image.width, background.width):
                    self._blit(image, background, xx, yy)

        rope_cells = self._rope_cells(room)
        for y in range(ROOM_ROWS):
            for x in range(ROOM_COLUMNS):
                code = room.get(x, y)
                if code == self.SOLID_INVISIBLE_CODE or (x, y) in rope_cells:
                    continue
                sprite_index = self.code_to_sprite.get(code)
                if sprite_index is None:
                    continue
                sprite = self.graphics.terrain_sprite(theme, sprite_index)
                if sprite is not None:
                    self._blit(image, sprite, x * CELL_SIZE + TERRAIN_ANCHOR.x, y * CELL_SIZE + TERRAIN_ANCHOR.y)
        self._render_rope(image, room)

    def _rope_cells(self, room: Room) -> set[tuple[int, int]]:
        return {(x, y) for y in range(ROOM_ROWS) for x in range(ROOM_COLUMNS) if room.get(x, y) in self.ROPE_CODES}

    def _render_rope(self, image: Image.Image, room: Room) -> None:
        sprites = {
            0x90: self.graphics.sprite("AE000", 5, 0),  # top
            0xA0: self.graphics.sprite("AE000", 6, 0),  # long middle
            0xB0: self.graphics.sprite("AE000", 7, 0),  # short middle
            0xC0: self.graphics.sprite("AE000", 8, 0),  # bottom
        }
        for y in range(ROOM_ROWS):
            for x in range(ROOM_COLUMNS):
                sprite = sprites.get(room.get(x, y))
                if sprite is not None:
                    self._blit(image, sprite, x * CELL_SIZE + self.ROPE_X_BIAS, y * CELL_SIZE)

    def _draw_platforms(self, image: Image.Image, room: Room) -> None:
        horizontal = self.graphics.sprite("AE000", 47, 0)
        vertical = self.graphics.sprite("AE000", 48, 0)
        for triplet in parse_platform_triplets(room):
            x, y = platform_xy(triplet)
            if triplet.orientation == "vertical" and vertical is not None:
                self._blit(image, vertical, x, y)
            elif triplet.orientation == "horizontal" and horizontal is not None:
                self._blit(image, horizontal, x, y)

    def _draw_control_records(self, image: Image.Image, room: Room, *, labels: bool) -> None:
        directory = parse_exe_payload_directory(room)
        if not directory:
            return
        draw = ImageDraw.Draw(image)
        button = self.graphics.sprite("AE000", 39, 0)
        pressed_button = self.graphics.sprite("AE000", 42, 0)
        ant = self.graphics.sprite("AE000", 20, 0)
        for record in directory.control_records:
            if len(record.raw) < 6:
                continue
            rec_type, subtype, x_raw, y_raw, arg_a, arg_b = record.raw[:6]
            sprite = None
            x = x_raw * 2 - 8
            y = y_raw - 16
            if rec_type == 0x06 and arg_b in (0x40, 0x41):
                sprite = pressed_button if arg_b == 0x41 and pressed_button is not None else button
            elif rec_type == 0x06 and subtype == 0x02 and arg_a == 0 and arg_b == 0:
                # Confirmed in L6/R5 as ant-like actor. Exact actor table is
                # still not fully solved, so this remains narrowly scoped.
                sprite = ant
                x = x_raw * 4 - 4
                y = y_raw - 12
            if sprite is not None:
                self._blit(image, sprite, x, y)
                if labels:
                    self._label(draw, x, y, record.label)


    def _draw_section_a_markers(self, image: Image.Image, room: Room, *, labels: bool) -> None:
        """Render the first compact3 section as lightweight markers.

        This section was previously ignored. In level 9 / Expert / room 0 it
        contains the three hanging round markers visible in the game screenshot.
        Treating it as a separate section is cleaner than folding those entries
        into the main visual decor lookup.
        """
        directory = parse_exe_payload_directory(room)
        if not directory or not directory.sections or not directory.sections.section_a:
            return
        marker = self.graphics.sprite("AE000", 9, 0)
        if marker is None:
            return
        draw = ImageDraw.Draw(image)
        for entry in directory.sections.section_a.entries:
            # Same half-x family as compact3 visuals, but these markers are
            # anchored closer to their hanging point.
            x = entry.x_raw * 2 - marker.width // 2
            y = entry.y - marker.height
            self._blit(image, marker, x, y)
            if labels:
                self._label(draw, x, y, f"section_a {entry.label}")

    def _draw_laser_crystals(self, image: Image.Image, room: Room, *, labels: bool) -> None:
        table = laser_crystal_table(room)
        if not table:
            return
        draw = ImageDraw.Draw(image)
        for entry in table.entries:
            sprite = self.graphics.sprite("AE000", 19, entry.code)
            if sprite is None:
                continue
            x, y = compact3_xy(entry, sprite, "screen_exe")
            self._blit(image, sprite, x, y)
            if labels:
                self._label(draw, x, y, f"crystal @{table.offset:02X} {entry.label}")

    def _draw_visual_objects(self, image: Image.Image, room: Room, *, labels: bool) -> None:
        table = visual_compact3_table(room)
        if not table:
            return
        draw = ImageDraw.Draw(image)
        for entry in table.entries:
            sprite = self._sprite_for_visual_entry(entry, room)
            if sprite is None:
                if labels:
                    x, y = entry.x_raw * 2, entry.y
                    draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 0, 255, 255))
                    draw.text((x + 4, y - 6), f"@{table.offset:02X} {entry.label}", fill=(255, 255, 0, 255))
                continue
            x, y = compact3_xy(entry, sprite, "screen_exe")
            self._blit(image, sprite, x, y)
            if labels:
                self._label(draw, x, y, f"visual @{table.offset:02X} {entry.label}")

    def _sprite_for_visual_entry(self, entry: ObjectTableEntry, room: Room) -> Image.Image | None:
        ref = visual_sprite_ref(
            entry,
            theme=getattr(self, "_current_theme", 0),
            level_index=getattr(self, "_current_level_index", None),
            room_index=room.index,
            page_index=room.page_index,
        )
        return self.graphics.sprite(ref.archive, ref.resource_id, ref.sprite_index)

    def _draw_payload_debug(self, image: Image.Image, room: Room) -> None:
        draw = ImageDraw.Draw(image)
        for triplet in parse_platform_triplets(room):
            x, y = platform_xy(triplet)
            draw.rectangle([x, y, x + 10, y + 10], outline=(255, 180, 0, 255), width=1)
            draw.text((x + 2, y - 8), triplet.label, fill=(255, 180, 0, 255))
        directory = parse_exe_payload_directory(room)
        if directory and directory.sections:
            y = 2
            lines = [
                f"dir@{directory.base_offset:02X} count={directory.directory_count} selected={directory.selected_visual_index}",
                f"records={len(directory.control_records)} visual={None if directory.sections.visual is None else hex(directory.sections.visual.offset)}",
            ]
            for line in lines:
                draw.rectangle([0, y, 240, y + 10], fill=(0, 0, 0, 180))
                draw.text((2, y), line, fill=(255, 255, 255, 255))
                y += 11

    def _draw_collision_debug(self, image: Image.Image, room: Room) -> None:
        draw = ImageDraw.Draw(image)
        for y in range(ROOM_ROWS):
            for x in range(ROOM_COLUMNS):
                if room.get(x, y) == self.SOLID_INVISIBLE_CODE:
                    x0 = x * CELL_SIZE
                    y0 = y * CELL_SIZE
                    draw.rectangle([x0, y0, x0 + CELL_SIZE - 1, y0 + CELL_SIZE - 1], outline=(255, 0, 255, 180))
                    draw.line([x0, y0, x0 + CELL_SIZE - 1, y0 + CELL_SIZE - 1], fill=(255, 0, 255, 120))

    def _render_codes(self, image: Image.Image, draw: ImageDraw.ImageDraw, room: Room) -> None:
        for y in range(ROOM_ROWS):
            for x in range(ROOM_COLUMNS):
                value = room.get(x, y)
                colour = self.debug_colours[value % len(self.debug_colours)]
                x0 = x * CELL_SIZE
                y0 = y * CELL_SIZE
                draw.rectangle([x0, y0, x0 + CELL_SIZE - 1, y0 + CELL_SIZE - 1], fill=colour + (255,))
                if value:
                    draw.text((x0, y0 - 1), f"{value:02X}", fill=(255, 255, 255, 255))

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

    def _draw_grid(self, image: Image.Image) -> None:
        draw = ImageDraw.Draw(image)
        for y in range(ROOM_ROWS):
            for x in range(ROOM_COLUMNS):
                draw.rectangle([x * CELL_SIZE, y * CELL_SIZE, x * CELL_SIZE + CELL_SIZE - 1, y * CELL_SIZE + CELL_SIZE - 1], outline=(0, 0, 0, 100))

    @staticmethod
    def _label(draw: ImageDraw.ImageDraw, x: int, y: int, text: str) -> None:
        draw.rectangle([x, y, x + max(60, len(text) * 5), y + 10], fill=(0, 0, 0, 180))
        draw.text((x + 1, y), text, fill=(255, 255, 0, 255))
