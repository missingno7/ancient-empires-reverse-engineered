from __future__ import annotations

from dataclasses import dataclass, field
from PIL import Image, ImageDraw

from ..constants import (
    CELL_SIZE,
    ROOM_COLUMNS,
    ROOM_ROWS,
    ROOM_SCREEN_HEIGHT_PX,
    ROOM_SCREEN_WIDTH_PX,
)
from .coordinates import (
    actor_xy,
    header_exit_door_xy,
    control_xy,
    header_object_xy,
    object_entry_xy,
    object_screen_xy,
    rope_tile_xy,
    terrain_tile_xy,
)
from ..game_data.conveyors import ConveyorSpec, compose_conveyor, iter_conveyor_runs
from ..game_data.graphics import GraphicsSet
from ..game_data.level_format import Level, Room
from ..engine import platform_xy
from .object_mapping import visual_render_layer, visual_sprite_ref
from .tile_mapping import CONVEYOR_PHYSICS_TILE_CODES
from .tile_mapping import TERRAIN_CODE_TO_SPRITE


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
    draw_background: bool = True
    control_state_overrides: dict[int, bool] | None = None
    platform_offsets: dict[int, tuple[int, int]] | None = None
    green_block_alternate: dict[int, bool] | None = None
    green_block_remaining: dict[int, list[int]] | None = None
    # The faint "ghost" panel at the green block's *other* position is an
    # editor-only aid showing where the block will move; the running game never
    # draws it.  Editors leave this True; the game renderer sets it False.
    draw_puzzle_ghost: bool = True
    conveyor_frame: int = 0
    animated_decor_phase: int = 0
    conveyor_tiles: list[int] | None = None
    reflector_frames: dict[int, int] | None = None
    collected_artifacts: set[int] | None = None
    show_exit_door: bool = True
    exit_door_frame: int = 0
    show_invisible: bool = False
    transparent_background: bool = False
    display_mode: str = "vga"  # vga, ega, cga


@dataclass
class RoomRenderer:
    graphics: GraphicsSet
    code_to_sprite: dict[int, int | None] = field(default_factory=lambda: dict(TERRAIN_CODE_TO_SPRITE))

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
        background = (0, 0, 0, 0) if options.transparent_background else (0, 0, 0, 255)
        image = Image.new("RGBA", (ROOM_SCREEN_WIDTH_PX, ROOM_SCREEN_HEIGHT_PX), background)
        draw = ImageDraw.Draw(image, "RGBA")
        self._current_theme = part.theme
        self._current_level_index = level.index

        if options.mode == "codes_hex":
            self._render_codes(image, draw, room)
        elif options.mode == "trailing_hex":
            self._render_trailing_probe(image, draw, room)
        else:
            # Render order recovered from the AEPROG room draw routine.  The EXE
            # lays the room down in this exact sequence, so gameplay objects
            # stack on top of decor rather than the other way around:
            #   backdrop (0x2bc0)
            #   compact3 background, code >= 0x80 (0x2bf7)   -- before terrain
            #   terrain + rope tiles (0x2c71)
            #   compact3 foreground, code < 0x80 (0x2d3e)    -- decor, under objects
            #   laser crystals (0xd61c) / platforms (0x28ac)
            #   header diamonds (0x2e32), apple (0x2e89)
            #   control buttons/switches/triggers (0x2f10)
            #   puzzle symbols (0x3085), green blocks (0x3132)
            #   actors last, drawn each frame on top (0x4ef8, base 0xb8)
            if options.draw_background:
                self._draw_background(image, part.theme)
            if options.mode == "game":
                self._draw_animated_decor(image, room, part.theme, phase=options.animated_decor_phase)
                self._draw_visual_objects(image, room, layer="background")
            self._draw_terrain_tiles(image, room, part.theme)

            if options.mode == "game":
                self._draw_visual_objects(image, room, layer="foreground")
                self._draw_conveyor_tiles(image, room, frame=options.conveyor_frame, live_tiles=options.conveyor_tiles)
                self._draw_laser_crystals(image, room, frame_overrides=options.reflector_frames)
                if options.draw_platforms:
                    self._draw_platforms(image, room, offsets=options.platform_offsets)
                if options.show_invisible:
                    self._draw_invisible_blocks(image, room, options.conveyor_tiles)
                self._draw_header_objects(image, room, part.header, collected=options.collected_artifacts)
                if options.show_exit_door:
                    self._draw_exit_door(image, room, part.header, part.theme, options.exit_door_frame)
                self._draw_apple_pickup(image, part, room)
                self._draw_control_records(image, room, control_state_overrides=options.control_state_overrides)
                self._draw_puzzle_markers(image, room)
                if options.draw_puzzle_panels:
                    self._draw_record12_puzzle_panels(
                        image,
                        room,
                        alternate=options.green_block_alternate,
                        remaining=options.green_block_remaining,
                        draw_ghost=options.draw_puzzle_ghost,
                    )
                if options.draw_actors:
                    self._draw_actors(image, part, room, include_hidden=False)
                if options.draw_player_start:
                    self._draw_player_start(image, room, part.header)
            elif options.mode == "payload_debug":
                self._draw_animated_decor(image, room, part.theme, phase=options.animated_decor_phase)
                self._draw_visual_objects(image, room, layer="background")
                self._draw_conveyor_tiles(image, room)
                self._draw_platforms(image, room)
                self._draw_control_records(image, room)
                self._draw_puzzle_markers(image, room)
                self._draw_laser_crystals(image, room)
                self._draw_visual_objects(image, room, layer="foreground")
                self._draw_record12_puzzle_panels(image, room)
                self._draw_header_objects(image, room, part.header, collected=options.collected_artifacts)
                if options.show_exit_door:
                    self._draw_exit_door(image, room, part.header, part.theme, options.exit_door_frame)
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
                    self._blit(image, rope, *rope_tile_xy(x, y))
                    continue
                sprite_index = self.code_to_sprite.get(code)
                if sprite_index is None:
                    continue
                sprite = self.graphics.terrain_sprite(theme, sprite_index)
                if sprite is not None:
                    self._blit(image, sprite, *terrain_tile_xy(x, y))

    def _rope_sprite_for_code(self, code: int) -> Image.Image | None:
        resource_id = self.ROPE_SPRITE_RESOURCES.get(code)
        if resource_id is None:
            return None
        return self.graphics.sprite("AE000", resource_id, 0)


    def _draw_conveyor_tiles(self, image: Image.Image, room: Room, *, frame: int = 0, live_tiles: list[int] | None = None) -> None:
        """Render visible conveyor belts from CV payload objects.

        Terrain codes 0x0F/0x1F are only the scrolling/physics footprint.  A
        tile-only belt is intentionally invisible in the original game.  The
        visible belt is a CV record in the room payload directory header.

        ``frame`` scrolls the 4-frame belt animation; ``live_tiles`` (the runtime
        collision tiles) lets a toggled belt show its current grey/teal direction
        instead of the static payload default.
        """
        parts = [self.graphics.sprite("AE000", 38, i) for i in range(24)]
        runs = iter_conveyor_runs(room)
        for cv in parse_conveyor_visual_records(room):
            # Prefer the live tile (0x0F grey / 0x1F teal) so a triggered belt
            # shows its current direction; otherwise fall back to the static run.
            kind = "teal"
            live_kind = self._conveyor_live_kind(cv, live_tiles)
            if live_kind is not None:
                kind = live_kind
            else:
                for run in runs:
                    if run.cells & cv.cells:
                        kind = run.kind
                        break
            # Both belt kinds advance frames forward; the grey/teal sprite sets
            # themselves encode the scroll direction (the teal frames are the
            # left-moving artwork), so no per-kind frame reversal.
            belt_frame = frame % 4
            width = max(8, (cv.length + 1) * CELL_SIZE)
            strip = compose_conveyor(parts, ConveyorSpec(kind=kind, x=0, y=0, width=width, frame=belt_frame))
            if strip is not None:
                # CV records use the same (raw_x*2, raw_y+0xb8) object family as
                # every other payload object, so the belt sits at the shared
                # object anchor.
                self._blit(image, strip, *object_screen_xy(cv.x_raw, cv.y))

    @staticmethod
    def _conveyor_live_kind(cv, live_tiles: list[int] | None):
        if live_tiles is None:
            return None
        for x, y in cv.cells:
            if 0 <= x < ROOM_COLUMNS and 0 <= y < ROOM_ROWS:
                code = live_tiles[y * ROOM_COLUMNS + x]
                if code == 0x0F:
                    return "grey"
                if code == 0x1F:
                    return "teal"
        return None

    def _draw_platforms(self, image: Image.Image, room: Room, *, offsets: dict[int, tuple[int, int]] | None = None) -> None:
        horizontal = self.graphics.sprite("AE000", 47, 0)
        vertical = self.graphics.sprite("AE000", 48, 0)
        for triplet in parse_platform_triplets(room):
            if not triplet.visible:
                continue
            x, y = platform_xy(triplet)
            # Draw the platform at its current (gradually travelled) offset, in
            # lockstep with the runtime collision shift in RoomSimulation.
            if offsets is not None:
                dx, dy = offsets.get(triplet.index, (0, 0))
                x += dx
                y += dy
            if triplet.orientation == "vertical" and vertical is not None:
                self._blit(image, vertical, x, y)
            elif triplet.orientation == "horizontal" and horizontal is not None:
                self._blit(image, horizontal, x, y)

    def _draw_invisible_blocks(self, image: Image.Image, room: Room, tiles: list[int] | None = None) -> None:
        """Debug overlay: outline invisible solid clusters (developer menu)."""
        from .overlay import _invisible_clusters

        draw = ImageDraw.Draw(image, "RGBA")
        for x_px, y_px, w_px, h_px in _invisible_clusters(room, tiles):
            draw.rectangle(
                [x_px, y_px, x_px + w_px - 1, y_px + h_px - 1],
                outline=(255, 0, 255, 200),
                fill=(255, 0, 255, 60),
            )

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
            arg_b = cmd.arg_b or 0

            # LengthPrefixedControlRecord.raw[0] is the byte length, not the
            # command; the real command is body[0].  The command byte selects
            # the switch family, and bit 0x40 of arg_b is the initial pressed
            # state.  All three families share one draw anchor (control_xy).
            sprite = None
            override = None if control_state_overrides is None else control_state_overrides.get(cmd.record.index)
            pressed = bool(override) if override is not None else bool(arg_b & 0x40)
            if command == 0x00:
                sprite = ceiling_pressed if pressed and ceiling_pressed is not None else ceiling_button
            elif command == 0x01:
                sprite = floor_pressed if pressed and floor_pressed is not None else floor_button
            elif command == 0x02:
                sprite = self.graphics.sprite("AE000", 41, 0)

            if sprite is not None:
                self._blit(image, sprite, *control_xy(cmd))


    def _draw_puzzle_markers(self, image: Image.Image, room: Room) -> None:
        """Draw symbol buttons from section_a.

        The base marker is AE000:009.  Its symbol is a separate one-sprite bank
        AE000:010..016 selected by the compact3 code. This is distinct from the
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
            # AEPROG 0x3085: the medallion (sprite 0x6e88) is blitted at the
            # shared object anchor, and the symbol overlay (selected by
            # record[2]) at exactly +4 px in X (0x30d2: di+4) with the same Y.
            # Both sprites use the record anchor as their top-left position.
            x, y = object_screen_xy(entry.x_raw, entry.y)
            self._blit(image, base, x, y)
            symbol = self.graphics.sprite("AE000", 10 + (entry.code & 0x07), 0)
            if symbol is not None:
                self._blit(image, symbol, x + 4, y)

    def _draw_record12_puzzle_panels(self, image: Image.Image, room: Room, *, alternate: dict[int, bool] | None = None, remaining: dict[int, list[int]] | None = None, draw_ghost: bool = True) -> None:
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
            # Symbols are consumed as they are emitted/touched, so draw only the
            # part of the sequence still to come.
            if remaining is not None and i in remaining:
                seq_values = list(remaining[i])
            else:
                seq_values = _record12_sequence_values(rec)
            panel_img = _draw_sequence_on_panel(self.graphics, panel, seq_values)

            # Byte0/1 is the default position, byte2/3 the alternate.  event09
            # swaps the block to the alternate once the symbol sequence is fully
            # emitted; the live block draws solid at its current position and a
            # ghost at the other.
            at_alternate = bool(alternate.get(i)) if alternate else False
            solid_xy = alternate_xy if (at_alternate and alternate_xy is not None) else default_xy
            ghost_xy = default_xy if (at_alternate and alternate_xy is not None) else alternate_xy
            self._blit(image, panel_img, *solid_xy)
            if draw_ghost and ghost_xy is not None and ghost_xy != solid_xy:
                ghost = panel_img.copy()
                alpha = ghost.getchannel("A").point(lambda a: min(a, 96))
                ghost.putalpha(alpha)
                self._blit(image, ghost, *ghost_xy)

    def _draw_laser_crystals(self, image: Image.Image, room: Room, *, frame_overrides: dict[int, int] | None = None) -> None:
        table = laser_crystal_table(room)
        if not table:
            return
        for entry in table.entries:
            # AEPROG masks compact3 visual codes with 0x3F before indexing the
            # object sprite pointer table.  Laser reflector tables use the same
            # high-bit flags; treating the raw byte as the sprite index hid
            # entries like 0x8A/0x8B/0x8D/0xCA and left only low-valued crystals.
            sprite_index = (frame_overrides or {}).get(entry.index, entry.code & 0x1F)
            sprite = self.graphics.sprite("AE000", 19, sprite_index & 0x1F)
            if sprite is None:
                continue
            self._blit(image, sprite, *object_entry_xy(entry))

    def _draw_animated_decor(self, image: Image.Image, room: Room, theme: int, *, phase: int = 0) -> None:
        table = animated_decor_table(room)
        if table is None:
            return
        resource_id = 25 + theme
        for record in table.records:
            # Each decal cycles its 0-terminated sprite sequence; ``phase`` is
            # the live animation counter (0 = static editor/preview).  The
            # record's own stored phase offsets each decal so they flicker out
            # of sync, exactly like the preview frame.
            seq = record.sprite_sequence
            if seq:
                sprite_index = seq[(record.phase + phase) % len(seq)]
            else:
                sprite_index = record.preview_sprite_index
            sprite = self.graphics.sprite("AE001", resource_id, sprite_index)
            if sprite is None:
                continue
            # Animated decals use the same compact3 coordinate family as theme
            # visuals: x is half-screen space, y is the EXE object anchor.
            entry = ObjectTableEntry(record.source_offset, record.index, record.x_raw, record.y, sprite_index, record.raw)
            self._blit(image, sprite, *object_entry_xy(entry))

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
            # AEPROG draws every compact3 entry through the same top-left blit
            # (0x2bf7 / 0x2d3e -> 0x1a98) with no per-sprite nudge, so background
            # and foreground decor share the one object anchor.
            self._blit(image, sprite, *object_entry_xy(entry))

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

    def _draw_header_objects(self, image: Image.Image, room: Room, header: bytes, *, collected: set[int] | None = None) -> None:
        diamond = self.graphics.sprite("AE000", 44, 0)
        if diamond is None:
            return
        for cand in header_object_candidates(header):
            if collected is not None and cand.index in collected:
                continue
            if cand.room_plus_one != room.index + 1:
                continue
            x, y = header_object_xy(cand.x_raw, cand.y_raw)
            self._blit(image, diamond, x, y)

    def _draw_exit_door(
        self,
        image: Image.Image,
        room: Room,
        header: bytes,
        theme: int,
        frame: int = 0,
    ) -> None:
        door = header_exit_door(header)
        if door is None or door.room_index != room.index:
            return
        sprite = self.graphics.sprite("AE001", 21 + theme, max(0, min(4, int(frame))))
        if sprite is None:
            return
        self._blit(image, sprite, *header_exit_door_xy(door.x_raw, door.y_raw))

    def _draw_apple_pickup(self, image: Image.Image, part, room: Room) -> None:
        apple = part_apple_marker(part, room.index)
        sprite = self.graphics.sprite("AE000", 45, 0)
        if sprite is not None and apple is not None:
            self._blit(image, sprite, *apple_marker_screen_xy(apple))

    def _draw_actors(self, image: Image.Image, part, room: Room, *, include_hidden: bool) -> None:
        for actor in actor_records_for_room(part, room.index):
            x, y = actor_xy(actor.x, actor.y)
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
        return self.actor_sprite(actor.frame, actor.frame_variant)

    def actor_sprite(self, frame: int, frame_variant: int) -> Image.Image | None:
        """Resolve an actor sprite for a (frame, frame_variant) pair.

        Shared by the static record draw and the live simulation draw so both
        paths key off the same AE000 frame runs and horizontal-flip bit.
        """
        for frame_start, count, resource_id in self.ACTOR_FRAME_RUNS:
            if frame_start <= frame < frame_start + count:
                sprite = self.graphics.sprite("AE000", resource_id, frame - frame_start)
                if sprite is not None and (frame_variant & 0x01):
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
