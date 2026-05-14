from __future__ import annotations

from dataclasses import dataclass, field
from PIL import Image, ImageDraw

from ..constants import (
    CELL_SIZE,
    DEFAULT_TERRAIN_CODE_TO_SPRITE,
    ROOM_COLUMNS,
    ROOM_ROWS,
    ROOM_SCREEN_HEIGHT_PX,
    ROOM_SCREEN_WIDTH_PX,
)
from .coordinates import (
    TERRAIN_ANCHOR,
    BACKGROUND_COMPACT3_DELTA,
    FOREGROUND_COMPACT3_DELTA,
    LASER_CRYSTAL_DELTA,
    actor_xy,
    compact3_xy,
    header_exit_door_xy,
    control_xy,
    header_object_xy,
    platform_xy,
)
from ..game_data.conveyors import ConveyorSpec, compose_conveyor, iter_conveyor_runs
from ..game_data.graphics import GraphicsSet
from ..game_data.level_format import Level, Room
from .object_mapping import visual_render_layer, visual_sprite_ref
from .tile_mapping import CONVEYOR_PHYSICS_TILE_CODES


def _green_block_xy(raw_x: int, raw_y: int) -> tuple[int, int]:
    """Convert event09/puzzle-block raw coordinates to screen pixels.

    AEPROG's event09 handler uses byte0/byte1 as the current/default
    6-tile block position and byte2/byte3 as the alternate position.
    Collision is written through the runtime tile map as x/4 - 1,
    y/8 - 1, 6 cells wide by 2 cells high.  That corresponds to
    pixel x = raw_x * 2 - 8 and y = raw_y - 12 for the visible block.
    """
    return raw_x * 2 - 8, raw_y - 12


def _record12_default_xy(rec: bytes) -> tuple[int, int] | None:
    if len(rec) < 2:
        return None
    return _green_block_xy(rec[0], rec[1])


def _record12_alternate_xy(rec: bytes) -> tuple[int, int] | None:
    if len(rec) < 4:
        return None
    return _green_block_xy(rec[2], rec[3])


def _record12_panel_xy(rec: bytes) -> tuple[int, int] | None:
    # Backward-compatible name used by older code: this is the default/current
    # green-block position, not a separate panel location.
    return _record12_default_xy(rec)


def _record12_sequence_values(rec: bytes) -> list[int]:
    """Return the 1-based symbol sequence stored in a record12 green block.

    Current model: bytes 5..9 are the configured symbol ids; 0 terminates
    the sequence early.  Bytes after that are preserved but not treated as
    gameplay sequence data by the editor.
    """
    values: list[int] = []
    for value in rec[5:10]:
        if value == 0:
            break
        values.append(value)
    return values


def _invisible_clusters(room: Room) -> list[tuple[int, int, int, int]]:
    cells = {(x, y) for y in range(ROOM_ROWS) for x in range(ROOM_COLUMNS) if room.get(x, y) == 0x07}
    clusters: list[tuple[int, int, int, int]] = []
    while cells:
        seed = next(iter(cells))
        stack = [seed]
        cluster = set()
        cells.remove(seed)
        while stack:
            cx, cy = stack.pop()
            cluster.add((cx, cy))
            for nx, ny in ((cx-1, cy), (cx+1, cy), (cx, cy-1), (cx, cy+1)):
                if (nx, ny) in cells:
                    cells.remove((nx, ny))
                    stack.append((nx, ny))
        xs = [x for x, _ in cluster]
        ys = [y for _, y in cluster]
        clusters.append((min(xs) * CELL_SIZE, min(ys) * CELL_SIZE, (max(xs) - min(xs) + 1) * CELL_SIZE, (max(ys) - min(ys) + 1) * CELL_SIZE))
    clusters.sort(key=lambda r: (r[1], r[0]))
    return clusters


def _draw_sequence_on_panel(graphics, panel: Image.Image, seq_values: list[int]) -> Image.Image:
    if not seq_values:
        return panel
    out = panel.copy()
    symbols = []
    for value in seq_values[:5]:
        sprite = graphics.sprite("AE000", 9 + value, 0)
        if sprite is not None:
            symbols.append(sprite)
    if not symbols:
        return out
    total_w = sum(s.width for s in symbols) + max(0, len(symbols) - 1) * 1
    if total_w > out.width:
        scale = max(1, min(s.width for s in symbols) - 1) / max(1, max(s.width for s in symbols))
        scaled = []
        for sprite in symbols:
            w = max(1, int(sprite.width * scale))
            h = max(1, int(sprite.height * scale))
            scaled.append(sprite.resize((w, h), Image.Resampling.NEAREST))
        symbols = scaled
        total_w = sum(s.width for s in symbols) + max(0, len(symbols) - 1) * 1
    x = max(0, (out.width - total_w) // 2)
    for sprite in symbols:
        y = max(0, (out.height - sprite.height) // 2)
        out.alpha_composite(sprite, (x, y))
        x += sprite.width + 1
    return out

from ..game_data.room_payload import (
    ObjectTableEntry,
    ActorTableRecord,
    actor_records_for_room,
    control_commands,
    parse_exe_payload_directory,
    parse_platform_triplets,
    parse_conveyor_visual_records,
    visual_compact3_table,
    animated_decor_table,
    laser_crystal_table,
    part_apple_marker,
    apple_marker_screen_xy,
    header_object_candidates,
    header_exit_door,
    header_player_start,
)

@dataclass
class RenderOptions:
    """Rendering options exposed by the cleaned-up viewer."""

    mode: str = "game"  # game, payload_debug, codes_hex, trailing_hex
    zoom: int = 3
    grid: bool = False
    part_index: int = 0  # 0 = Explorer, 1 = Expert
    draw_platforms: bool = True
    draw_puzzle_panels: bool = True
    draw_actors: bool = True
    draw_player_start: bool = True
    control_state_overrides: dict[int, bool] | None = None
    display_mode: str = "vga"  # vga, ega, cga


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

    ROPE_SPRITE_RESOURCES = {
        0x90: 5,  # top
        0xA0: 6,  # long middle
        0xB0: 7,  # short middle
        0xC0: 8,  # bottom
    }
    CONVEYOR_TILE_CODES = {0x0F: "grey", 0x1F: "teal"}
    ACTOR_FRAME_RUNS = [
        (0x00, 0x17, 0x14),
        (0x17, 0x14, 0x15),
        (0x2B, 0x29, 0x16),
    ]
    # Rope markers sit on the left edge of the 8×8 grid cell, but the visible
    # rope art is slightly right of that logical column in the captured game.
    ROPE_X_BIAS = 4
    SOLID_INVISIBLE_CODE = 0x07

    def render_room(self, level: Level, room_index: int, options: RenderOptions | None = None) -> Image.Image:
        options = options or RenderOptions()
        previous_display_mode = self.graphics.display_mode
        self.graphics.set_display_mode(options.display_mode)
        try:
            return self._render_room_with_current_graphics(level, room_index, options)
        finally:
            self.graphics.set_display_mode(previous_display_mode)

    def _render_room_with_current_graphics(self, level: Level, room_index: int, options: RenderOptions) -> Image.Image:
        part = level.part(options.part_index)
        room = part.room(room_index)
        image = Image.new("RGBA", (ROOM_SCREEN_WIDTH_PX, ROOM_SCREEN_HEIGHT_PX), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image, "RGBA")
        self._current_theme = part.theme
        self._current_level_index = level.index

        if options.mode == "codes_hex":
            self._render_codes(image, draw, room)
        elif options.mode == "trailing_hex":
            self._render_trailing_probe(image, draw, room)
        else:
            # EXE render order recovered from AEPROG around 0x2CE2:
            # compact3 visuals with code >= 0x80 are drawn before terrain,
            # terrain and rope markers are walked together in row-major order,
            # then compact3 visuals with code < 0x80 are drawn as foreground.
            self._draw_background(image, part.theme)
            if options.mode == "game":
                self._draw_animated_decor(image, room, part.theme)
                self._draw_visual_objects(image, room, layer="background")
            self._draw_terrain_tiles(image, room, part.theme)

            if options.mode == "game":
                self._draw_conveyor_tiles(image, room)
                if options.draw_platforms:
                    self._draw_platforms(image, room)
                self._draw_control_records(image, room, control_state_overrides=options.control_state_overrides)
                self._draw_puzzle_markers(image, room)
                self._draw_laser_crystals(image, room)
                self._draw_visual_objects(image, room, layer="foreground")
                if options.draw_puzzle_panels:
                    self._draw_record12_puzzle_panels(image, room)
                self._draw_header_objects(image, room, part.header)
                self._draw_exit_door(image, room, part.header, part.theme)
                self._draw_apple_pickup(image, part, room)
                if options.draw_actors:
                    self._draw_actors(image, part, room, include_hidden=False)
                if options.draw_player_start:
                    self._draw_player_start(image, room, part.header)
            elif options.mode == "payload_debug":
                self._draw_animated_decor(image, room, part.theme)
                self._draw_visual_objects(image, room, layer="background")
                self._draw_conveyor_tiles(image, room)
                self._draw_platforms(image, room)
                self._draw_control_records(image, room)
                self._draw_puzzle_markers(image, room)
                self._draw_laser_crystals(image, room)
                self._draw_visual_objects(image, room, layer="foreground")
                self._draw_record12_puzzle_panels(image, room)
                self._draw_header_objects(image, room, part.header)
                self._draw_exit_door(image, room, part.header, part.theme)
                self._draw_apple_pickup(image, part, room)
                self._draw_actors(image, part, room, include_hidden=True)
                self._draw_player_start(image, room, part.header)
                self._draw_actor_probes(image, part, room, part.header)
                self._draw_payload_debug(image, room)

        if options.zoom != 1:
            image = image.resize((image.width * options.zoom, image.height * options.zoom), Image.Resampling.NEAREST)
        if options.grid:
            self._draw_grid(image, zoom=options.zoom)
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
        for y in range(ROOM_ROWS):
            for x in range(ROOM_COLUMNS):
                code = room.get(x, y)
                if code == self.SOLID_INVISIBLE_CODE or code in CONVEYOR_PHYSICS_TILE_CODES:
                    continue
                rope = self._rope_sprite_for_code(code)
                if rope is not None:
                    self._blit(image, rope, x * CELL_SIZE + self.ROPE_X_BIAS, y * CELL_SIZE)
                    continue
                sprite_index = self.code_to_sprite.get(code)
                if sprite_index is None:
                    continue
                sprite = self.graphics.terrain_sprite(theme, sprite_index)
                if sprite is not None:
                    self._blit(image, sprite, x * CELL_SIZE + TERRAIN_ANCHOR.x, y * CELL_SIZE + TERRAIN_ANCHOR.y)

    def _rope_sprite_for_code(self, code: int) -> Image.Image | None:
        resource_id = self.ROPE_SPRITE_RESOURCES.get(code)
        if resource_id is None:
            return None
        return self.graphics.sprite("AE000", resource_id, 0)


    def _draw_conveyor_tiles(self, image: Image.Image, room: Room) -> None:
        """Render visible conveyor belts from CV payload objects.

        Terrain codes 0x0F/0x1F are only the scrolling/physics footprint.  A
        tile-only belt is intentionally invisible in the original game.  The
        visible belt is a CV record in the room payload directory header.
        """
        parts = [self.graphics.sprite("AE000", 38, i) for i in range(24)]
        runs = iter_conveyor_runs(room)
        for cv in parse_conveyor_visual_records(room):
            # Prefer the tile footprint to choose grey/teal when it is present;
            # otherwise keep the existing default so orphan CVs remain visible.
            kind = "teal"
            for run in runs:
                if run.cells & cv.cells:
                    kind = run.kind
                    break
            width = max(8, (cv.length + 1) * CELL_SIZE)
            strip = compose_conveyor(parts, ConveyorSpec(kind=kind, x=0, y=0, width=width, frame=0))
            if strip is not None:
                self._blit(image, strip, cv.x_raw * 2 - 8, cv.y - 18)

    def _draw_platforms(self, image: Image.Image, room: Room) -> None:
        horizontal = self.graphics.sprite("AE000", 47, 0)
        vertical = self.graphics.sprite("AE000", 48, 0)
        for triplet in parse_platform_triplets(room):
            if not triplet.visible:
                continue
            x, y = platform_xy(triplet)
            if triplet.orientation == "vertical" and vertical is not None:
                self._blit(image, vertical, x, y)
            elif triplet.orientation == "horizontal" and horizontal is not None:
                self._blit(image, horizontal, x, y)

    def _draw_control_records(
        self,
        image: Image.Image,
        room: Room,
        *,
        control_state_overrides: dict[int, bool] | None = None,
    ) -> None:
        ceiling_button = self.graphics.sprite("AE000", 39, 0)
        ceiling_pressed = self.graphics.sprite("AE000", 42, 0)
        floor_button = self.graphics.sprite("AE000", 40, 0)
        floor_pressed = self.graphics.sprite("AE000", 43, 0)
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
            sprite = None
            mode = "button"
            override = None if control_state_overrides is None else control_state_overrides.get(cmd.record.index)
            pressed = bool(override) if override is not None else bool(arg_b & 0x40)
            if command == 0x00:
                # Command byte, not position, selects the switch family:
                #   0 => ceiling button
                #   1 => floor switch
                # The remaining bytes are trigger/link/state metadata.  Bit 0x40
                # in arg_b is the first confirmed initial-state bit: use the
                # pressed artwork but do not reinterpret it as a different type.
                sprite = ceiling_pressed if pressed and ceiling_pressed is not None else ceiling_button
                mode = "ceiling_button"
            elif command == 0x01:
                sprite = floor_pressed if pressed and floor_pressed is not None else floor_button
                mode = "floor_switch"
            elif command == 0x02:
                # Command 2 goes through the visible trigger renderer in
                # AEPROG.  Its metadata links it to platforms/lasers; enemies
                # are initialized later into the separate runtime actor table.
                sprite = self.graphics.sprite("AE000", 41, 0)
                mode = "laser_trigger"

            if sprite is not None:
                x, y = control_xy(cmd, mode=mode)
                self._blit(image, sprite, x, y)


    def _draw_puzzle_markers(self, image: Image.Image, room: Room) -> None:
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
        for entry in directory.sections.section_a.entries:
            x = entry.x_raw * 2 - base.width // 2
            y = entry.y - base.height // 2
            self._blit(image, base, x, y)
            symbol = self.graphics.sprite("AE000", 10 + (entry.code & 0x07), 0)
            if symbol is not None:
                self._blit(image, symbol, x + (base.width - symbol.width) // 2, y)

    def _draw_record12_puzzle_panels(self, image: Image.Image, room: Room) -> None:
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
        for i, rec in enumerate(directory.sections.section_b_records):
            default_xy = _record12_default_xy(rec)
            alternate_xy = _record12_alternate_xy(rec)
            if default_xy is None:
                continue
            x, y = default_xy
            seq_values = _record12_sequence_values(rec)
            panel_img = _draw_sequence_on_panel(self.graphics, panel, seq_values)

            # The current/default position is byte0/byte1.  The alternate
            # position is byte2/byte3 and is shown as a ghost, because event09
            # swaps the two positions only when the configured symbol sequence
            # has been emitted/pressed.
            self._blit(image, panel_img, x, y)
            if alternate_xy is not None:
                ax, ay = alternate_xy
                ghost = panel_img.copy()
                alpha = ghost.getchannel("A").point(lambda a: min(a, 96))
                ghost.putalpha(alpha)
                self._blit(image, ghost, ax, ay)

    def _draw_laser_crystals(self, image: Image.Image, room: Room) -> None:
        table = laser_crystal_table(room)
        if not table:
            return
        for entry in table.entries:
            # AEPROG masks compact3 visual codes with 0x3F before indexing the
            # object sprite pointer table.  Laser reflector tables use the same
            # high-bit flags; treating the raw byte as the sprite index hid
            # entries like 0x8A/0x8B/0x8D/0xCA and left only low-valued crystals.
            sprite_index = entry.code & 0x3F
            sprite = self.graphics.sprite("AE000", 19, sprite_index)
            if sprite is None:
                continue
            x, y = compact3_xy(entry, sprite, "screen_exe", delta=LASER_CRYSTAL_DELTA)
            self._blit(image, sprite, x, y)

    def _draw_animated_decor(self, image: Image.Image, room: Room, theme: int) -> None:
        table = animated_decor_table(room)
        if table is None:
            return
        resource_id = 25 + theme
        for record in table.records:
            sprite_index = record.preview_sprite_index
            sprite = self.graphics.sprite("AE001", resource_id, sprite_index)
            if sprite is None:
                continue
            # Animated decals use the same compact3 coordinate family as theme
            # visuals: x is half-screen space, y is the EXE object anchor.
            entry = ObjectTableEntry(record.source_offset, record.index, record.x_raw, record.y, sprite_index, record.raw)
            x, y = compact3_xy(entry, sprite, "screen_exe", delta=BACKGROUND_COMPACT3_DELTA)
            self._blit(image, sprite, x, y)

    def _draw_visual_objects(self, image: Image.Image, room: Room, *, layer: str = "all") -> None:
        table = visual_compact3_table(room)
        if not table:
            return
        for entry in table.entries:
            entry_layer = visual_render_layer(
                entry,
                level_index=getattr(self, "_current_level_index", None),
                room_index=room.index,
                part_index=room.part_index,
            )
            if layer != "all" and entry_layer != layer:
                continue
            sprite = self._sprite_for_visual_entry(entry, room)
            if sprite is None:
                continue
            delta = BACKGROUND_COMPACT3_DELTA if entry_layer == "background" else FOREGROUND_COMPACT3_DELTA
            ref = visual_sprite_ref(
                entry,
                theme=getattr(self, "_current_theme", 0),
                level_index=getattr(self, "_current_level_index", None),
                room_index=room.index,
                part_index=room.part_index,
            )
            # Large statue/sarcophagus artwork sits a little lower than the
            # generic foreground decor anchor.
            if ref.archive == "AE001" and ref.resource_id == 26 and ref.sprite_index in {24, 25}:
                delta = (delta[0], delta[1] + 2)
            x, y = compact3_xy(entry, sprite, "screen_exe", delta=delta)
            self._blit(image, sprite, x, y)

    def _sprite_for_visual_entry(self, entry: ObjectTableEntry, room: Room) -> Image.Image | None:
        ref = visual_sprite_ref(
            entry,
            theme=getattr(self, "_current_theme", 0),
            level_index=getattr(self, "_current_level_index", None),
            room_index=room.index,
            part_index=room.part_index,
        )
        sprite = self.graphics.sprite(ref.archive, ref.resource_id, ref.sprite_index)
        if sprite is not None and getattr(ref, "flip_h", False):
            sprite = sprite.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        return sprite

    def _draw_actor_probes(self, image: Image.Image, part, room: Room, header: bytes) -> None:
        """Debug-only overlay for raw actor/item storage.

        The six-slot diamond/artifact array is now rendered normally.  The
        The runtime apple marker is physically split across the current room
        tail and the next record preamble, so draw the decoded runtime anchor.
        """
        draw = ImageDraw.Draw(image)
        apple = part_apple_marker(part, room.index)
        if apple is not None:
            x = apple.x_raw * 2
            y = apple.y_raw
            colour = (0, 255, 255, 255)
            draw.rectangle([x - 3, y - 3, x + 3, y + 3], outline=colour, width=1)

    def _draw_header_objects(self, image: Image.Image, room: Room, header: bytes) -> None:
        diamond = self.graphics.sprite("AE000", 44, 0)
        if diamond is None:
            return
        for cand in header_object_candidates(header):
            if cand.room_plus_one != room.index + 1:
                continue
            x, y = header_object_xy(cand.x_raw, cand.y_raw)
            self._blit(image, diamond, x, y)

    def _draw_exit_door(self, image: Image.Image, room: Room, header: bytes, theme: int) -> None:
        door = header_exit_door(header)
        if door is None or door.room_index != room.index:
            return
        sprite = self.graphics.sprite("AE001", 21 + theme, 0)
        if sprite is None:
            return
        x, y = header_exit_door_xy(door.x_raw, door.y_raw, sprite)
        self._blit(image, sprite, x, y)

    def _draw_apple_pickup(self, image: Image.Image, part, room: Room) -> None:
        apple = part_apple_marker(part, room.index)
        sprite = self.graphics.sprite("AE000", 45, 0)
        if sprite is not None and apple is not None:
            self._blit(image, sprite, *apple_marker_screen_xy(apple))

    def _draw_actors(self, image: Image.Image, part, room: Room, *, include_hidden: bool) -> None:
        for actor in actor_records_for_room(part, room.index):
            x, y = actor_xy(actor.x, actor.y, frame_min=actor.frame_min)
            if actor.hidden and not include_hidden:
                continue
            sprite = self._sprite_for_actor_record(actor)
            if sprite is None:
                continue
            if actor.hidden:
                sprite = sprite.copy()
                alpha = sprite.getchannel("A").point(lambda value: value // 3)
                sprite.putalpha(alpha)
            self._blit(image, sprite, x, y)

    def _sprite_for_actor_record(self, actor: ActorTableRecord) -> Image.Image | None:
        for frame_start, count, resource_id in self.ACTOR_FRAME_RUNS:
            if frame_start <= actor.frame < frame_start + count:
                sprite = self.graphics.sprite("AE000", resource_id, actor.frame - frame_start)
                if sprite is not None and (actor.frame_variant & 0x01):
                    sprite = sprite.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                return sprite
        return None

    def _draw_player_start(self, image: Image.Image, room: Room, header: bytes) -> None:
        start = header_player_start(header)
        if start is None or room.index != start.room_index:
            return
        sprite = self.graphics.sprite("AE000", 4, 0)
        if sprite is None:
            return
        x = start.x_raw * 2 - 4
        y = start.y_raw - 16
        self._blit(image, sprite, x, y)

    def _draw_payload_debug(self, image: Image.Image, room: Room) -> None:
        draw = ImageDraw.Draw(image)
        for triplet in parse_platform_triplets(room):
            x, y = platform_xy(triplet)
            draw.rectangle([x, y, x + 10, y + 10], outline=(255, 180, 0, 255), width=1)

    def _render_codes(self, image: Image.Image, draw: ImageDraw.ImageDraw, room: Room) -> None:
        for y in range(ROOM_ROWS):
            for x in range(ROOM_COLUMNS):
                value = room.get(x, y)
                colour = self.debug_colours[value % len(self.debug_colours)]
                x0 = x * CELL_SIZE
                y0 = y * CELL_SIZE
                draw.rectangle([x0, y0, x0 + CELL_SIZE - 1, y0 + CELL_SIZE - 1], fill=colour + (255,))

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

    def _draw_grid(self, image: Image.Image, *, zoom: int = 1) -> None:
        draw = ImageDraw.Draw(image, "RGBA")
        cell = CELL_SIZE * max(1, int(zoom))
        width = ROOM_COLUMNS * cell
        height = ROOM_ROWS * cell
        minor = (111, 143, 176, 110)
        major = (182, 212, 240, 145)
        for x in range(ROOM_COLUMNS + 1):
            px = x * cell
            colour = major if x % 4 == 0 else minor
            draw.line((px, 0, px, height), fill=colour)
        for y in range(ROOM_ROWS + 1):
            py = y * cell
            colour = major if y % 4 == 0 else minor
            draw.line((0, py, width, py), fill=colour)
