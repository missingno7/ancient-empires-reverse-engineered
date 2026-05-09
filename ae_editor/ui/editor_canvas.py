from __future__ import annotations

from .common import (
    ACTOR_TEMPLATE_BY_KEY,
    ACTOR_TEMPLATE_SPECS,
    AUTO_SOLID_TILE_CODES,
    ActorScriptError,
    CELL_SIZE,
    COLLISION_TILE_CODE,
    CONVEYOR_PHYSICS_TILE_CODES,
    DELETE_SELECTION_HINT,
    EditorHandle,
    ImageTk,
    KnownExtraPickup,
    PLATFORM_TRIPLET_SIZE,
    ROOM_COLUMNS,
    ROOM_ROWS,
    ROPE_TILE_CODES,
    RenderOptions,
    actor_records_for_room,
    actor_xy,
    add_actor_record,
    add_control_command,
    add_conveyor_visual_record,
    add_laser_crystal_entry,
    add_record12_green_block,
    add_section_a_symbol_entry,
    add_visual_compact3_entry,
    animated_decor_table,
    build_room_overlay,
    clear_room_apple_marker,
    clear_runtime_triplet_slot,
    control_commands,
    control_targets,
    control_xy,
    cv_geometry_to_raw,
    decode_control_target,
    delete_actor_record,
    delete_animated_decor_record,
    delete_control_command,
    delete_laser_crystal_entry,
    delete_record12_green_block,
    delete_section_a_symbol_entry,
    delete_visual_compact3_entry,
    first_free_runtime_triplet_slot,
    header_exit_door,
    header_object_candidates,
    header_player_start,
    iter_conveyor_runs,
    laser_crystal_table,
    parse_conveyor_visual_records,
    parse_platform_triplets,
    re,
    record12_green_block_records,
    room_apple_marker,
    section_a_symbol_table,
    set_actor_record_placement,
    set_animated_decor_record,
    set_control_command_body,
    set_conveyor_visual_record,
    set_laser_crystal_entry,
    set_record12_green_block,
    set_room_apple_marker,
    set_section_a_symbol_entry,
    set_visual_compact3_entry,
    tk,
    tkfont,
    visual_compact3_table,
)


class EditorCanvasMixin:
    def redraw_editor_room(self) -> None:
        if not hasattr(self, "editor_canvas"):
            return
        image = self.project.renderer.render_room(
            self.current_level(),
            self.room_var.get(),
            RenderOptions(mode="game", zoom=self.zoom_var.get(), grid=False, part_index=self.part_var.get()),
        )
        self.tk_editor_image = ImageTk.PhotoImage(image)
        self.editor_canvas.delete("all")
        self.editor_canvas.create_image(0, 0, anchor="nw", image=self.tk_editor_image)
        self.editor_canvas.config(scrollregion=(0, 0, image.width, image.height))
        self._update_editor_info()
        self.refresh_property_panel()
        if self.editor_collision_var.get():
            self.draw_collision_overlay(self.editor_canvas, self.current_room())
        self.draw_editor_selection_preview()
        if self.editor_overlay_var.get() or self.editor_tool_var.get() == "select":
            part = self.current_level().part(self.part_var.get())
            room = part.room(self.room_var.get())
            self.draw_editor_object_handles(part, room)
        if self.editor_grid_var.get():
            self.draw_editor_grid()

    def draw_editor_selection_preview(self) -> None:
        tool = self.editor_tool_var.get()
        if tool == "terrain":
            value = self._parse_selected_tile_silent()
            if value is None:
                return
            x = 8
            y = 8
            size = 28
            mode = self._tile_brush_mode()
            self.editor_canvas.create_rectangle(x, y, x + 112, y + 42, fill="#111111", outline="#d8e8ff", stipple="gray50")
            self.editor_canvas.create_text(x + 54, y + 7, text=f"Tile {value:02X} {mode}", fill="#ffffff", font=("Consolas", 9))
            self.editor_canvas.create_rectangle(x + 10, y + 24, x + 10 + size, y + 24 + 8, outline="#d8e8ff", fill="")
        elif tool == "belt":
            text = f"Belt {self.belt_kind_var.get()} x{self._belt_length()}"
            self.editor_canvas.create_rectangle(8, 8, 134, 34, fill="#111111", outline="#d8e8ff", stipple="gray50")
            self.editor_canvas.create_text(14, 14, anchor="nw", text=text, fill="#ffffff", font=("Segoe UI", 9))
        elif tool == "platform":
            text = f"Platform {self.platform_kind_var.get().replace('_', ' ')}"
            self.editor_canvas.create_rectangle(8, 8, 176, 34, fill="#111111", outline="#d8e8ff", stipple="gray50")
            self.editor_canvas.create_text(14, 14, anchor="nw", text=text, fill="#ffffff", font=("Segoe UI", 9))
        elif tool == "select":
            text = "Select" if self.editor_selected_ref is None else self.editor_info.get()
            self.editor_canvas.create_rectangle(8, 8, 132, 34, fill="#111111", outline="#d8e8ff", stipple="gray50")
            self.editor_canvas.create_text(14, 14, anchor="nw", text=text, fill="#ffffff", font=("Segoe UI", 9))
        elif tool == "decor":
            text = f"Decor {self.decor_code_var.get().upper()}"
            self.editor_canvas.create_rectangle(8, 8, 132, 34, fill="#111111", outline="#d8e8ff", stipple="gray50")
            self.editor_canvas.create_text(14, 14, anchor="nw", text=text, fill="#ffffff", font=("Segoe UI", 9))
        elif tool == "room_data":
            text = f"Room {self.current_room().index:02d} data"
            self.editor_canvas.create_rectangle(8, 8, 144, 34, fill="#111111", outline="#d8e8ff", stipple="gray50")
            self.editor_canvas.create_text(14, 14, anchor="nw", text=text, fill="#ffffff", font=("Segoe UI", 9))
        else:
            self.editor_canvas.create_rectangle(8, 8, 132, 34, fill="#111111", outline="#d8e8ff", stipple="gray50")
            self.editor_canvas.create_text(14, 14, anchor="nw", text=self.editor_object_var.get().replace("_", " "), fill="#ffffff", font=("Segoe UI", 9))

    def draw_collision_overlay(self, canvas: tk.Canvas, room) -> None:
        zoom = self.zoom_var.get()
        cell = CELL_SIZE * zoom
        for y in range(ROOM_ROWS):
            for x in range(ROOM_COLUMNS):
                if room.get(x, y) != COLLISION_TILE_CODE:
                    continue
                x0 = x * cell
                y0 = y * cell
                x1 = x0 + cell - 1
                y1 = y0 + cell - 1
                canvas.create_rectangle(
                    x0,
                    y0,
                    x1,
                    y1,
                    outline="#ff66dd",
                    fill="#ff66dd",
                    stipple="gray75",
                    width=1,
                )
                canvas.create_line(x0 + 2, y0 + 2, x1 - 2, y1 - 2, fill="#ffd6f6", width=1)

    def draw_editor_grid(self) -> None:
        zoom = self.zoom_var.get()
        width = ROOM_COLUMNS * CELL_SIZE * zoom
        height = ROOM_ROWS * CELL_SIZE * zoom
        minor = "#6f8fb0"
        major = "#b6d4f0"
        for x in range(ROOM_COLUMNS + 1):
            px = x * CELL_SIZE * zoom
            colour = major if x % 4 == 0 else minor
            self.editor_canvas.create_line(px, 0, px, height, fill=colour, stipple="gray75")
        for y in range(ROOM_ROWS + 1):
            py = y * CELL_SIZE * zoom
            colour = major if y % 4 == 0 else minor
            self.editor_canvas.create_line(0, py, width, py, fill=colour, stipple="gray75")

    def _known_extra_pickups_for_room(self, part, room):
        apple = room_apple_marker(room)
        if apple is not None:
            return [KnownExtraPickup("AE000", 45, 0, apple.x_raw * 2, apple.y_raw)]
        # Compatibility override for shipped apples with non-local marker ids.
        # A cleared zero marker means the user intentionally deleted the apple.
        from ..game_data.room_payload import room_tail_marker
        if room_tail_marker(room) is None:
            return []
        key = (self.current_level().index + 1, part.index, room.index)
        pickup = getattr(self.project.renderer, "KNOWN_LEGACY_APPLES", {}).get(key)
        return [] if pickup is None else [pickup]

    def _draw_editor_handle(self, handle: EditorHandle) -> None:
        zoom = self.zoom_var.get()
        sx = handle.x * zoom
        sy = handle.y * zoom
        selected = handle.ref == self.editor_selected_ref
        r = 7 if selected else 5
        width = 3 if selected else 2
        fill = "#111111" if selected else ""
        self.editor_canvas.create_oval(sx - r, sy - r, sx + r, sy + r, outline=handle.colour, fill=fill, width=width)
        self.editor_canvas.create_text(sx + 8, sy - 9, anchor="nw", text=handle.label, fill=handle.colour, font=("Segoe UI", 8))

    def _green_block_xy_from_raw(self, raw_x: int, raw_y: int) -> tuple[int, int]:
        return raw_x * 2 - 8, raw_y - 12

    def _green_block_raw_from_xy(self, x: int, y: int) -> tuple[int, int]:
        return self._clamp_byte(round((x + 8) / 2)), self._clamp_byte(y + 12)

    def _record12_sequence(self, rec: bytes) -> list[int]:
        values: list[int] = []
        for value in rec[5:10]:
            if value == 0:
                break
            values.append(value)
        return values

    def _format_symbol_sequence(self, rec: bytes) -> str:
        return ",".join(str(v) for v in self._record12_sequence(rec))

    def _parse_symbol_sequence_text(self, text: str, current: list[int]) -> list[int]:
        raw = text.strip()
        if not raw:
            return current
        parts = [p for p in re.split(r"[\s,;>\-]+", raw) if p]
        values: list[int] = []
        for part in parts:
            lower = part.lower()
            if lower.startswith("symbol"):
                lower = lower.removeprefix("symbol")
            if lower.startswith("m") and lower[1:].isdigit():
                # Marker labels M0/M1 are zero-based editor labels; symbol ids
                # in the green block sequence are one-based.
                value = int(lower[1:]) + 1
            else:
                value = self._parse_int_property(lower, default=0)
            if value == 0:
                break
            if not 1 <= value <= 7:
                raise ValueError("symbol ids must be 1..7; 0 terminates the sequence")
            values.append(value)
            if len(values) >= 5:
                break
        return values

    def _write_record12_sequence(self, rec: bytearray, values: list[int]) -> None:
        for i in range(5):
            rec[5 + i] = values[i] if i < len(values) else 0

    def editor_object_handles(self, part, room) -> list[EditorHandle]:
        handles: list[EditorHandle] = []
        door = header_exit_door(part.header)
        if door and door.room_index == room.index:
            handles.append(EditorHandle(("exit_door", None), door.x_raw * 2, door.y_raw, "Exit", "#ffffff"))
        start = header_player_start(part.header)
        if start and room.index == start.room_index:
            handles.append(EditorHandle(("player_start", None), start.x_raw * 2, start.y_raw, "Start", "#7cff6b"))
        # Room links are edited from the Room data tab. They are not drawn as scene objects.
        for cand in header_object_candidates(part.header):
            if cand.room_plus_one == room.index + 1:
                handles.append(EditorHandle(("artifact", cand.index), cand.x_raw * 2, cand.y_raw, f"D{cand.index}", "#ff40ff"))
        for i, pickup in enumerate(self._known_extra_pickups_for_room(part, room)):
            label = "Apple" if pickup.resource_id == 45 else f"Pickup{i}"
            handles.append(EditorHandle(("known_pickup", i), pickup.x + 8, pickup.y + 8, label, "#ff5050"))
        for platform in parse_platform_triplets(room):
            if platform.visible:
                handles.append(EditorHandle(("platform", platform.index), platform.x_raw * 2, platform.y, f"P{platform.index}", "#ffb000"))
        symbol_table = section_a_symbol_table(room)
        if symbol_table is not None:
            for entry in symbol_table.entries:
                symbol_id = (entry.code & 0x07) + 1
                handles.append(EditorHandle(("symbol", entry.index), entry.x_raw * 2, entry.y, f"S{symbol_id}", "#ffd84d"))
        _gb_offset, green_records = record12_green_block_records(room)
        for idx, rec in enumerate(green_records):
            if len(rec) >= 2:
                dx, dy = self._green_block_xy_from_raw(rec[0], rec[1])
                handles.append(EditorHandle(("green_block", idx), dx + 28, dy + 8, f"PD{idx}", "#ffd84d"))
            if len(rec) >= 4:
                ax, ay = self._green_block_xy_from_raw(rec[2], rec[3])
                handles.append(EditorHandle(("green_block_alt", idx), ax + 28, ay + 8, f"PB{idx}", "#c8a840"))

        for cmd in control_commands(room):
            if cmd.command is None or cmd.x_raw is None or cmd.y_raw is None:
                continue
            mode = "button"
            prefix = "C"
            if cmd.command == 0x00:
                mode = "ceiling_button"
                prefix = "B"
            elif cmd.command == 0x01:
                mode = "floor_switch"
                prefix = "S"
            elif cmd.command == 0x02:
                mode = "laser_trigger"
                prefix = "J"
            cx, cy = control_xy(cmd, mode=mode)
            targets = control_targets(cmd)
            suffix = "" if not targets else "→" + ",".join(t.label for t in targets)
            handles.append(EditorHandle(("control", cmd.record.index), cx + 8, cy + 8, f"{prefix}{cmd.record.index}{suffix}", "#00e0ff"))
        for actor in actor_records_for_room(part, room.index):
            # Actor record x/y is the real runtime anchor.  Use that same point as
            # the editor handle so dragging can write x/y back without introducing
            # a per-frame offset.  The sprite top-left is derived via actor_xy()
            # only for drawing/hit testing, not for the stored placement anchor.
            handles.append(EditorHandle(("actor", actor.index), actor.x, actor.y, f"A{actor.index}", "#7cff6b" if not actor.hidden else "#7a7a7a"))
        cv_cells = set()
        for cv in parse_conveyor_visual_records(room):
            cv_cells |= cv.cells
            handles.append(EditorHandle(self._cv_ref(cv), cv.x_raw * 2, cv.y - 8, f"CV{cv.index}×{cv.length}", "#4aa8ff"))
        crystal_table = laser_crystal_table(room)
        if crystal_table is not None:
            for entry in crystal_table.entries:
                handles.append(EditorHandle(("crystal", entry.index), entry.x_raw * 2, entry.y, f"R{entry.index}:{entry.code & 0x3F:02X}", "#44d7ff"))
        visual_table = visual_compact3_table(room)
        if visual_table is not None:
            for entry in visual_table.entries:
                label = f"V{entry.index}:{entry.code:02X}"
                colour = "#d4a8ff"
                handles.append(EditorHandle(("decor", entry.index), entry.x_raw * 2, entry.y, label, colour))
        anim_table = animated_decor_table(room)
        if anim_table is not None:
            for record in anim_table.records:
                handles.append(EditorHandle(("animated_decor", record.index), record.x_raw * 2, record.y, f"AD{record.index}", "#ff9a40"))
        # Tile-only belt runs are physics footprints. Show them as a separate
        # grey handle only when no CV object covers them, because in-game they
        # are invisible but still push the player.
        for belt in iter_conveyor_runs(room):
            if belt.cells & cv_cells:
                continue
            handles.append(EditorHandle(self._belt_run_ref(belt), belt.start_x * CELL_SIZE + 4, belt.y * CELL_SIZE + 4, f"BT{belt.index}×{belt.length}", "#8aa0b8"))
        return handles

    def draw_editor_object_handles(self, part, room) -> None:
        for handle in self.editor_object_handles(part, room):
            self._draw_editor_handle(handle)

    def paint_editor_tile(self, event) -> None:
        cell = self._cell_from_event(event, self.editor_canvas)
        value = self._parse_tile_value()
        if cell is None or value is None:
            return
        if value in CONVEYOR_PHYSICS_TILE_CODES:
            self.select_editor_object("belt_teal" if value == 0x1F else "belt_grey")
            self.status.set(f"Tile {value:02X} is conveyor physics. Switched to Belt placement to keep the CV visual object and physics footprint together.")
            return
        cx, cy = cell
        room = self.current_room()
        mode = self._tile_brush_mode()
        brush = self._brush_size()
        half = brush // 2
        cells = {
            (xx, yy)
            for yy in range(cy - half, cy - half + brush)
            for xx in range(cx - half, cx - half + brush)
            if 0 <= xx < ROOM_COLUMNS and 0 <= yy < ROOM_ROWS
        }
        if not cells:
            return

        # Terrain painting must not leave half-deleted belts behind.  If a tile
        # brush touches a belt footprint, delete that whole composite belt first
        # and then apply the requested tile paint.
        changed = False
        touched_cvs = self._cv_records_touching_cells(room, cells)
        for cv in sorted(touched_cvs, key=lambda r: r.index, reverse=True):
            changed = self._clear_cv_composite(room, cv) or changed
        touched_belts = self._belt_runs_touching_cells(room, cells)
        for belt in touched_belts:
            changed = self._clear_belt_run(room, belt) or changed
        # Painting another terrain value over a platform footprint deletes the
        # platform composite.  Painting 0x07 itself should not delete runtime P
        # records because 0x07 is also a legitimate standalone invisible tile.
        touched_platforms = [] if value == COLLISION_TILE_CODE else self._platforms_touching_cells(room, cells)
        for platform in touched_platforms:
            changed = self._clear_platform_footprint(room, platform) or changed
            clear_runtime_triplet_slot(room, platform.index)
            changed = True
        if (touched_belts or touched_cvs) and self.editor_selected_ref and self.editor_selected_ref[0] in {"belt", "conveyor"}:
            self.editor_selected_ref = None
            self.editor_drag_offset = None
        if touched_platforms and self.editor_selected_ref and self.editor_selected_ref[0] == "platform":
            self.editor_selected_ref = None
            self.editor_drag_offset = None

        if mode == "auto solid":
            active = {
                (xx, yy)
                for yy in range(ROOM_ROWS)
                for xx in range(ROOM_COLUMNS)
                if room.get(xx, yy) in AUTO_SOLID_TILE_CODES
            } | cells
            affected = set(cells)
            for xx, yy in list(cells):
                affected |= {
                    (nx, ny)
                    for nx, ny in ((xx - 1, yy), (xx + 1, yy), (xx, yy - 1), (xx, yy + 1))
                    if 0 <= nx < ROOM_COLUMNS and 0 <= ny < ROOM_ROWS and (nx, ny) in active
                }
            for xx, yy in affected:
                new_value = self._auto_solid_code_for_cell(active, cells, xx, yy)
                if room.get(xx, yy) != new_value:
                    room.set(xx, yy, new_value)
                    changed = True
        elif mode == "auto rope":
            active = {
                (xx, yy)
                for yy in range(ROOM_ROWS)
                for xx in range(ROOM_COLUMNS)
                if room.get(xx, yy) in ROPE_TILE_CODES
            } | cells
            affected = set()
            for xx, yy in cells:
                top = yy
                while (xx, top - 1) in active:
                    top -= 1
                bottom = yy
                while (xx, bottom + 1) in active:
                    bottom += 1
                affected |= {(xx, run_y) for run_y in range(top, bottom + 1)}
            for xx, yy in affected:
                new_value = self._auto_rope_code_for_cell(active, xx, yy)
                if room.get(xx, yy) != new_value:
                    room.set(xx, yy, new_value)
                    changed = True
        else:
            for xx, yy in cells:
                if room.get(xx, yy) == value:
                    continue
                room.set(xx, yy, value)
                changed = True
        if not changed:
            return
        self._set_dirty()
        self.redraw_room()
        removed = len(touched_belts) + len(touched_cvs) + len(touched_platforms)
        if removed:
            self.status.set(f"Painted tile {value:02X}; removed {removed} mechanics object(s) that overlapped the brush.")
        elif mode != "exact":
            self.status.set(f"Painted {mode} brush at x={cx} y={cy}.")

    def place_editor_belt(self, event) -> None:
        cell = self._cell_from_event(event, self.editor_canvas)
        if cell is None:
            return
        start_x, y = cell
        room = self.current_room()
        value = self._belt_tile_code()
        length = self._belt_length()
        actual_length = min(length, ROOM_COLUMNS - start_x)
        footprint = {(x, y) for x in range(start_x, start_x + actual_length)}

        # A real belt is a composite of:
        #   1) 0x0F/0x1F terrain cells = physics/scrolling footprint;
        #   2) CV payload record        = visible animated strip.
        # Never write the first ten runtime triplets; those are platform-like
        # records and can become horizontal platforms in the real game.
        replaced_cvs = self._cv_records_touching_cells(room, footprint)
        for cv in sorted(replaced_cvs, key=lambda r: r.index, reverse=True):
            self._clear_cv_composite(room, cv)
        replaced_tiles = self._belt_runs_touching_cells(room, footprint)
        for belt in replaced_tiles:
            self._clear_belt_run(room, belt)

        self._write_belt_footprint(room, start_x=start_x, y=y, length=actual_length, tile_code=value)
        x_raw, y_raw, code = cv_geometry_to_raw(start_x, y, actual_length)
        cv_index = add_conveyor_visual_record(room, x_raw=x_raw, y=y_raw, code=code, props=self._belt_default_props())
        self.editor_selected_ref = ("conveyor", cv_index)
        self.editor_drag_offset = None
        self._set_dirty()
        self.redraw_room()
        action = "Replaced" if replaced_cvs or replaced_tiles else "Placed"
        self.status.set(f"{action} {self.belt_kind_var.get()} belt CV{cv_index} + physics tile {value:02X} at x={start_x} y={y} len={actual_length}")

    def place_editor_platform(self, event) -> None:
        x, y = self._screen_xy_from_event(event, self.editor_canvas)
        if not (0 <= x < ROOM_COLUMNS * CELL_SIZE and 0 <= y < ROOM_ROWS * CELL_SIZE):
            return
        room = self.current_room()
        slot = first_free_runtime_triplet_slot(room)
        if slot is None:
            self.status.set("No free P slot for a new platform.")
            return
        flags = self._platform_flags()
        x_raw = self._clamp_byte(round(x / 2))
        y_raw = self._clamp_byte(y)
        room.set_trailing_bytes(slot * PLATFORM_TRIPLET_SIZE, [flags, x_raw, y_raw])
        platforms = [p for p in parse_platform_triplets(room) if p.index == slot]
        if platforms:
            self._write_platform_footprint(room, platforms[0])
        self.editor_selected_ref = ("platform", slot)
        self.editor_drag_offset = None
        self._set_dirty()
        self.redraw_room()
        self.redraw_editor_object_palette()
        self.status.set(f"Placed P{slot} platform flags={flags:02X} + 07 footprint at x={x} y={y}")

    def find_editor_handle(self, event) -> EditorHandle | None:
        x, y = self._screen_xy_from_event(event, self.editor_canvas)
        part = self.current_level().part(self.part_var.get())
        room = self.current_room()

        # Actors are larger than the small editor handle dot.  Let clicks anywhere
        # inside the rendered sprite select the actor, while still dragging the
        # stored actor-table anchor smoothly.  This avoids the old jumpy behavior
        # where the visual handle was offset from the value being written back.
        for actor in reversed(actor_records_for_room(part, room.index)):
            ax, ay = actor_xy(actor.x, actor.y, frame_min=actor.frame_min)
            # Most enemy sprites in this game fit in roughly a 24x24 box.  Use a
            # slightly forgiving box because some frames have transparent margins.
            if ax - 2 <= x <= ax + 26 and ay - 2 <= y <= ay + 26:
                return EditorHandle(("actor", actor.index), actor.x, actor.y, f"A{actor.index}", "#7cff6b" if not actor.hidden else "#7a7a7a")

        best: tuple[int, EditorHandle] | None = None
        for handle in self.editor_object_handles(part, room):
            dx = handle.x - x
            dy = handle.y - y
            dist2 = dx * dx + dy * dy
            if dist2 > 12 * 12:
                continue
            if best is None or dist2 < best[0]:
                best = (dist2, handle)
        return None if best is None else best[1]

    def select_editor_handle(self, event) -> None:
        keep_select_tool = self.editor_tool_var.get() == "select"
        handle = self.find_editor_handle(event)
        self.editor_selected_ref = None if handle is None else handle.ref
        self.editor_drag_offset = None
        if handle is None:
            self.status.set("No editable object handle under cursor.")
        else:
            x, y = self._screen_xy_from_event(event, self.editor_canvas)
            self.editor_drag_offset = (handle.x - x, handle.y - y)
            kind = handle.ref[0]
            slot = handle.ref[1] if len(handle.ref) > 1 else None
            if kind == "artifact" and slot is not None:
                self.editor_object_var.set(f"artifact_{slot}")
            elif kind == "platform" and slot is not None:
                platforms = [p for p in parse_platform_triplets(self.current_room()) if p.index == slot]
                if platforms:
                    flag_to_kind = {0x40: "horizontal_right", 0x60: "horizontal_left", 0x80: "vertical_down", 0xA0: "vertical_up"}
                    self.platform_kind_var.set(flag_to_kind.get(platforms[0].flags & 0xF0, self.platform_kind_var.get()))
                    if not keep_select_tool:
                        self.editor_tool_var.set("platform")
                        if hasattr(self, "editor_palettes"):
                            self.editor_palettes.select(1)
            elif kind == "decor" and slot is not None:
                entry = self._decor_from_ref(self.current_room(), handle.ref)
                if entry is not None:
                    self.decor_code_var.set(f"{entry.code:02X}")
                    if not keep_select_tool:
                        self.editor_tool_var.set("decor")
                        if hasattr(self, "editor_palettes"):
                            self.editor_palettes.select(2)
            elif kind == "actor" and slot is not None:
                self.actor_script_share_source_index = int(slot)
                self.scripting_selected_actor_index = int(slot)
                if not keep_select_tool:
                    self.editor_tool_var.set("actor")
                    if hasattr(self, "editor_palettes"):
                        self.editor_palettes.select(1)
            elif kind == "known_pickup":
                self.editor_object_var.set("apple")
                if not keep_select_tool:
                    self.editor_tool_var.set("object")
                    if hasattr(self, "editor_palettes"):
                        self.editor_palettes.select(1)
            elif kind == "room_links":
                if not keep_select_tool:
                    self.editor_tool_var.set("room_data")
                    if hasattr(self, "editor_palettes"):
                        self.editor_palettes.select(3)
            elif kind == "symbol":
                self.editor_object_var.set("symbol_1")
                if not keep_select_tool:
                    self.editor_tool_var.set("object")
                    if hasattr(self, "editor_palettes"):
                        self.editor_palettes.select(1)
            elif kind in {"green_block", "green_block_alt"}:
                self.editor_object_var.set("green_block")
                if not keep_select_tool:
                    self.editor_tool_var.set("object")
                    if hasattr(self, "editor_palettes"):
                        self.editor_palettes.select(1)
            elif kind == "control" and slot is not None:
                cmd = next((cmd for cmd in control_commands(self.current_room()) if cmd.record.index == slot), None)
                command_to_object = {0x00: "ceiling_button", 0x01: "floor_switch", 0x02: "jello"}
                self.editor_object_var.set(command_to_object.get(None if cmd is None else cmd.command, "ceiling_button"))
                if not keep_select_tool:
                    self.editor_tool_var.set("object")
                    if hasattr(self, "editor_palettes"):
                        self.editor_palettes.select(1)
            elif kind == "crystal":
                self.editor_object_var.set("reflector_0")
                if not keep_select_tool:
                    self.editor_tool_var.set("object")
                    if hasattr(self, "editor_palettes"):
                        self.editor_palettes.select(1)
            else:
                self.editor_object_var.set(kind)
            self.status.set(f"Selected {handle.label}")
        self.redraw_editor_object_palette()
        self.redraw_actor_palette()
        self.redraw_editor_room()

    def move_selected_editor_object(self, event) -> None:
        if self.editor_selected_ref is None:
            return
        x, y = self._screen_xy_from_event(event, self.editor_canvas)
        if self.editor_drag_offset is not None:
            x += self.editor_drag_offset[0]
            y += self.editor_drag_offset[1]
        x = max(0, min(ROOM_COLUMNS * CELL_SIZE - 1, x))
        y = max(0, min(ROOM_ROWS * CELL_SIZE - 1, y))
        part = self.current_level().part(self.part_var.get())
        room = self.current_room()
        kind = self.editor_selected_ref[0]
        slot = self.editor_selected_ref[1] if len(self.editor_selected_ref) > 1 else None
        before_raw = part.raw
        before_header = part.header
        before_tiles = list(room.tiles)
        before_trailing = room.trailing

        if kind == "exit_door":
            part.set_exit_door(room.index, self._clamp_byte(round(x / 2)), self._clamp_byte(y))
        elif kind == "player_start":
            if room.index != 0:
                self.status.set("Player start is hard-coded by the game to room 00; switch to room 00 to move it.")
                return
            part.set_player_start(self._clamp_byte(round(x / 2)), self._clamp_byte(y))
        elif kind == "artifact" and slot is not None:
            part.set_artifact_slot(slot, room.index, self._clamp_byte(round(x / 2)), self._clamp_byte(y))
        elif kind == "known_pickup":
            set_room_apple_marker(room, x_raw=self._clamp_byte(round(x / 2)), y=self._clamp_byte(y))
        elif kind == "platform" and slot is not None:
            platforms = [p for p in parse_platform_triplets(room) if p.index == slot]
            if platforms:
                self._clear_platform_footprint(room, platforms[0])
            off = slot * PLATFORM_TRIPLET_SIZE
            room.set_trailing_bytes(off + 1, [self._clamp_byte(round(x / 2)), self._clamp_byte(y)])
            platforms = [p for p in parse_platform_triplets(room) if p.index == slot]
            if platforms:
                self._write_platform_footprint(room, platforms[0])
        elif kind == "symbol" and slot is not None:
            table = section_a_symbol_table(room)
            entry = None if table is None else next((e for e in table.entries if e.index == slot), None)
            if entry is None:
                self.status.set("Selected symbol no longer exists.")
                self.editor_selected_ref = None
                self.editor_drag_offset = None
                self.redraw_editor_room()
                return
            set_section_a_symbol_entry(room, entry.index, x_raw=self._clamp_byte(round(x / 2)), y=self._clamp_byte(y), code=entry.code)
        elif kind in {"green_block", "green_block_alt"} and slot is not None:
            _off, records = record12_green_block_records(room)
            if not 0 <= slot < len(records):
                self.status.set("Selected green block no longer exists.")
                self.editor_selected_ref = None
                self.editor_drag_offset = None
                self.redraw_editor_room()
                return
            rec = bytearray(records[slot])
            old_rec = bytes(rec)
            raw_x, raw_y = self._green_block_raw_from_xy(x - 28, y - 8)
            if kind == "green_block":
                self._clear_green_block_footprint(room, old_rec, alternate=False)
                rec[0], rec[1] = raw_x, raw_y
                self._rewrite_green_block_footprints(room, rec)
            else:
                # PB/alternate is only a destination stored in the mechanism.
                # Moving it must not create, move, or remove 0x07 room tiles.
                rec[2], rec[3] = raw_x, raw_y
            set_record12_green_block(room, slot, bytes(rec))
        elif kind == "control" and slot is not None:
            cmds = [cmd for cmd in control_commands(room) if cmd.record.index == slot]
            if not cmds:
                self.status.set("Selected control no longer exists.")
                self.editor_selected_ref = None
                self.editor_drag_offset = None
                self.redraw_editor_room()
                return
            body = bytearray(cmds[0].body)
            if len(body) < 3:
                self.status.set("Selected control has no editable x/y bytes.")
                return
            body[1] = self._clamp_byte(round(x / 2))
            body[2] = self._clamp_byte(y)
            set_control_command_body(room, slot, bytes(body))
        elif kind == "crystal" and slot is not None:
            table = laser_crystal_table(room)
            entry = None if table is None else next((e for e in table.entries if e.index == slot), None)
            if entry is None:
                self.status.set("Selected reflector no longer exists.")
                self.editor_selected_ref = None
                self.editor_drag_offset = None
                self.redraw_editor_room()
                return
            set_laser_crystal_entry(room, entry.index, x_raw=self._clamp_byte(round(x / 2)), y=self._clamp_byte(y), code=entry.code)
        elif kind == "decor" and slot is not None:
            entry = self._decor_from_ref(room, self.editor_selected_ref)
            if entry is None:
                self.status.set("Selected decor decal no longer exists.")
                self.editor_selected_ref = None
                self.editor_drag_offset = None
                self.redraw_editor_room()
                return
            set_visual_compact3_entry(room, entry.index, x_raw=self._clamp_byte(round(x / 2)), y=self._clamp_byte(y), code=entry.code)
        elif kind == "animated_decor" and slot is not None:
            record = self._animated_decor_from_ref(room, self.editor_selected_ref)
            if record is None:
                self.status.set("Selected animated decor no longer exists.")
                self.editor_selected_ref = None
                self.editor_drag_offset = None
                self.redraw_editor_room()
                return
            set_animated_decor_record(room, record.index, phase=record.phase, x_raw=self._clamp_byte(round(x / 2)), y=self._clamp_byte(y), sequence=record.sequence_raw)
        elif kind == "actor" and slot is not None:
            actor = self._actor_by_index(part, int(slot))
            if actor is None:
                self.status.set("Selected actor no longer exists.")
                self.editor_selected_ref = None
                self.editor_drag_offset = None
                self.redraw_editor_room()
                return
            set_actor_record_placement(part, actor.index, room_index=room.index, x=self._clamp_actor_x(x), y=self._clamp_actor_y(y))
            self.actor_script_share_source_index = actor.index
        elif kind == "known_pickup":
            set_room_apple_marker(room, x_raw=self._clamp_byte(round(x / 2)), y=self._clamp_byte(y))
        elif kind == "conveyor" and slot is not None:
            cv = self._cv_from_ref(room, self.editor_selected_ref)
            if cv is None:
                self.status.set("Selected CV no longer exists.")
                self.editor_selected_ref = None
                self.editor_drag_offset = None
                self.redraw_editor_room()
                return
            old_tile = 0x1F if any(room.get(bx, by) == 0x1F for bx, by in cv.cells if 0 <= bx < ROOM_COLUMNS and 0 <= by < ROOM_ROWS) else self._belt_tile_code()
            for bx, by in cv.cells:
                if 0 <= bx < ROOM_COLUMNS and 0 <= by < ROOM_ROWS and room.get(bx, by) in {0x0F, 0x1F}:
                    room.set(bx, by, 0)
            start_x = max(0, min(ROOM_COLUMNS - 1, x // CELL_SIZE))
            start_y = max(0, min(ROOM_ROWS - 1, y // CELL_SIZE))
            actual_length = min(cv.length, ROOM_COLUMNS - start_x)
            new_cells = {(bx, start_y) for bx in range(start_x, start_x + actual_length)}
            for other in sorted(self._cv_records_touching_cells(room, new_cells), key=lambda r: r.index, reverse=True):
                if other.index != cv.index:
                    self._clear_cv_composite(room, other)
            for other in self._belt_runs_touching_cells(room, new_cells):
                self._clear_belt_run(room, other)
            self._write_belt_footprint(room, start_x=start_x, y=start_y, length=actual_length, tile_code=old_tile)
            x_raw, y_raw, code = cv_geometry_to_raw(start_x, start_y, actual_length)
            set_conveyor_visual_record(room, cv.index, x_raw=x_raw, y=y_raw, code=code, props=cv.props)
        elif kind == "belt":
            run = self._belt_run_from_ref(room, self.editor_selected_ref)
            if run is None:
                self.status.set("Selected belt no longer exists.")
                self.editor_selected_ref = None
                self.editor_drag_offset = None
                self.redraw_editor_room()
                return
            old_code = run.code
            length = run.length
            self._clear_belt_run(room, run)
            start_x = max(0, min(ROOM_COLUMNS - 1, x // CELL_SIZE))
            start_y = max(0, min(ROOM_ROWS - 1, y // CELL_SIZE))
            actual_length = min(length, ROOM_COLUMNS - start_x)
            new_cells = {(bx, start_y) for bx in range(start_x, start_x + actual_length)}
            for other in self._belt_runs_touching_cells(room, new_cells):
                self._clear_belt_run(room, other)
            self._write_belt_footprint(room, start_x=start_x, y=start_y, length=actual_length, tile_code=old_code)
            self.editor_selected_ref = ("belt", start_x, start_y, actual_length, old_code)
        else:
            return

        if part.raw == before_raw and part.header == before_header and room.tiles == before_tiles and room.trailing == before_trailing:
            return
        self._set_dirty()
        self.redraw_room()
        self.redraw_editor_object_palette()
        self.redraw_decor_palette()
        label = kind.replace("_", " ")
        suffix = "" if slot is None or kind == "conveyor" else f" {slot}"
        self.status.set(f"Moved {label}{suffix} to x={x} y={y}")

    def editor_click(self, event) -> None:
        self.editor_canvas.focus_set()
        tool = self.editor_tool_var.get()
        if tool == "select":
            self.select_editor_handle(event)
        elif tool == "terrain":
            self.paint_editor_tile(event)
        elif tool == "belt":
            self.place_editor_belt(event)
        elif tool == "platform":
            handle = self.find_editor_handle(event)
            if handle is not None and handle.ref[0] == "platform":
                self.select_editor_handle(event)
            else:
                self.place_editor_platform(event)
        elif tool == "decor":
            handle = self.find_editor_handle(event)
            if handle is not None and handle.ref[0] == "decor":
                self.select_editor_handle(event)
            else:
                self.place_editor_decor(event)
        elif tool == "actor":
            handle = self.find_editor_handle(event)
            if handle is not None and handle.ref[0] == "actor":
                self.select_editor_handle(event)
            else:
                self.place_editor_actor(event)
        else:
            handle = self.find_editor_handle(event)
            if handle is not None and handle.ref[0] in {
                "exit_door",
                "player_start",
                "artifact",
                "known_pickup",
                "room_links",
                "symbol",
                "green_block",
                "green_block_alt",
                "control",
                "crystal",
            }:
                self.select_editor_handle(event)
            else:
                self.place_editor_object(event)

    def editor_drag(self, event) -> None:
        tool = self.editor_tool_var.get()
        if tool == "select":
            self.move_selected_editor_object(event)
        elif tool == "terrain":
            self.paint_editor_tile(event)
        elif tool == "platform" and self.editor_selected_ref is not None and self.editor_selected_ref[0] == "platform":
            self.move_selected_editor_object(event)
        elif tool == "decor" and self.editor_selected_ref is not None and self.editor_selected_ref[0] == "decor":
            self.move_selected_editor_object(event)
        elif tool == "actor" and self.editor_selected_ref is not None and self.editor_selected_ref[0] == "actor":
            self.move_selected_editor_object(event)
        elif tool == "object" and self.editor_selected_ref is not None and self.editor_selected_ref[0] in {
            "exit_door",
            "player_start",
            "artifact",
            "known_pickup",
            "symbol",
            "green_block",
            "green_block_alt",
            "control",
            "crystal",
        }:
            self.move_selected_editor_object(event)

    def place_editor_actor(self, event) -> None:
        x, y = self._screen_xy_from_event(event, self.editor_canvas)
        if not (0 <= x < ROOM_COLUMNS * CELL_SIZE and 0 <= y < ROOM_ROWS * CELL_SIZE):
            return
        spec = ACTOR_TEMPLATE_BY_KEY.get(self.actor_template_var.get(), ACTOR_TEMPLATE_SPECS[0])
        part = self.current_level().part(self.part_var.get())
        room = self.current_room()
        script_offset = None
        restart_script_offset = None
        script_bytes: bytes | None = b"\x00"
        script_note = "new wait script"
        mode = self.actor_script_mode_var.get()
        try:
            if mode == "share_selected":
                source_actor = self._actor_selected_for_script_sharing()
                if source_actor is None:
                    raise ValueError("no source actor selected to share script_pc")
                script_offset = source_actor.script_offset
                restart_script_offset = source_actor.restart_script_offset
                script_bytes = None
                script_note = f"shared script_pc 0x{script_offset:04X} from A{source_actor.index}"
            elif mode == "address":
                script_offset = self._parse_actor_addr(self.actor_script_address_var.get())
                reset_text = self.actor_script_reset_address_var.get().strip()
                restart_script_offset = script_offset if not reset_text else self._parse_actor_addr(reset_text)
                script_bytes = None
                script_note = f"existing script_pc 0x{script_offset:04X}, restart 0x{restart_script_offset:04X}"
            idx = add_actor_record(
                part,
                room_index=room.index,
                x=self._clamp_byte(x),
                y=self._clamp_byte(y),
                actor_type=spec.actor_type,
                frame=spec.frame,
                frame_variant=0,
                hidden=0,
                frame_min=spec.frame_min,
                frame_max=spec.frame_max,
                script_bytes=script_bytes,
                script_offset=script_offset,
                restart_script_offset=restart_script_offset,
            )
        except (ValueError, ActorScriptError) as exc:
            self.status.set(f"Cannot place actor: {exc}")
            return
        self.editor_selected_ref = ("actor", idx)
        self.scripting_selected_actor_index = idx
        self.actor_script_share_source_index = idx
        self.editor_drag_offset = None
        self._set_dirty()
        self.redraw_room()
        self.redraw_actor_palette()
        self.refresh_actor_scripting_tab()
        self.status.set(f"Placed actor A{idx} {spec.label} at x={x} y={y}; behavior: {script_note}.")

    def editor_pick_tile(self, event) -> None:
        # Right-click on an editable handle selects it. Right-click again or use
        # the Delete button/key to remove it.  Otherwise right-click keeps the
        # original convenient tile-pick behaviour.
        handle = self.find_editor_handle(event)
        if handle is not None:
            self.editor_selected_ref = handle.ref
            self.editor_drag_offset = None
            kind = handle.ref[0]
            slot = handle.ref[1] if len(handle.ref) > 1 else None
            if kind == "artifact" and slot is not None:
                self.editor_object_var.set(f"artifact_{slot}")
            elif kind == "platform" and slot is not None:
                platforms = [p for p in parse_platform_triplets(self.current_room()) if p.index == slot]
                if platforms:
                    flag_to_kind = {0x40: "horizontal_right", 0x60: "horizontal_left", 0x80: "vertical_down", 0xA0: "vertical_up"}
                    self.platform_kind_var.set(flag_to_kind.get(platforms[0].flags & 0xF0, self.platform_kind_var.get()))
                    if not keep_select_tool:
                        self.editor_tool_var.set("platform")
                        if hasattr(self, "editor_palettes"):
                            self.editor_palettes.select(1)
            elif kind == "decor" and slot is not None:
                entry = self._decor_from_ref(self.current_room(), handle.ref)
                if entry is not None:
                    self.decor_code_var.set(f"{entry.code:02X}")
                    if not keep_select_tool:
                        self.editor_tool_var.set("decor")
                        if hasattr(self, "editor_palettes"):
                            self.editor_palettes.select(2)
            elif kind == "animated_decor" and slot is not None:
                if not keep_select_tool:
                    self.editor_tool_var.set("decor")
                    if hasattr(self, "editor_palettes"):
                        self.editor_palettes.select(2)
            else:
                self.editor_object_var.set(kind)
            if kind in {"belt", "conveyor"} and self.editor_tool_var.get() == "belt":
                self.delete_selected_editor_object()
                return
            self.status.set(f"Selected {handle.label}. Press Delete or click Delete to remove it.")
            self.redraw_editor_object_palette()
            self.redraw_editor_room()
            return
        cell = self._cell_from_event(event, self.editor_canvas)
        if cell is None:
            return
        x, y = cell
        value = self.current_room().get(x, y)
        self.select_tile_code(value)
        self.status.set(f"Picked tile {value:02X} at x={x} y={y}")

    def _clamp_byte(self, value: int) -> int:
        return max(0, min(0xFF, int(value)))

    def _clamp_actor_x(self, value: int) -> int:
        # Actor record coordinates are pixel-space anchors stored as u16 values,
        # unlike most static/mechanical records whose X coordinate is stored in
        # half-pixel/raw units.  Do not clamp actor X to one byte during drag:
        # 0xFF is still visibly short of the 304px-wide room.
        return max(0, min(ROOM_COLUMNS * CELL_SIZE - 1, int(value)))

    def _clamp_actor_y(self, value: int) -> int:
        return max(0, min(ROOM_ROWS * CELL_SIZE - 1, int(value)))

    def place_editor_decor(self, event) -> None:
        x, y = self._screen_xy_from_event(event, self.editor_canvas)
        if not (0 <= x < ROOM_COLUMNS * CELL_SIZE and 0 <= y < ROOM_ROWS * CELL_SIZE):
            return
        code = self._parse_decor_code()
        if code is None:
            return
        room = self.current_room()
        try:
            idx = add_visual_compact3_entry(room, x_raw=self._clamp_byte(round(x / 2)), y=self._clamp_byte(y), code=code)
        except ValueError as exc:
            self.status.set(f"Cannot place decor decal: {exc}")
            return
        self.editor_selected_ref = ("decor", idx)
        self.editor_drag_offset = None
        self._set_dirty()
        self.redraw_room()
        self.redraw_decor_palette()
        self.status.set(f"Placed decor V{idx} code={code:02X} at x={x} y={y}")

    def place_editor_object(self, event) -> None:
        x, y = self._screen_xy_from_event(event, self.editor_canvas)
        if not (0 <= x < ROOM_COLUMNS * CELL_SIZE and 0 <= y < ROOM_ROWS * CELL_SIZE):
            return
        part = self.current_level().part(self.part_var.get())
        room = self.current_room()
        obj = self.editor_object_var.get()

        if obj == "exit_door":
            x_raw = self._clamp_byte(round((x + 12) / 2))
            y_raw = self._clamp_byte(y + 16)
            part.set_exit_door(room.index, x_raw, y_raw)
        elif obj == "player_start":
            if room.index != 0:
                self.status.set("Player start is hard-coded by the game to room 00; switch to room 00 to place it.")
                return
            x_raw = self._clamp_byte(round((x + 4) / 2))
            y_raw = self._clamp_byte(y + 16)
            part.set_player_start(x_raw, y_raw)
        elif obj == "room_links":
            self.editor_selected_ref = ("room_links", room.index)
            self.editor_drag_offset = None
            self.redraw_editor_room()
            self.status.set(f"Selected room {room.index:02d} links for editing.")
            return
        elif obj.startswith("artifact_"):
            slot = int(obj.split("_", 1)[1])
            x_raw = self._clamp_byte(round((x + 8) / 2))
            y_raw = self._clamp_byte(y + 16)
            part.set_artifact_slot(slot, room.index, x_raw, y_raw)
        elif obj == "apple":
            x_raw = self._clamp_byte(round(x / 2))
            y_raw = self._clamp_byte(y)
            set_room_apple_marker(room, x_raw=x_raw, y=y_raw)
            self.editor_selected_ref = ("known_pickup", 0)
            self.editor_drag_offset = None
            self.status.set(f"Placed apple at x={x_raw * 2} y={y_raw}. The game supports one red apple marker per room; placing it again moves/replaces it.")
        elif obj.startswith("symbol_"):
            try:
                symbol_id = int(obj.split("_", 1)[1])
            except ValueError:
                self.status.set("Invalid symbol kind.")
                return
            try:
                idx = add_section_a_symbol_entry(room, x_raw=self._clamp_byte(round(x / 2)), y=self._clamp_byte(y), code=(symbol_id - 1) & 0x07)
            except ValueError as exc:
                self.status.set(f"Cannot place symbol: {exc}")
                return
            self.editor_selected_ref = ("symbol", idx)
            self.editor_drag_offset = None
            self.status.set(f"Placed S{symbol_id} / M{idx} at x={x} y={y}.")
        elif obj == "green_block":
            dx_raw, dy_raw = self._green_block_raw_from_xy(x - 28, y - 8)
            # New blocks default to an alternate position one tile-row above,
            # and a one-symbol sequence. The properties panel can refine both.
            ax_raw, ay_raw = self._green_block_raw_from_xy(max(0, x - 28), max(0, y - 40))
            raw = bytes([dx_raw, dy_raw, ax_raw, ay_raw, 0, 1, 0, 0, 0, 0, 0, 0])
            try:
                idx = add_record12_green_block(room, raw)
            except ValueError as exc:
                self.status.set(f"Cannot place green block: {exc}")
                return
            self._rewrite_green_block_footprints(room, raw)
            self.editor_selected_ref = ("green_block", idx)
            self.editor_drag_offset = None
            self.status.set(f"Placed green block PB{idx}/PD{idx}. Edit alternate position and sequence in properties.")
        elif obj.startswith("reflector_"):
            try:
                sprite_index = int(obj.split("_", 1)[1]) & 0x3F
            except ValueError:
                self.status.set("Invalid reflector kind.")
                return
            try:
                idx = add_laser_crystal_entry(room, x_raw=self._clamp_byte(round(x / 2)), y=self._clamp_byte(y), code=sprite_index)
            except ValueError as exc:
                self.status.set(f"Cannot place reflector: {exc}")
                return
            self.editor_selected_ref = ("crystal", idx)
            self.editor_drag_offset = None
            self.status.set(f"Placed reflector R{idx} sprite={sprite_index} at x={x} y={y}. Use R{idx} in a control Targets field to rotate/control it.")
        elif obj in {"ceiling_button", "floor_switch", "jello"}:
            command_by_object = {"ceiling_button": 0x00, "floor_switch": 0x01, "jello": 0x02}
            command = command_by_object[obj]
            x_raw = self._clamp_byte(round((x + 8) / 2))
            y_raw = self._clamp_byte(y + 8)
            state = self._parse_int_property(self.control_state_var.get(), default=0) & 0xFF
            targets = self._parse_control_targets(self.control_targets_var.get(), current=[])
            if not targets:
                self.status.set("New control needs at least one target, for example P0 or CV0.")
                return
            body = bytes([command, x_raw, y_raw, state] + targets)
            idx = add_control_command(room, body)
            self.editor_selected_ref = ("control", idx)
            self.editor_drag_offset = None
            self.status.set(f"Placed {obj} C{idx} targets={','.join(decode_control_target(t).label for t in targets)}")
        else:
            return

        self._set_dirty()
        self.redraw_room()
        self.redraw_editor_object_palette()
        if obj not in {"ceiling_button", "floor_switch", "jello", "apple"} and not obj.startswith("reflector_"):
            self.status.set(f"Placed {obj} at x={x} y={y}")

    def delete_selected_header_object(self) -> None:
        self.delete_selected_editor_object()

    def delete_selected_editor_object(self, _event=None):
        ref = self.editor_selected_ref
        if ref is None:
            obj = self.editor_object_var.get()
            if obj.startswith("artifact_"):
                ref = ("artifact", int(obj.split("_", 1)[1]))
        if ref is None:
            self.status.set(DELETE_SELECTION_HINT)
            return "break"
        kind = ref[0]
        slot = ref[1] if len(ref) > 1 else None
        if kind in {"artifact", "platform", "conveyor"} and slot is None:
            self.status.set(DELETE_SELECTION_HINT)
            return "break"
        if kind == "artifact":
            part = self.current_level().part(self.part_var.get())
            part.clear_artifact_slot(slot)
        elif kind == "platform":
            room = self.current_room()
            platforms = [p for p in parse_platform_triplets(room) if p.index == slot]
            if platforms:
                self._clear_platform_footprint(room, platforms[0])
            clear_runtime_triplet_slot(room, slot)
        elif kind == "conveyor":
            room = self.current_room()
            cv = self._cv_from_ref(room, ref)
            if cv is None:
                self.status.set("Selected CV no longer exists.")
                return "break"
            self._clear_cv_composite(room, cv)
        elif kind == "belt":
            room = self.current_room()
            if not self._clear_belt_composite(room, ref):
                self.status.set("Selected belt no longer exists.")
                return "break"
        elif kind == "symbol":
            room = self.current_room()
            if slot is None:
                self.status.set(DELETE_SELECTION_HINT)
                return "break"
            delete_section_a_symbol_entry(room, slot)
        elif kind in {"green_block", "green_block_alt"}:
            room = self.current_room()
            if slot is None:
                self.status.set(DELETE_SELECTION_HINT)
                return "break"
            _off, records = record12_green_block_records(room)
            if 0 <= slot < len(records):
                self._clear_green_block_footprint(room, records[slot], alternate=False)
            delete_record12_green_block(room, slot)
        elif kind == "control":
            room = self.current_room()
            delete_control_command(room, slot)
        elif kind == "crystal":
            room = self.current_room()
            delete_laser_crystal_entry(room, slot)
        elif kind == "decor":
            room = self.current_room()
            delete_visual_compact3_entry(room, slot)
        elif kind == "animated_decor":
            room = self.current_room()
            delete_animated_decor_record(room, slot)
        elif kind == "actor":
            part = self.current_level().part(self.part_var.get())
            actors = [a for a in actor_records_for_room(part, self.current_room().index) if a.index == slot]
            if not actors:
                self.status.set("Selected actor no longer exists.")
                return "break"
            actor = actors[0]
            try:
                delete_actor_record(part, actor.index, script_offset=actor.script_offset)
            except ValueError as exc:
                self.status.set(f"Cannot delete actor A{actor.index}: {exc}")
                return "break"
            self.scripting_selected_actor_index = None
        elif kind == "known_pickup":
            room = self.current_room()
            clear_room_apple_marker(room)
        else:
            self.status.set(DELETE_SELECTION_HINT)
            return "break"
        if self.editor_selected_ref == ref:
            self.editor_selected_ref = None
            self.editor_drag_offset = None
        self._set_dirty()
        self.redraw_room()
        self.redraw_editor_object_palette()
        self.redraw_decor_palette()
        self.redraw_actor_palette()
        self.refresh_actor_scripting_tab()
        self.status.set(f"Deleted {kind}")
        return "break"

    def draw_codes_overlay(self, room) -> None:
        if not self.overlay_labels_var.get():
            return
        zoom = self.zoom_var.get()
        cell = CELL_SIZE * zoom
        font = tkfont.Font(family="Consolas", size=max(7, min(10, cell // 3)))
        for y in range(ROOM_ROWS):
            for x in range(ROOM_COLUMNS):
                value = room.get(x, y)
                cx = x * cell + cell // 2
                cy = y * cell + cell // 2
                text = f"{value:02X}"
                fill = "#ffffff" if value else "#c8c8c8"
                self.canvas.create_text(cx + 1, cy + 1, text=text, fill="#000000", font=font)
                self.canvas.create_text(cx, cy, text=text, fill=fill, font=font)

    def draw_trailing_overlay(self, room) -> None:
        if not self.overlay_labels_var.get():
            return
        zoom = self.zoom_var.get()
        cols = 19
        cell_w = 16 * zoom
        cell_h = 8 * zoom
        font = tkfont.Font(family="Consolas", size=max(7, min(10, cell_h - 2)))
        for i, value in enumerate(room.trailing[:cols * ROOM_ROWS]):
            x = i % cols
            y = i // cols
            cx = x * cell_w + cell_w // 2
            cy = y * cell_h + cell_h // 2
            fill = "#ffffff" if value else "#9a9a9a"
            text = f"{value:02X}"
            self.canvas.create_text(cx + 1, cy + 1, text=text, fill="#000000", font=font)
            self.canvas.create_text(cx, cy, text=text, fill=fill, font=font)

    def draw_room_overlay(self, level, part, room) -> None:
        overlay = build_room_overlay(level, part, room, include_hidden=self.overlay_hidden_var.get())
        zoom = self.zoom_var.get()
        label_font = tkfont.Font(family="Segoe UI", size=9)

        def sx(value: int) -> int:
            return int(value * zoom)

        def label(x: int, y: int, value: str, colour: str) -> None:
            if not self.overlay_labels_var.get():
                return
            item = self.canvas.create_text(
                sx(x) + 4,
                sx(y) - 16,
                anchor="nw",
                text=value,
                fill=colour,
                font=label_font,
            )
            box = self.canvas.bbox(item)
            if box:
                pad = 2
                bg = self.canvas.create_rectangle(
                    box[0] - pad,
                    box[1] - pad,
                    box[2] + pad,
                    box[3] + pad,
                    fill="#111111",
                    outline=colour,
                    stipple="gray50",
                )
                self.canvas.tag_lower(bg, item)

        def draw_rects(rects) -> None:
            for rect in rects:
                dash = (4, 3) if rect.hidden else None
                self.canvas.create_rectangle(
                    sx(rect.x),
                    sx(rect.y),
                    sx(rect.x + rect.width),
                    sx(rect.y + rect.height),
                    outline=rect.colour,
                    width=2,
                    dash=dash,
                )
                cx, cy = rect.center
                self.canvas.create_line(sx(cx - 10), sx(cy), sx(cx + 10), sx(cy), fill=rect.colour, width=2, dash=(3, 3))
                label(rect.x, rect.y, rect.label, rect.colour)

        def draw_points(points, radius: int = 5, diamond: bool = False) -> None:
            for point in points:
                if diamond:
                    self.canvas.create_polygon(
                        sx(point.x),
                        sx(point.y) - radius,
                        sx(point.x) + radius,
                        sx(point.y),
                        sx(point.x),
                        sx(point.y) + radius,
                        sx(point.x) - radius,
                        sx(point.y),
                        outline=point.colour,
                        fill="",
                        width=2,
                    )
                else:
                    self.canvas.create_oval(
                        sx(point.x) - radius,
                        sx(point.y) - radius,
                        sx(point.x) + radius,
                        sx(point.y) + radius,
                        outline=point.colour,
                        width=2,
                    )
                label(point.x, point.y, point.label, point.colour)

        if self.show_platforms_var.get():
            draw_rects(overlay.platforms)
        if self.show_conveyors_var.get():
            draw_rects(overlay.conveyors)
        if self.show_puzzle_blocks_var.get():
            draw_rects(overlay.puzzle_blocks)
        if self.show_puzzle_destinations_var.get():
            draw_rects(overlay.puzzle_destinations)
        if self.show_actors_var.get():
            draw_rects(overlay.actors)
        if self.show_exits_var.get():
            draw_rects(overlay.exit_doors)

        control_points = [p for p in overlay.controls if p.kind == "control"]
        puzzle_points = [p for p in overlay.controls if p.kind.startswith("puzzle")]
        if self.show_controls_var.get():
            draw_points(control_points, radius=5, diamond=False)
        if self.show_puzzle_markers_var.get():
            draw_points(puzzle_points, radius=5, diamond=False)
        if self.show_pickups_var.get():
            draw_points(overlay.pickups, radius=6, diamond=True)
        if self.show_crystals_var.get():
            draw_points(overlay.crystals, radius=6, diamond=True)

        if self.overlay_links_var.get():
            visible_lines = []
            if self.show_trigger_links_var.get():
                visible_lines.extend(line for line in overlay.links if line.kind == "trigger")
            if self.show_puzzle_links_var.get():
                visible_lines.extend(line for line in overlay.links if line.kind == "puzzle_link")
            if self.show_puzzle_move_links_var.get():
                visible_lines.extend(line for line in overlay.links if line.kind == "puzzle_move")
            if self.show_projectile_links_var.get():
                visible_lines.extend(line for line in overlay.links if line.kind == "projectile")
            if self.show_actor_paths_var.get():
                visible_lines.extend(overlay.actor_paths)
            if self.show_platform_paths_var.get():
                visible_lines.extend(overlay.platform_paths)
            if self.show_exits_var.get():
                visible_lines.extend(overlay.exits)

            for line in visible_lines:
                dash = (5, 4) if line.dashed else None
                self.canvas.create_line(
                    sx(line.start[0]),
                    sx(line.start[1]),
                    sx(line.end[0]),
                    sx(line.end[1]),
                    fill=line.colour,
                    width=2,
                    dash=dash,
                    arrow=tk.LAST,
                )
                label((line.start[0] + line.end[0]) // 2, (line.start[1] + line.end[1]) // 2, line.label, line.colour)

