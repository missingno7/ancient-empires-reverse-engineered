from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image, ImageDraw

from .constants import CELL_SIZE, DEFAULT_TERRAIN_CODE_TO_SPRITE, ROOM_COLUMNS, ROOM_ROWS
from .coordinates import TERRAIN_ANCHOR, compact3_xy, control_xy, platform_xy
from .conveyors import ConveyorSpec, compose_conveyor
from .graphics import GraphicsSet
from .level_format import Level, Room
from .object_mapping import visual_render_layer, visual_sprite_ref
from .room_payload import (
    ObjectTableEntry,
    control_commands,
    parse_exe_payload_directory,
    parse_platform_triplets,
    visual_compact3_table,
    laser_crystal_table,
    room_tail_marker,
    header_object_candidates,
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
    CONVEYOR_TILE_CODES = {0x0F: "grey", 0x1F: "teal"}
    # Rope markers sit on the left edge of the 8×8 grid cell, but the visible
    # rope art is slightly right of that logical column in the captured game.
    ROPE_X_BIAS = 4
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
            # EXE-style order: background, high-bit visual entries, terrain,
            # then foreground/control/low-bit visual entries. This fixes many
            # cases where wall decorations were painted over solid geometry.
            self._draw_background(image, part.theme)
            if options.mode == "game":
                self._draw_visual_objects(image, room, labels=False, layer="background")
            self._draw_terrain_tiles(image, room, part.theme)
            self._render_rope(image, room)

            if options.mode == "game":
                self._draw_conveyor_tiles(image, room)
                self._draw_platforms(image, room)
                self._draw_control_records(image, room, labels=False)
                self._draw_puzzle_markers(image, room, labels=False)
                self._draw_record12_puzzle_panels(image, room, labels=False)
                self._draw_laser_crystals(image, room, labels=False)
                self._draw_visual_objects(image, room, labels=False, layer="foreground")
            elif options.mode == "collision":
                self._draw_collision_debug(image, room)
            elif options.mode == "payload_debug":
                self._draw_visual_objects(image, room, labels=True, layer="background")
                self._draw_conveyor_tiles(image, room)
                self._draw_platforms(image, room)
                self._draw_control_records(image, room, labels=True)
                self._draw_puzzle_markers(image, room, labels=True)
                self._draw_record12_puzzle_panels(image, room, labels=True)
                self._draw_laser_crystals(image, room, labels=True)
                self._draw_visual_objects(image, room, labels=True, layer="foreground")
                self._draw_actor_probes(image, room, part.header)
                self._draw_payload_debug(image, room)

        if options.grid:
            self._draw_grid(image)
        if options.zoom != 1:
            image = image.resize((image.width * options.zoom, image.height * options.zoom), Image.Resampling.NEAREST)
        return image

    def _blit(self, image: Image.Image, sprite: Image.Image, x: int, y: int) -> None:
        image.alpha_composite(sprite, (int(x), int(y)))

    def _draw_background(self, image: Image.Image, theme: int) -> None:
        background = self.graphics.terrain_background(theme)
        if not background:
            return
        for yy in range(0, image.height, background.height):
            for xx in range(0, image.width, background.width):
                self._blit(image, background, xx, yy)

    def _draw_terrain_tiles(self, image: Image.Image, room: Room, theme: int) -> None:
        rope_cells = self._rope_cells(room)
        for y in range(ROOM_ROWS):
            for x in range(ROOM_COLUMNS):
                code = room.get(x, y)
                if code == self.SOLID_INVISIBLE_CODE or code in self.CONVEYOR_TILE_CODES or (x, y) in rope_cells:
                    continue
                sprite_index = self.code_to_sprite.get(code)
                if sprite_index is None:
                    continue
                sprite = self.graphics.terrain_sprite(theme, sprite_index)
                if sprite is not None:
                    self._blit(image, sprite, x * CELL_SIZE + TERRAIN_ANCHOR.x, y * CELL_SIZE + TERRAIN_ANCHOR.y)

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


    def _draw_conveyor_tiles(self, image: Image.Image, room: Room) -> None:
        """Render conveyor belts directly from terrain tile runs.

        User screenshots plus codes_hex confirmed that belts behave like rope:
        the room grid contains special non-terrain tile codes.  The visible belt
        is not a one-sprite object and should not be inferred from trigger/control
        records.  AE000:038 stores left/middle/right pieces for four animation
        frames and two colour/direction families; static previews use frame 0.
        """
        parts = [self.graphics.sprite("AE000", 38, i) for i in range(24)]
        y_bias = -8
        x_bias = -4
        for y in range(ROOM_ROWS):
            x = 0
            while x < ROOM_COLUMNS:
                code = room.get(x, y)
                kind = self.CONVEYOR_TILE_CODES.get(code)
                if kind is None:
                    x += 1
                    continue
                start = x
                while x < ROOM_COLUMNS and room.get(x, y) == code:
                    x += 1
                # Conveyor tile runs need one extra cell on the right: the grid
                # marks occupied conveyor cells, while the visual right cap extends
                # past the final marker.
                width = max(8, (x - start + 1) * CELL_SIZE)
                strip = compose_conveyor(parts, ConveyorSpec(kind=kind, x=0, y=0, width=width, frame=0))
                if strip is not None:
                    self._blit(image, strip, start * CELL_SIZE + x_bias, y * CELL_SIZE + y_bias)

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
        draw = ImageDraw.Draw(image)
        ceiling_button = self.graphics.sprite("AE000", 39, 0)
        floor_button = self.graphics.sprite("AE000", 40, 0)
        pressed_button = self.graphics.sprite("AE000", 42, 0)
        ant = self.graphics.sprite("AE000", 20, 0)
        for cmd in control_commands(room):
            if cmd.command is None or cmd.x_raw is None or cmd.y_raw is None:
                continue
            command = cmd.command
            arg_a = cmd.arg_a or 0
            arg_b = cmd.arg_b or 0

            # Aha from the v31 cleanup: LengthPrefixedControlRecord.raw[0] is
            # the byte length, not the command.  The real command is body[0].
            # This removes several old false positives where length 0x06/0x07
            # was treated as an object id.
            if command in (0x00, 0x01) and arg_b in (0x10, 0x11, 0x12, 0x13):
                # v33: visible conveyor belts are terrain-grid special tiles
                # (0x0F/0x1F), much like ropes. These control commands may
                # still carry trigger/motion metadata, but rendering them here
                # creates misplaced duplicate belts. Keep them visible only in
                # payload_debug labels for now.
                if labels:
                    x, y = control_xy(cmd, mode="button")
                    self._label(draw, x, y, f"belt-meta {cmd.label}")
                continue

            sprite = None
            mode = "button"
            if command in (0x00, 0x01) and (arg_b in (0x02, 0x03, 0x04, 0x40, 0x41) or (cmd.y_raw or 0) >= 0x80):
                # Trigger/buttons.  Ceiling/floor buttons are length-prefixed
                # control commands; the visual compact3 code 0x0E is *not* a
                # button.  Some floor buttons use arg_b=0, so y-position is a
                # safer discriminator than a small whitelist alone.
                if arg_b == 0x41 and pressed_button is not None:
                    sprite = pressed_button
                elif (cmd.y_raw or 0) >= 0x78 and floor_button is not None:
                    sprite = floor_button
                else:
                    sprite = ceiling_button
            elif command == 0x02 and arg_a == 0 and arg_b in (0, 1):
                # Actor/control record. Confirmed ant-like enemy in L6/R5;
                # other actor families still need the EXE lookup table.
                sprite = ant
                mode = "actor"

            if sprite is not None:
                x, y = control_xy(cmd, mode=mode)
                self._blit(image, sprite, x, y)
                if labels:
                    self._label(draw, x, y, cmd.label)

    def _draw_puzzle_markers(self, image: Image.Image, room: Room, *, labels: bool) -> None:
        """Draw symbol buttons from section_a.

        The base marker is AE000:009.  Its symbol is a separate one-sprite bank
        AE000:010..016 selected by the compact3 code. This replaces the older
        renderer that drew only the blank medallion and missed the puzzle state
        encoded in the payload.
        """
        directory = parse_exe_payload_directory(room)
        if not directory or not directory.sections or not directory.sections.section_a:
            return
        base = self.graphics.sprite("AE000", 9, 0)
        if base is None:
            return
        draw = ImageDraw.Draw(image)
        for entry in directory.sections.section_a.entries:
            x = entry.x_raw * 2 - base.width // 2
            y = entry.y - base.height // 2
            self._blit(image, base, x, y)
            symbol = self.graphics.sprite("AE000", 10 + (entry.code & 0x07), 0)
            if symbol is not None:
                self._blit(image, symbol, x + (base.width - symbol.width) // 2, y)
            if labels:
                self._label(draw, x, y, f"puzzle {entry.label}")

    def _draw_record12_puzzle_panels(self, image: Image.Image, room: Room, *, labels: bool) -> None:
        """Draw the puzzle progress block from the 12-byte section when present.

        This is still a partial model, but it is much cleaner than hard-coding
        it as a visual compact3 object. The L9 Expert room 0 record places the
        AE000:017 progress block at the right side of the room.
        """
        directory = parse_exe_payload_directory(room)
        if not directory or not directory.sections or not directory.sections.section_b_records:
            return
        panel = self.graphics.sprite("AE000", 17, 0)
        if panel is None:
            return
        draw = ImageDraw.Draw(image)
        for i, rec in enumerate(directory.sections.section_b_records):
            if len(rec) < 4:
                continue
            # Observed layout family: byte1 behaves as half-x, byte3 as y.
            x = rec[1] * 2 - 4
            y = rec[3] + 8
            self._blit(image, panel, x, y)
            if labels:
                self._label(draw, x, y, f"rec12[{i}] {rec.hex(' ')}")

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

    def _draw_visual_objects(self, image: Image.Image, room: Room, *, labels: bool, layer: str = "all") -> None:
        table = visual_compact3_table(room)
        if not table:
            return
        draw = ImageDraw.Draw(image)
        for entry in table.entries:
            entry_layer = visual_render_layer(
                entry,
                level_index=getattr(self, "_current_level_index", None),
                room_index=room.index,
                page_index=room.page_index,
            )
            if layer != "all" and entry_layer != layer:
                continue
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
                self._label(draw, x, y, f"{entry_layer} @{table.offset:02X} {entry.label}")

    def _sprite_for_visual_entry(self, entry: ObjectTableEntry, room: Room) -> Image.Image | None:
        ref = visual_sprite_ref(
            entry,
            theme=getattr(self, "_current_theme", 0),
            level_index=getattr(self, "_current_level_index", None),
            room_index=room.index,
            page_index=room.page_index,
        )
        sprite = self.graphics.sprite(ref.archive, ref.resource_id, ref.sprite_index)
        if sprite is not None and getattr(ref, "flip_h", False):
            sprite = sprite.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        return sprite

    def _draw_actor_probes(self, image: Image.Image, room: Room, header: bytes) -> None:
        """Debug-only overlay for actor/item storage that is not solved yet.

        Static analysis of AEPROG shows at least two additional object paths
        after the terrain/decor renderer: a six-slot room-gated global array
        and a three-byte marker at the end of the room record.  They are exposed
        here as probes so screenshots can be compared without polluting the
        normal game renderer with guesses.
        """
        draw = ImageDraw.Draw(image)
        tail = room_tail_marker(room)
        if tail is not None:
            x = tail.x_raw * 2
            y = tail.y_raw
            colour = (0, 255, 255, 255) if tail.room_plus_one == room.index + 1 else (80, 120, 120, 180)
            draw.rectangle([x - 3, y - 3, x + 3, y + 3], outline=colour, width=1)
            self._label(draw, x + 4, y - 6, tail.label)

        for cand in header_object_candidates(header):
            if cand.room_plus_one != room.index + 1:
                continue
            x = cand.x_raw * 2
            y = cand.y_raw
            draw.ellipse([x - 4, y - 4, x + 4, y + 4], outline=(255, 128, 0, 255), width=1)
            self._label(draw, x + 5, y - 6, cand.label)

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
