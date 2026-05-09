from __future__ import annotations

from .common import (
    ACTOR_TEMPLATE_BY_KEY,
    ACTOR_TEMPLATE_SPECS,
    CELL_SIZE,
    COLLISION_TILE_CODE,
    Image,
    ImageTk,
    PLATFORM_KIND_FLAGS,
    ROOM_COLUMNS,
    ROOM_ROWS,
    actor_records_for_room,
    header_exit_door,
    header_object_candidates,
    header_player_start,
    parse_exe_payload_directory,
    tkfont,
)


class PaletteMixin:
    def atlas_categories(self):
        """Return a grouped catalog of recognized gameplay objects.

        Each item is (label, archive, resource_id, sprite_index, note).  The
        static sections are the object catalog/picker. Current-room sections are
        an inspector and are intentionally not used for placement.
        """
        static = [
            (
                "Actors",
                [
                    ("Ant", "AE000", 20, 0, "020:0-1"),
                    ("Pill Projectile", "AE000", 20, 2, "020:2-7"),
                    ("Bat", "AE000", 20, 8, "020:8-14"),
                    ("Praying Mantis", "AE000", 20, 15, "020:15-22"),
                    ("Energy Orb", "AE000", 21, 0, "021:0-3"),
                    ("Fireball", "AE000", 21, 4, "021:4-8"),
                    ("Pegasus Frog", "AE000", 21, 9, "021:9-19"),
                    ("Ladybug", "AE000", 22, 0, "022:0-1"),
                    ("Scarab", "AE000", 22, 2, "022:2-6"),
                    ("Scorpion", "AE000", 22, 7, "022:7-11"),
                    ("Spider", "AE000", 22, 12, "022:12-15"),
                    ("Neon Spider", "AE000", 22, 16, "022:16-19"),
                    ("Snake", "AE000", 22, 20, "022:20-22"),
                    ("Flea", "AE000", 22, 23, "022:23-30"),
                    ("Caterpillar", "AE000", 22, 31, "022:31-36"),
                    ("Sparkles", "AE000", 22, 37, "022:37-40"),
                ],
            ),
            (
                "Player / header objects",
                [
                    ("Player start", "AE000", 4, 0, "header player start"),
                ],
            ),
            (
                "Pickups",
                [
                    *[(f"D{i} artifact", "AE000", 44, 0, f"artifact slot {i}") for i in range(6)],
                    ("Apple", "AE000", 45, 0, "room-tail pickup, max one per room"),
                ],
            ),
            (
                "Exit",
                [
                    ("Exit door, theme 0", "AE001", 21, 0, "header exit door"),
                    ("Exit door, theme 1", "AE001", 22, 0, "header exit door"),
                    ("Exit door, theme 2", "AE001", 23, 0, "header exit door"),
                    ("Exit door, theme 3", "AE001", 24, 0, "header exit door"),
                ],
            ),
            (
                "Triggers / switches",
                [
                    ("Puzzle medal base", "AE000", 9, 0, "section_a base"),
                    ("Ceiling button", "AE000", 39, 0, "control command 00"),
                    ("Ceiling pressed", "AE000", 42, 0, "control command 00, state bit"),
                    ("Floor switch", "AE000", 40, 0, "control command 01"),
                    ("Floor pressed", "AE000", 43, 0, "control command 01, state bit"),
                    ("Light sensor / jello", "AE000", 41, 0, "control command 02"),
                ],
            ),
            (
                "Symbol buttons",
                [(f"S{i + 1}", "AE000", 10 + i, 0, f"symbol {i + 1}") for i in range(7)],
            ),
            (
                "Green block mechanisms",
                [
                    ("Green sequence block", "AE000", 17, 0, "record12: default byte0/1, alternate byte2/3, sequence byte5..9, 0 terminates"),
                ],
            ),
            (
                "Movement objects",
                [
                    ("Platform left", "AE000", 47, 0, "platform horizontal_left"),
                    ("Platform right", "AE000", 47, 0, "platform horizontal_right"),
                    ("Platform down", "AE000", 48, 0, "platform vertical_down"),
                    ("Platform up", "AE000", 48, 0, "platform vertical_up"),
                    ("Conveyor grey", "AE000", 38, 0, "terrain 0F, frame 0"),
                    ("Conveyor teal", "AE000", 38, 12, "terrain 1F, frame 0"),
                ],
            ),
            (
                "Reflectors / laser mirrors",
                [
                    ("Reflector orientation 0", "AE000", 19, 0, "section_c code: bits 0..4 orientation"),
                    ("Reflector orientation 2", "AE000", 19, 2, "section_c code: add 0x40 reverse, 0x80 auto"),
                    ("Reflector orientation 9", "AE000", 19, 9, "section_c code: controls target Rn = 0x40|n"),
                ],
            ),
        ]

        dynamic = []
        level = self.current_level()
        part = level.part(self.part_var.get())
        room = part.room(self.room_var.get())
        actors = []
        for actor in actor_records_for_room(part, room.index):
            actors.append((
                f"A{actor.index} {actor.confirmed_name or 'actor'}",
                "AE000",
                self._actor_resource_id(actor.frame),
                self._actor_sprite_index(actor.frame),
                f"frame={actor.frame:02X} mode={actor.actor_type} hidden={actor.hidden} script={actor.script_offset:04X}",
            ))
        if actors:
            dynamic.append(("Current room: actors", actors))

        controls = []
        directory = parse_exe_payload_directory(room)
        if directory:
            for cmd in directory.control_records:
                body = cmd.body
                if not body:
                    continue
                command = body[0]
                if command == 0:
                    controls.append((f"B{cmd.index} ceiling", "AE000", 39, 0, f"@{cmd.source_offset:02X}"))
                elif command == 1:
                    controls.append((f"S{cmd.index} floor", "AE000", 40, 0, f"@{cmd.source_offset:02X}"))
                elif command == 2:
                    controls.append((f"J{cmd.index} light", "AE000", 41, 0, f"@{cmd.source_offset:02X}"))
            if controls:
                dynamic.append(("Current room: controls", controls))

        pickups = []
        for cand in header_object_candidates(part.header):
            if cand.room_plus_one == room.index + 1:
                pickups.append((f"D{cand.index} artifact", "AE000", 44, 0, f"x={cand.x_raw} y={cand.y_raw}"))
        for pickup in self._known_extra_pickups_for_room(part, room):
            label = "Apple" if pickup.resource_id == 45 else "Known pickup"
            pickups.append((label, pickup.archive, pickup.resource_id, pickup.sprite_index, f"x={pickup.x} y={pickup.y} room-tail marker"))
        if pickups:
            dynamic.append(("Current room: pickups", pickups))

        start = header_player_start(part.header)
        if start is not None and start.room_index == room.index:
            dynamic.append((
                "Current room: player start",
                [("Player start", "AE000", 4, 0, f"room={start.room_index} x={start.x_raw} y={start.y_raw}")],
            ))

        door = header_exit_door(part.header)
        if door is not None and door.room_index == room.index:
            dynamic.append((
                "Current room: exit",
                [(
                    "Exit door",
                    "AE001",
                    21 + part.theme,
                    0,
                    f"x={door.x_raw} y={door.y_raw}",
                )],
            ))

        return static + dynamic

    def _actor_resource_id(self, frame: int) -> int:
        if 0 <= frame < 0x17:
            return 20
        if 0x17 <= frame < 0x2B:
            return 21
        return 22

    def _actor_sprite_index(self, frame: int) -> int:
        if 0 <= frame < 0x17:
            return frame
        if 0x17 <= frame < 0x2B:
            return frame - 0x17
        return frame - 0x2B

    def _current_palette_value(self) -> str | None:
        if self.editor_tool_var.get() == "terrain":
            return f"tile_{self.tile_value_var.get().upper()}"
        if self.editor_tool_var.get() == "belt":
            return f"belt_{self.belt_kind_var.get()}"
        if self.editor_tool_var.get() == "platform":
            return f"platform_{self.platform_kind_var.get()}"
        if self.editor_tool_var.get() == "object":
            return self.editor_object_var.get()
        if self.editor_tool_var.get() == "actor":
            return f"actor:{self.actor_template_var.get()}"
        if self.editor_tool_var.get() == "decor":
            return f"decor_{self.decor_code_var.get().upper()}"
        return None

    def _editable_value_for_atlas_item(self, label: str, archive: str, resource_id: int, sprite_index: int, note: str = "") -> str | None:
        # Prefer exact sprite identity.  This makes the editor palette and the
        # full Objects atlas use the same source of truth even when labels vary.
        if archive == "AE000" and resource_id == 44 and sprite_index == 0:
            lower_note = note.lower()
            if lower_note.startswith("artifact slot "):
                try:
                    slot = int(lower_note.rsplit(" ", 1)[1])
                except ValueError:
                    return None
                return f"artifact_{slot}" if 0 <= slot < 6 else None
            return None
        lower_note = note.lower()
        if label == "Player start" or "player start" in lower_note:
            return "player_start"
        if lower_note.startswith("platform "):
            kind = lower_note.removeprefix("platform ").strip()
            return f"platform_{kind}" if kind in PLATFORM_KIND_FLAGS else None
        if archive == "AE000" and resource_id == 19:
            return f"reflector_{sprite_index & 0x3F}"
        for spec in ACTOR_TEMPLATE_SPECS:
            if label == spec.label and (archive, resource_id, sprite_index) == (spec.archive, spec.resource_id, spec.sprite_index):
                return f"actor:{spec.key}"
        for value, _label, a, rid, si in self.editor_object_specs():
            if (archive, resource_id, sprite_index) == (a, rid, si):
                return value
        return None

    def objects_atlas_click(self, event) -> None:
        if not hasattr(self, "objects_atlas_hitboxes"):
            return
        x = int(self.objects_canvas.canvasx(event.x))
        y = int(self.objects_canvas.canvasy(event.y))
        for x0, y0, x1, y1, value in self.objects_atlas_hitboxes:
            if x0 <= x <= x1 and y0 <= y <= y1:
                if isinstance(value, str) and value.startswith("actor:"):
                    actor_key = value.split(":", 1)[1]
                    self.actor_template_var.set(actor_key)
                    self.select_actor_mode()
                    spec = ACTOR_TEMPLATE_BY_KEY.get(actor_key, ACTOR_TEMPLATE_SPECS[0])
                    self.status.set(f"Selected actor {spec.label} from Objects atlas. Click in the editor to place it.")
                else:
                    self.select_editor_object(value)
                    self.status.set(f"Selected {value.replace('_', ' ')} from Objects atlas. Click in the editor to place it.")
                return

    def redraw_objects_atlas(self) -> None:
        if not hasattr(self, "objects_canvas"):
            return
        self.objects_canvas.delete("all")
        self.tk_atlas_images = []
        self.objects_atlas_hitboxes = []

        x0 = 12
        y = 12
        section_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        category_font = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        item_font = tkfont.Font(family="Segoe UI", size=9)
        note_font = tkfont.Font(family="Segoe UI", size=8)
        last_section = None

        for title, items in self.atlas_categories():
            room_section = title.startswith("Current room:")
            section = "Current room inspector" if room_section else "Placement catalog"
            if section != last_section:
                if last_section is not None:
                    y += 8
                    self.objects_canvas.create_line(x0, y, x0 + 4 * 170 - 8, y, fill="#4f5964")
                    y += 12
                self.objects_canvas.create_text(x0, y, anchor="nw", text=section, fill="#ffffff", font=section_font)
                y += 28
                last_section = section

            title_text = title.replace("Current room: ", "")
            title_colour = "#b8e0ff" if room_section else "#ffffff"
            self.objects_canvas.create_text(x0, y, anchor="nw", text=title_text, fill=title_colour, font=category_font)
            y += 24

            col_w = 170
            row_h = 66
            cols = 4
            for idx, (label, archive, resource_id, sprite_index, note) in enumerate(items):
                col = idx % cols
                row = idx // cols
                x = x0 + col * col_w
                yy = y + row * row_h

                editable_value = None if room_section else self._editable_value_for_atlas_item(label, archive, resource_id, sprite_index, note)
                selected = editable_value is not None and editable_value == self._current_palette_value()
                fill = "#4f6f8f" if selected else ("#343434" if editable_value else "#2b2b2b")
                outline = "#9ed0ff" if editable_value else "#555555"
                self.objects_canvas.create_rectangle(x, yy, x + col_w - 8, yy + row_h - 8, outline=outline, fill=fill)
                if editable_value:
                    self.objects_atlas_hitboxes.append((x, yy, x + col_w - 8, yy + row_h - 8, editable_value))
                sprite = self.project.graphics.sprite(archive, resource_id, sprite_index)
                if sprite is not None:
                    thumb = sprite.copy()
                    max_size = 36
                    scale = min(max_size / max(1, thumb.width), max_size / max(1, thumb.height), 3)
                    if scale != 1:
                        thumb = thumb.resize((max(1, int(thumb.width * scale)), max(1, int(thumb.height * scale))), Image.Resampling.NEAREST)
                    tk_img = ImageTk.PhotoImage(thumb)
                    self.tk_atlas_images.append(tk_img)
                    self.objects_canvas.create_image(x + 22, yy + 25, image=tk_img)

                self.objects_canvas.create_text(x + 48, yy + 8, anchor="nw", text=label, fill="#ffffff", font=item_font)
                self.objects_canvas.create_text(x + 48, yy + 28, anchor="nw", text=f"{archive}:{resource_id:03d}:{sprite_index}", fill="#b8e0ff", font=note_font)
                note_text = ("click to place" if editable_value else note)[:24]
                self.objects_canvas.create_text(x + 48, yy + 43, anchor="nw", text=note_text, fill="#c8c8c8", font=note_font)

            rows = (len(items) + cols - 1) // cols
            y += rows * row_h + 14

        self.objects_canvas.config(scrollregion=(0, 0, 12 + 4 * 170, y + 20))

    def redraw_tile_palette(self) -> None:
        if not hasattr(self, "tile_palette_canvas"):
            return
        self.tile_palette_canvas.delete("all")
        self.tk_tile_images = []
        selected = self._parse_selected_tile_silent()
        part = self.current_level().part(self.part_var.get())
        theme = part.theme
        normal_codes = sorted(self.project.renderer.code_to_sprite.keys())
        # 0x07 is an invisible solid/support tile.  It deliberately has no
        # terrain sprite in the renderer, but it must remain paintable because
        # the original levels use it as standable hidden collision, including
        # around some statue/puzzle setups.
        special_codes = [COLLISION_TILE_CODE, 0x90, 0xA0, 0xB0, 0xC0]
        codes = []
        for code in normal_codes + special_codes:
            if code not in codes:
                codes.append(code)
        self.tile_palette_codes = codes

        cell_w = 76
        cell_h = 58
        cols = 3
        for idx, code in enumerate(codes):
            col = idx % cols
            row = idx // cols
            x = 8 + col * cell_w
            y = 8 + row * cell_h
            fill = "#3a3a3a" if code != selected else "#4f6f8f"
            self.tile_palette_canvas.create_rectangle(x, y, x + cell_w - 8, y + cell_h - 8, outline="#777777", fill=fill)
            sprite = None
            sprite_index = self.project.renderer.code_to_sprite.get(code)
            if sprite_index is not None:
                sprite = self.project.graphics.terrain_sprite(theme, sprite_index)
            elif code in {0x90, 0xA0, 0xB0, 0xC0}:
                rope_rid = {0x90: 5, 0xA0: 6, 0xB0: 7, 0xC0: 8}[code]
                sprite = self.project.graphics.sprite("AE000", rope_rid, 0)
            if sprite is not None:
                thumb = sprite.copy()
                scale = min(2, max(1, 28 // max(1, max(thumb.size))))
                thumb = thumb.resize((max(1, thumb.width * scale), max(1, thumb.height * scale)), Image.Resampling.NEAREST)
                tk_img = ImageTk.PhotoImage(thumb)
                self.tk_tile_images.append(tk_img)
                self.tile_palette_canvas.create_image(x + 34, y + 22, image=tk_img)
            elif code == COLLISION_TILE_CODE:
                self.tile_palette_canvas.create_rectangle(x + 22, y + 12, x + 46, y + 32, outline="#ff66dd", fill="#ff66dd", stipple="gray75")
            self.tile_palette_canvas.create_text(x + 4, y + 38, anchor="nw", text=f"{code:02X}", fill="#ffffff", font=("Consolas", 9))

        rows = (len(codes) + cols - 1) // cols
        self.tile_palette_canvas.config(scrollregion=(0, 0, cols * cell_w + 12, rows * cell_h + 12))

    def tile_palette_click(self, event) -> None:
        if not hasattr(self, "tile_palette_codes"):
            return
        cell_w = 76
        cell_h = 58
        x = int(self.tile_palette_canvas.canvasx(event.x) - 8)
        y = int(self.tile_palette_canvas.canvasy(event.y) - 8)
        if x < 0 or y < 0:
            return
        col = x // cell_w
        row = y // cell_h
        idx = row * 3 + col
        if 0 <= idx < len(self.tile_palette_codes):
            code = self.tile_palette_codes[idx]
            self.select_tile_code(code)

    def redraw_decor_palette(self) -> None:
        if not hasattr(self, "decor_palette_canvas"):
            return
        self.decor_palette_canvas.delete("all")
        self.tk_decor_images = []
        selected = self._parse_decor_code_silent()
        part = self.current_level().part(self.part_var.get())
        bank = self.project.graphics.banks.get(f"AE001:{25 + part.theme:03d}", [])
        codes = list(range(min(64, len(bank))))
        self.decor_palette_codes = codes

        cell_w = 76
        cell_h = 58
        cols = 3
        for idx, code in enumerate(codes):
            col = idx % cols
            row = idx // cols
            x = 8 + col * cell_w
            y = 8 + row * cell_h
            fill = "#4f6f8f" if code == selected else "#343434"
            self.decor_palette_canvas.create_rectangle(x, y, x + cell_w - 8, y + cell_h - 8, outline="#777777", fill=fill)
            sprite = bank[code] if 0 <= code < len(bank) else None
            if sprite is not None:
                thumb = sprite.copy()
                scale = min(2, max(1, 30 // max(1, max(thumb.size))))
                thumb = thumb.resize((max(1, thumb.width * scale), max(1, thumb.height * scale)), Image.Resampling.NEAREST)
                tk_img = ImageTk.PhotoImage(thumb)
                self.tk_decor_images.append(tk_img)
                self.decor_palette_canvas.create_image(x + 34, y + 22, image=tk_img)
            self.decor_palette_canvas.create_text(x + 4, y + 38, anchor="nw", text=f"{code:02X}", fill="#ffffff", font=("Consolas", 9))

        rows = (len(codes) + cols - 1) // cols
        self.decor_palette_canvas.config(scrollregion=(0, 0, cols * cell_w + 12, rows * cell_h + 12))

    def decor_palette_click(self, event) -> None:
        if not hasattr(self, "decor_palette_codes"):
            return
        cell_w = 76
        cell_h = 58
        x = int(self.decor_palette_canvas.canvasx(event.x) - 8)
        y = int(self.decor_palette_canvas.canvasy(event.y) - 8)
        if x < 0 or y < 0:
            return
        col = x // cell_w
        row = y // cell_h
        idx = row * 3 + col
        if 0 <= idx < len(self.decor_palette_codes):
            self.select_decor_code(self.decor_palette_codes[idx])

    def editor_object_specs(self):
        """Editable/placeable atlas entries.

        Each entry is (value, label, archive, resource_id, sprite_index).  This
        is intentionally the single source of truth for the editor-side object
        palette and for clickable entries in the full Objects atlas.
        """
        part = self.current_level().part(self.part_var.get())
        theme = part.theme
        return [
            ("exit_door", "Exit door", "AE001", 21 + theme, 0),
            ("player_start", "Player start", "AE000", 4, 0),
            ("ceiling_button", "Ceiling button", "AE000", 39, 0),
            ("floor_switch", "Floor switch", "AE000", 40, 0),
            ("jello", "Jello / light trigger", "AE000", 41, 0),
            *[(f"symbol_{i}", f"S{i}", "AE000", 9 + i, 0) for i in range(1, 8)],
            ("green_block", "Green sequence block", "AE000", 17, 0),
            ("apple", "Apple", "AE000", 45, 0),
            ("reflector_0", "Reflector 0", "AE000", 19, 0),
            ("reflector_2", "Reflector 2", "AE000", 19, 2),
            ("reflector_4", "Reflector 4", "AE000", 19, 4),
            ("reflector_7", "Reflector 7", "AE000", 19, 7),
            ("reflector_9", "Reflector 9", "AE000", 19, 9),
            ("reflector_16", "Reflector 16", "AE000", 19, 16),
            ("reflector_22", "Reflector 22", "AE000", 19, 22),
            ("belt_grey", "Conveyor grey", "AE000", 38, 0),
            ("belt_teal", "Conveyor teal", "AE000", 38, 12),
            ("platform_horizontal_left", "Platform left", "AE000", 47, 0),
            ("platform_horizontal_right", "Platform right", "AE000", 47, 0),
            ("platform_vertical_down", "Platform down", "AE000", 48, 0),
            ("platform_vertical_up", "Platform up", "AE000", 48, 0),
            *[(f"artifact_{i}", f"D{i} artifact", "AE000", 44, 0) for i in range(6)],
        ]

    def redraw_editor_object_palette(self) -> None:
        if not hasattr(self, "object_palette_canvas"):
            return
        self.object_palette_canvas.delete("all")
        self.tk_editor_object_images = []
        self.editor_object_palette_hitboxes = []

        y = 8
        category_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        item_font = tkfont.Font(family="Segoe UI", size=9)
        note_font = tkfont.Font(family="Segoe UI", size=8)
        row_h = 58
        width = 238

        self.object_palette_canvas.create_text(8, y, anchor="nw", text="Objects", fill="#ffffff", font=category_font)
        y += 24
        for title, items in self.atlas_categories():
            if title.startswith("Current room:") or title == "Actors":
                continue
            placeable_items = [
                (label, archive, resource_id, sprite_index, note, value)
                for label, archive, resource_id, sprite_index, note in items
                for value in [self._editable_value_for_atlas_item(label, archive, resource_id, sprite_index, note)]
                if value is not None
            ]
            if not placeable_items:
                continue
            self.object_palette_canvas.create_text(8, y, anchor="nw", text=title, fill="#b8e0ff", font=category_font)
            y += 22
            for label, archive, resource_id, sprite_index, _note, value in placeable_items:
                selected = value is not None and value == self._current_palette_value()
                fill = "#4f6f8f" if selected else "#343434"
                outline = "#9ed0ff"
                self.object_palette_canvas.create_rectangle(8, y, 8 + width, y + row_h - 6, outline=outline, fill=fill)
                self.editor_object_palette_hitboxes.append((8, y, 8 + width, y + row_h - 6, value))
                sprite = self.project.graphics.sprite(archive, resource_id, sprite_index)
                if sprite is not None:
                    thumb = sprite.copy()
                    max_size = 34
                    scale = min(max_size / max(1, thumb.width), max_size / max(1, thumb.height), 2.5)
                    if scale != 1:
                        thumb = thumb.resize((max(1, int(thumb.width * scale)), max(1, int(thumb.height * scale))), Image.Resampling.NEAREST)
                    tk_img = ImageTk.PhotoImage(thumb)
                    self.tk_editor_object_images.append(tk_img)
                    self.object_palette_canvas.create_image(30, y + 25, image=tk_img)
                self.object_palette_canvas.create_text(56, y + 7, anchor="nw", text=label, fill="#ffffff", font=item_font)
                self.object_palette_canvas.create_text(56, y + 27, anchor="nw", text="click to place", fill="#c8c8c8", font=note_font)
                y += row_h
            y += 8

        self.object_palette_canvas.create_text(8, y, anchor="nw", text="Actors", fill="#b8e0ff", font=category_font)
        y += 22
        for spec in ACTOR_TEMPLATE_SPECS:
            value = f"actor:{spec.key}"
            selected = value == self._current_palette_value()
            fill = "#4f6f8f" if selected else "#343434"
            outline = "#9ed0ff"
            self.object_palette_canvas.create_rectangle(8, y, 8 + width, y + row_h - 6, outline=outline, fill=fill)
            self.editor_object_palette_hitboxes.append((8, y, 8 + width, y + row_h - 6, value))
            sprite = self.project.graphics.sprite(spec.archive, spec.resource_id, spec.sprite_index)
            if sprite is not None:
                thumb = sprite.copy()
                max_size = 34
                scale = min(max_size / max(1, thumb.width), max_size / max(1, thumb.height), 2.5)
                if scale != 1:
                    thumb = thumb.resize((max(1, int(thumb.width * scale)), max(1, int(thumb.height * scale))), Image.Resampling.NEAREST)
                tk_img = ImageTk.PhotoImage(thumb)
                self.tk_editor_object_images.append(tk_img)
                self.object_palette_canvas.create_image(30, y + 25, image=tk_img)
            self.object_palette_canvas.create_text(56, y + 7, anchor="nw", text=spec.label, fill="#ffffff", font=item_font)
            note = f"actor frames={spec.frame_min:02X}-{spec.frame_max:02X}"
            self.object_palette_canvas.create_text(56, y + 27, anchor="nw", text=note, fill="#c8c8c8", font=note_font)
            y += row_h
        y += 8
        self.object_palette_canvas.config(scrollregion=(0, 0, 260, y + 8))

    def object_palette_click(self, event) -> None:
        if not hasattr(self, "editor_object_palette_hitboxes"):
            return
        x = int(self.object_palette_canvas.canvasx(event.x))
        y = int(self.object_palette_canvas.canvasy(event.y))
        for x0, y0, x1, y1, value in self.editor_object_palette_hitboxes:
            if x0 <= x <= x1 and y0 <= y <= y1:
                if isinstance(value, str) and value.startswith("actor:"):
                    actor_key = value.split(":", 1)[1]
                    self.actor_template_var.set(actor_key)
                    self.select_actor_mode()
                    spec = ACTOR_TEMPLATE_BY_KEY.get(actor_key, ACTOR_TEMPLATE_SPECS[0])
                    self.status.set(f"Selected actor {spec.label}. Click in the editor to place it.")
                else:
                    self.select_editor_object(value)
                    self.status.set(f"Selected {value.replace('_', ' ')}. Click in the editor to place it.")
                return

    def redraw_actor_palette(self) -> None:
        if not hasattr(self, "actor_palette_canvas"):
            return
        self.actor_palette_canvas.delete("all")
        self.tk_actor_images = []
        self.actor_palette_hitboxes = []
        y = 8
        title_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        item_font = tkfont.Font(family="Segoe UI", size=9)
        note_font = tkfont.Font(family="Segoe UI", size=8)
        self.actor_palette_canvas.create_text(8, y, anchor="nw", text="Actor families", fill="#ffffff", font=title_font)
        y += 26
        for spec in ACTOR_TEMPLATE_SPECS:
            fill = "#4f6f8f" if self.actor_template_var.get() == spec.key else "#343434"
            outline = "#9ed0ff"
            self.actor_palette_canvas.create_rectangle(8, y, 246, y + 52, outline=outline, fill=fill)
            self.actor_palette_hitboxes.append((8, y, 246, y + 52, spec.key))
            sprite = self.project.graphics.sprite(spec.archive, spec.resource_id, spec.sprite_index)
            if sprite is not None:
                thumb = sprite.copy()
                scale = min(2, max(1, 32 // max(1, max(thumb.size))))
                thumb = thumb.resize((max(1, thumb.width * scale), max(1, thumb.height * scale)), Image.Resampling.NEAREST)
                tk_img = ImageTk.PhotoImage(thumb)
                self.tk_actor_images.append(tk_img)
                self.actor_palette_canvas.create_image(30, y + 25, image=tk_img)
            self.actor_palette_canvas.create_text(56, y + 7, anchor="nw", text=spec.label, fill="#ffffff", font=item_font)
            note = f"frames={spec.frame_min:02X}-{spec.frame_max:02X} mode={spec.actor_type}"
            self.actor_palette_canvas.create_text(56, y + 27, anchor="nw", text=note, fill="#c8c8c8", font=note_font)
            y += 58
        self.actor_palette_canvas.config(scrollregion=(0, 0, 260, y + 8))

    def actor_palette_click(self, event) -> None:
        if not hasattr(self, "actor_palette_hitboxes"):
            return
        x = int(self.actor_palette_canvas.canvasx(event.x))
        y = int(self.actor_palette_canvas.canvasy(event.y))
        for x0, y0, x1, y1, actor_key in self.actor_palette_hitboxes:
            if x0 <= x <= x1 and y0 <= y <= y1:
                self.actor_template_var.set(actor_key)
                self.editor_selected_ref = None
                self.editor_drag_offset = None
                self.editor_tool_var.set("actor")
                if hasattr(self, "editor_palettes"):
                    self.editor_palettes.select(1)
                self.refresh_placeable_settings()
                self.redraw_actor_palette()
                self.redraw_editor_room()
                spec = ACTOR_TEMPLATE_BY_KEY.get(actor_key, ACTOR_TEMPLATE_SPECS[0])
                self.status.set(f"Selected {spec.label}. Click in the editor to place it.")
                return

    def redraw_bank_sheet(self) -> None:
        rid = self.bank_var.get() or next(iter(self.project.graphics.banks.keys()), "AE001:021")
        sheet = self.project.graphics.make_bank_sheet(rid, self.project.graphics.banks.get(rid, []))
        self.tk_sheet = ImageTk.PhotoImage(sheet)
        self.bank_canvas.delete("all")
        self.bank_canvas.create_image(0, 0, anchor="nw", image=self.tk_sheet)
        self.bank_canvas.config(scrollregion=(0, 0, sheet.width, sheet.height))

    def click_room(self, event) -> None:
        zoom = self.zoom_var.get()
        if self.mode_var.get() == "trailing_hex":
            cols = 19
            x = int(self.canvas.canvasx(event.x) // (16 * zoom))
            y = int(self.canvas.canvasy(event.y) // (8 * zoom))
            idx = y * cols + x
            room = self.current_level().part(self.part_var.get()).room(self.room_var.get())
            if 0 <= idx < len(room.trailing):
                value = room.trailing[idx]
                self.status.set(self.status.get() + f" | trailing[{idx:03X}]={value:02X}/{value}")
            return
        x = int(self.canvas.canvasx(event.x) // (CELL_SIZE * zoom))
        y = int(self.canvas.canvasy(event.y) // (CELL_SIZE * zoom))
        if 0 <= x < ROOM_COLUMNS and 0 <= y < ROOM_ROWS:
            value = self.current_level().part(self.part_var.get()).room(self.room_var.get()).get(x, y)
            self.status.set(self.status.get() + f" | click x={x} y={y} tile={value:02X}/{value}")

