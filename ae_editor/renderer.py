from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from PIL import Image, ImageDraw

from .constants import CELL_SIZE, DEFAULT_TERRAIN_CODE_TO_SPRITE, ROOM_COLUMNS, ROOM_ROWS
from .coordinates import ScreenBias, compact3_xy, platform_xy
from .graphics import GraphicsSet
from .level_format import Level, LevelPart, Room
from .room_payload import (
    PayloadPoint,
    parse_room_payload,
    parse_room_object_table,
    parse_room_object_tables,
    ObjectTableEntry,
    parse_platform_triplets,
    parse_visual_compact3_tables,
)


@dataclass
class RenderOptions:
    # terrain            = terrain only. Special gameplay/collision cells stay invisible.
    # terrain_payload    = terrain + debug markers from the room payload
    # terrain_objects    = terrain + first-pass known actor/control sprites from payload
    # collision_debug    = terrain + visible overlay for special collision cells such as 0x07
    # payload_probe      = coordinate/table visualization of the trailing payload only
    # object_table       = terrain + raw 3-byte object/decor table labels
    # exe_sections       = terrain + EXE-derived platform/object table labels
    # object_anchors     = terrain + all candidate compact3 anchor interpretations
    mode: str = "terrain"
    zoom: int = 2
    grid: bool = False
    crop_left_columns: int = 0
    crop_width_columns: int | None = None
    header_probe: bool = False
    part_index: int = 0
    # Experimental global offset.  Use this to test the suspected half-tile
    # (+4,+4) game viewport alignment without changing decoded data.
    origin_x: int = 0
    origin_y: int = 0
    # v25: terrain 8x8 cells are drawn with 18x17 overlapping sprites.
    # The sprite anchor is not top-left of the bitmap; the game blits normal
    # terrain about half a cell up/left relative to the logical tile position.
    # Keep it configurable for research, but default to the visually-correct
    # anchor discovered from the AE001:021 block sprites.
    terrain_anchor_x: int = -4
    terrain_anchor_y: int = -4


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

    # Rope-family logical tile codes.  They are encoded in the terrain grid,
    # but rendered from AE000 rope sprites, not from the AE001 terrain bank.
    ROPE_CODES = {0x80, 0x90, 0xA0, 0xB0, 0xC0}
    # Rope sprites are 16px-wide art on an 8px grid.  The game appears to blit
    # them one column left of the marker cell, which fixes the persistent
    # “rope is slightly too far left/right” mismatch in L1 room 1.
    ROPE_X_BIAS = -8

    # v20: 0x07 is best understood as invisible solid/collision support.
    # Moving-platform sprites live in the per-room payload instead of being
    # inferred from 0x07 runs in the terrain grid.
    SOLID_INVISIBLE_CODE = 0x07

    def render_room(self, level: Level, room_index: int, options: RenderOptions | None = None) -> Image.Image:
        options = options or RenderOptions()
        part = level.part(options.part_index)
        room = part.room(room_index)
        width = ROOM_COLUMNS * CELL_SIZE
        height = ROOM_ROWS * CELL_SIZE
        image = Image.new("RGBA", (width, height), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        self._current_bias = ScreenBias(options.origin_x, options.origin_y)
        self._current_terrain_anchor = (options.terrain_anchor_x, options.terrain_anchor_y)

        if options.mode in {"codes_hex", "codes_dec"}:
            self._render_codes(image, draw, room.tiles, options.mode)
        elif options.mode == "trailing_hex":
            self._render_trailing_probe(image, draw, room)
        elif options.mode == "payload_probe":
            self._render_payload_probe(image, draw, room)
        elif options.mode == "exe_sections":
            self._render_terrain(image, room.tiles, part.theme)
            self._draw_exe_sections_overlay(image, room)
        else:
            self._render_terrain(image, room.tiles, part.theme)
            if options.mode == "terrain_payload":
                self._draw_payload_overlay(image, room)
            elif options.mode == "terrain_objects":
                self._draw_known_payload_objects(image, room)
                self._draw_visual_compact3_sprites(image, room, labels=False)
            elif options.mode == "collision_debug":
                self._draw_collision_debug(image, room)
            elif options.mode == "object_table":
                self._draw_known_payload_objects(image, room)
                self._draw_visual_compact3_sprites(image, room, labels=True)
            elif options.mode == "object_anchors":
                self._draw_object_anchor_probe(image, room)

        if options.header_probe:
            self._draw_header_probe(image, part)
        if options.grid:
            self._draw_grid(image)

        image = self._crop(image, options.crop_left_columns, options.crop_width_columns)
        if options.zoom != 1:
            image = image.resize((image.width * options.zoom, image.height * options.zoom), Image.Resampling.NEAREST)
        return image


    def _xy(self, x: int, y: int) -> tuple[int, int]:
        bias = getattr(self, "_current_bias", ScreenBias())
        return x + bias.x, y + bias.y

    def _blit(self, image: Image.Image, sprite: Image.Image, x: int, y: int) -> None:
        image.alpha_composite(sprite, self._xy(x, y))

    def _blit_terrain_sprite(self, image: Image.Image, sprite: Image.Image, x: int, y: int) -> None:
        ax, ay = getattr(self, "_current_terrain_anchor", (-4, -4))
        self._blit(image, sprite, x + ax, y + ay)

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
                    self._blit(image, background, xx, yy)

        rope_cells = self._rope_cells(tiles)

        # Main terrain pass. Known special/gameplay cells are deliberately not
        # passed through the terrain bank. Ropes are rendered from AE000 rope
        # sprites. 0x07 stays invisible by default: it is a solid support/
        # collision marker, not the actual moving-platform art.
        for y in range(ROOM_ROWS):
            for x in range(ROOM_COLUMNS):
                code = tiles[y * ROOM_COLUMNS + x]
                if code == self.SOLID_INVISIBLE_CODE or (x, y) in rope_cells:
                    continue
                sprite_index = self.code_to_sprite.get(code)
                if sprite_index is None:
                    continue
                sprite = self.graphics.terrain_sprite(theme, sprite_index)
                if sprite is not None:
                    self._blit_terrain_sprite(image, sprite, x * CELL_SIZE, y * CELL_SIZE)

        self._render_rope_codes(image, tiles)

    def _rope_cells(self, tiles: list[int]) -> set[tuple[int, int]]:
        return {(x, y) for y in range(ROOM_ROWS) for x in range(ROOM_COLUMNS) if tiles[y * ROOM_COLUMNS + x] in self.ROPE_CODES}

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
                px = x * CELL_SIZE + self.ROPE_X_BIAS
                py = y * CELL_SIZE
                if code == 0x90 and top is not None:
                    self._blit(image, top, px, py)
                elif code == 0xA0 and middle24 is not None:
                    self._blit(image, middle24, px, py)
                elif code == 0xB0 and middle8 is not None:
                    self._blit(image, middle8, px, py)
                elif code == 0xC0 and bottom is not None:
                    self._blit(image, bottom, px, py)
                # 0x80 is treated as continuation covered by the 24px segment.

    def _object_sprite_for_code(self, code: int, room: Room | None = None):
        """Best-effort mapping for compact3 visual room records.

        v21 distinction:
        - terrain code 0x07 is collision only, never a visible platform.
        - visible platforms/buttons/vases/laser triggers come from room payload
          records.
        - compact3 code is a logical object/decor id, not a raw bank number.

        The returned tuple is:
            archive, resource_id, sprite_index, anchor_mode, y_adjust
        anchor_mode 'bottom_half' means x_raw is a half-pixel center/baseline
        anchor.  That matches vase/statue/plaque records better than the older
        top-left placement.
        """
        mapping = {
            # L1 room 2 wall plaques/reliefs in AE001 decor bank.
            0x88: ("AE001", 25, 8, "bottom_half", 0),
            0x49: ("AE001", 25, 9, "bottom_half", 0),
            0x48: ("AE001", 25, 8, "bottom_half", 0),
            0x09: ("AE001", 25, 9, "bottom_half", 0),
            # Large blue seated statue in L1 room 2.
            0x05: ("AE001", 25, 36, "bottom_half", 0),
            # Vase in L2 room 0 page B. User-confirmed sprite.
            0x1A: ("AE001", 25, 26, "bottom_half", 0),
            # Ceiling/floor button family. User confirmed ceiling button sprite.
            0x0E: ("AE000", 39, 0, "bottom_half", 0),
            # Laser trigger / red pudding-looking trigger. User-confirmed sprite.
            0x80: ("AE000", 41, 0, "bottom_half", 0),
            # Diamond/artifact pickup. Confirmed sprite location by manual asset browsing.
            0x8E: ("AE000", 44, 0, "bottom_half", 0),
            # Enemy family. Code 02 is reused; for now use theme/room hints.
            # L2 room 0 page B screenshot shows spider AE000:022:12, while
            # L1 room 2 uses green crawler/snake frames around AE000:022:20.
            0x02: ("AE000", 22, 12 if (room is not None and room.page_index == 1 and room.index == 0) else 20, "bottom_half", 0),
            # Common blue triangular/arrow object family.
            0x7D: ("AE000", 19, 2, "bottom_half", 0),
        }
        return mapping.get(code)

    def _object_x(self, entry: ObjectTableEntry, mode: str) -> int:
        if mode == "half":
            return entry.x_half_px
        if mode == "tile":
            return entry.x_tile_px
        # auto: small x values in crawler/control records often behave like
        # tile coordinates, while larger values behave more like half-pixels.
        if entry.x_raw < ROOM_COLUMNS:
            return entry.x_tile_px
        return entry.x_half_px

    def _object_position(self, entry: ObjectTableEntry, sprite: Image.Image, mode: str) -> tuple[int, int]:
        if mode == "bottom_half":
            # Compact3 visual records behave like: x_raw = half-pixel center,
            # y = bottom/baseline.  This lines up the L2 vase and L1 statue far
            # better than treating the record as a top-left coordinate.
            return entry.x_half_px - sprite.width // 2, entry.y - sprite.height
        if mode == "half":
            return entry.x_half_px, entry.y
        if mode == "tile":
            return entry.x_tile_px, entry.y
        if entry.x_raw < ROOM_COLUMNS:
            return entry.x_tile_px, entry.y
        return entry.x_half_px, entry.y

    def _draw_object_table_sprites(self, image: Image.Image, room: Room, labels: bool = False) -> None:
        draw = ImageDraw.Draw(image)
        seen: set[tuple[int, int, int, int]] = set()
        tables = parse_room_object_tables(room)
        # Keep backward compatibility for rooms where only the older selector finds anything.
        if not tables:
            tables = [(-1, parse_room_object_table(room))]
        for table_offset, entries in tables:
            for entry in entries:
                key = (entry.x_raw, entry.y, entry.code, entry.source_offset)
                if key in seen:
                    continue
                seen.add(key)
                spec = self._object_sprite_for_code(entry.code, room)
                if spec:
                    archive, resource_id, sprite_index, anchor_mode, y_adjust = spec
                    sprite = self.graphics.sprite(archive, resource_id, sprite_index)
                    if sprite is not None:
                        x, y = self._object_position(entry, sprite, anchor_mode)
                        y += y_adjust
                        self._blit(image, sprite, x, y)
                        if labels:
                            draw.rectangle([x, y, x + max(40, sprite.width), y + 10], fill=(0, 0, 0, 180))
                            draw.text((x + 1, y), f"@{table_offset:02X} {entry.label}", fill=(255, 255, 0, 255))
                        continue
                # Unknown object/decor/control entry: keep it visible in research mode.
                if labels:
                    x = entry.x_half_px
                    y = entry.y
                    draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 0, 255, 255))
                    draw.text((x + 4, y - 6), f"@{table_offset:02X} {entry.label}", fill=(255, 255, 0, 255))



    def _object_sprite_for_entry(self, entry: ObjectTableEntry, room: Room | None = None):
        """Return sprite mapping plus an EXE-derived anchor mode.

        Static EXE disassembly shows compact3 coordinates are generally
        x_px = x_raw * 2 and y_px = y.  High-bit codes are rendered directly
        through an EXE sprite pointer table, so they should be top-left anchored.
        Some low-code decorations known from screenshots (vase/statue) are
        better treated as bottom/center anchored because their compact3 point is
        a baseline/center marker.
        """
        code = entry.code
        # User-confirmed and screenshot-confirmed mappings.
        if code == 0x1A:
            return ("AE001", 25, 26, "bottom_half", 0)  # vase
        if code == 0x0E:
            return ("AE000", 39, 0, "top_exe", 0)       # ceiling/floor button family
        if code == 0x80:
            return ("AE000", 41, 0, "top_exe", 0)       # laser trigger / pudding
        if code == 0x8E:
            return ("AE000", 44, 0, "top_exe", 0)       # diamond/artifact
        if code == 0x05:
            return ("AE001", 25, 36, "bottom_half", 0)  # large statue
        if code in (0x88, 0x48, 0x49, 0x09):
            # Wall reliefs/plaques.  They behave as decorative sprites; exact
            # index mapping remains incomplete, but these are much closer than
            # drawing terrain tiles.
            idx = {0x88: 8, 0x48: 8, 0x49: 9, 0x09: 9}[code]
            return ("AE001", 25, idx, "top_exe", 0)
        if code == 0x02:
            # Actor/enemy-like entries.  The sprite family is known, but the
            # actor coordinate schema is still not fully solved.  Avoid the old
            # room-specific spider hack here; expose an actor anchor mode instead.
            sprite_index = 12 if (room is not None and room.page_index == 1 and room.index == 0) else 20
            return ("AE000", 22, sprite_index, "actor_bottom_2x", 0)
        if code == 0x7D:
            return ("AE000", 19, 2, "top_exe", 0)
        return None

    def _entry_position(self, entry: ObjectTableEntry, sprite: Image.Image, mode: str) -> tuple[int, int]:
        # Compatibility names from old builds.
        aliases = {
            "bottom_half": "bottom_center",
            "half": "top_exe",
            "tile": "tile_top",
            "actor2x": "actor_top_2x",
        }
        return compact3_xy(entry, sprite, aliases.get(mode, mode))

    def _draw_visual_compact3_sprites(self, image: Image.Image, room: Room, labels: bool = False) -> None:
        """Draw EXE-style compact3 visual/decor/object tables.

        This supersedes the older generic payload scanner for display purposes.
        It uses canonical count-prefixed compact3 tables and the EXE coordinate
        rule x_px = x_raw * 2 for top-left anchored high-bit objects.
        """
        draw = ImageDraw.Draw(image)
        seen: set[tuple[int, int, int, int]] = set()
        for table in parse_visual_compact3_tables(room):
            for entry in table.entries:
                key = (table.offset, entry.source_offset, entry.x_raw, entry.y, entry.code)
                if key in seen:
                    continue
                seen.add(key)
                spec = self._object_sprite_for_entry(entry, room)
                if spec:
                    archive, resource_id, sprite_index, anchor_mode, y_adjust = spec
                    sprite = self.graphics.sprite(archive, resource_id, sprite_index)
                    if sprite is not None:
                        x, y = self._entry_position(entry, sprite, anchor_mode)
                        y += y_adjust
                        self._blit(image, sprite, x, y)
                        if labels:
                            draw.rectangle([x, y, x + max(46, sprite.width), y + 10], fill=(0, 0, 0, 180))
                            draw.text((x + 1, y), f"@{table.offset:02X} {entry.label}", fill=(255, 255, 0, 255))
                        continue
                if labels:
                    x, y = entry.x_raw * 2, entry.y
                    draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 0, 255, 255))
                    draw.text((x + 4, y - 6), f"@{table.offset:02X} {entry.label}", fill=(255, 255, 0, 255))

    def _draw_exe_sections_overlay(self, image: Image.Image, room: Room) -> None:
        """Debug overlay for the EXE-derived payload structures."""
        draw = ImageDraw.Draw(image)
        for p in parse_platform_triplets(room):
            x, y = platform_xy(p)
            draw.rectangle([x, y, x + 10, y + 10], outline=(255, 180, 0, 255), width=1)
            draw.text((x + 2, y - 8), p.label, fill=(255, 180, 0, 255))
        for table in parse_visual_compact3_tables(room):
            for entry in table.entries:
                x, y = entry.x_raw * 2, entry.y
                colour = (0, 255, 180, 255) if entry.code >= 0x80 else (0, 160, 255, 255)
                draw.line([x - 4, y, x + 4, y], fill=colour)
                draw.line([x, y - 4, x, y + 4], fill=colour)
                draw.text((x + 4, y - 6), f"@{table.offset:02X} {entry.code:02X}", fill=colour)


    def _draw_object_anchor_probe(self, image: Image.Image, room: Room) -> None:
        """Visualize competing compact3 coordinate interpretations.

        Useful for exactly the current problem: decorations are broadly right,
        but actors/buttons/platforms are sometimes several pixels off.  This
        mode draws the same raw entry using several coordinate models instead
        of silently choosing one.
        """
        draw = ImageDraw.Draw(image)
        colours = {
            "top_exe": (0, 255, 255, 255),
            "bottom_center": (255, 255, 0, 255),
            "actor_top_2x": (255, 0, 255, 255),
            "actor_bottom_2x": (255, 120, 0, 255),
        }
        for table in parse_visual_compact3_tables(room):
            for entry in table.entries:
                spec = self._object_sprite_for_entry(entry, room)
                if not spec:
                    continue
                archive, resource_id, sprite_index, _anchor_mode, _y_adjust = spec
                sprite = self.graphics.sprite(archive, resource_id, sprite_index)
                if sprite is None:
                    continue
                for mode, colour in colours.items():
                    x, y = compact3_xy(entry, sprite, mode)
                    x, y = self._xy(x, y)
                    draw.rectangle([x, y, x + sprite.width - 1, y + sprite.height - 1], outline=colour, width=1)
                    draw.text((x + 1, y + 1), f"{entry.code:02X}/{mode[:2]}", fill=colour)

    def _draw_collision_debug(self, image: Image.Image, room: Room) -> None:
        """Show invisible solid cells without pretending they are visible sprites."""
        draw = ImageDraw.Draw(image)
        for y in range(ROOM_ROWS):
            for x in range(ROOM_COLUMNS):
                if room.tiles[y * ROOM_COLUMNS + x] == self.SOLID_INVISIBLE_CODE:
                    x0 = x * CELL_SIZE
                    y0 = y * CELL_SIZE
                    draw.rectangle([x0, y0, x0 + CELL_SIZE - 1, y0 + CELL_SIZE - 1], outline=(255, 0, 255, 180))
                    draw.line([x0, y0, x0 + CELL_SIZE - 1, y0 + CELL_SIZE - 1], fill=(255, 0, 255, 120))

    def _draw_leading_payload_platforms(self, image: Image.Image, room: Room) -> None:
        """Render moving platform sprites from the first payload triplets.

        Observed examples:
        - L20 room 0 page B starts with A0 10 58 / A0 18 58, matching the two
          vertical blue platforms in the screenshot.
        - L1 room 1 has 80/60 leading triplets that match moving platform
          state/position changes between Page A and Page B.

        This is still a research renderer: the triplet flag encodes more than
        just orientation, but rendering from the payload is more correct than
        inferring platforms from terrain code 0x07.
        """
        horiz = self.graphics.sprite("AE000", 47, 0)
        vert = self.graphics.sprite("AE000", 48, 0)
        for p in parse_platform_triplets(room):
            flag = p.flags & 0xF0
            # EXE-derived coordinate rule from routine 0x25b3:
            # byte1 is doubled and then biased left by 4.  byte2 is a pixel Y.
            px, py = platform_xy(p)
            if flag == 0xA0 and vert is not None:
                self._blit(image, vert, px, py)
            elif flag in {0x40, 0x60, 0x80} and horiz is not None:
                self._blit(image, horiz, px, py)

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
        self._draw_leading_payload_platforms(image, room)
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
