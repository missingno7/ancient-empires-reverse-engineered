from __future__ import annotations

from .common import (
    CELL_SIZE,
    COLLISION_TILE_CODE,
    CONVEYOR_PHYSICS_TILE_CODES,
    PLATFORM_FOOTPRINT_CELLS,
    PLATFORM_KIND_FLAGS,
    PLATFORM_TRIPLET_SIZE,
    ROOM_COLUMNS,
    ROOM_COUNT,
    ROOM_ROWS,
    actor_records_for_room,
    add_animated_decor_record,
    add_record12_green_block,
    add_section_a_symbol_entry,
    add_visual_compact3_entry,
    animated_decor_table,
    clear_part_apple_marker,
    control_commands,
    control_targets,
    cv_geometry_to_raw,
    decode_actor_script,
    decode_control_target,
    delete_animated_decor_record,
    delete_conveyor_visual_record,
    delete_record12_green_block,
    delete_section_a_symbol_entry,
    delete_visual_compact3_entry,
    header_exit_door,
    header_object_candidates,
    header_player_start,
    iter_conveyor_runs,
    laser_crystal_table,
    messagebox,
    parse_conveyor_visual_records,
    parse_platform_triplets,
    part_apple_marker,
    platform_xy,
    green_block_footprint_cells,
    re,
    record12_green_block_records,
    section_a_symbol_table,
    set_actor_record_flags,
    set_actor_record_placement,
    set_animated_decor_record,
    set_control_command_body,
    set_conveyor_visual_record,
    set_record12_green_block,
    set_part_apple_marker,
    set_section_a_symbol_entry,
    set_visual_compact3_entry,
    tk,
    transition_links_for_room,
    visual_compact3_table,
    visual_sprite_ref,
    apple_marker_raw_xy,
)


class EditorToolsMixin:
    def _parse_tile_value(self) -> int | None:
        text = self.tile_value_var.get().strip()
        if not text:
            return None
        try:
            value = int(text, 16) if not text.lower().startswith("0x") else int(text, 0)
        except ValueError:
            messagebox.showerror("Invalid tile", f"Tile value must be a byte, got {text!r}.")
            return None
        if not 0 <= value <= 0xFF:
            messagebox.showerror("Invalid tile", f"Tile value must be between 00 and FF, got {text!r}.")
            return None
        self.tile_value_var.set(f"{value:02X}")
        return value

    def _parse_selected_tile_silent(self) -> int | None:
        text = self.tile_value_var.get().strip()
        if not text:
            return None
        try:
            value = int(text, 16) if not text.lower().startswith("0x") else int(text, 0)
        except ValueError:
            return None
        return value if 0 <= value <= 0xFF else None

    def _parse_decor_code(self) -> int | None:
        text = self.decor_code_var.get().strip()
        if not text:
            return None
        try:
            value = int(text, 16) if not text.lower().startswith("0x") else int(text, 0)
        except ValueError:
            messagebox.showerror("Invalid decal", f"Decor code must be a byte, got {text!r}.")
            return None
        if not 0 <= value <= 0xFF:
            messagebox.showerror("Invalid decal", f"Decor code must be between 00 and FF, got {text!r}.")
            return None
        self.decor_code_var.set(f"{value:02X}")
        return value

    def _parse_decor_code_silent(self) -> int | None:
        text = self.decor_code_var.get().strip()
        if not text:
            return None
        try:
            value = int(text, 16) if not text.lower().startswith("0x") else int(text, 0)
        except ValueError:
            return None
        return value if 0 <= value <= 0xFF else None

    def select_tile_code(self, code: int) -> None:
        if code in CONVEYOR_PHYSICS_TILE_CODES:
            self.select_editor_object("belt_teal" if code == 0x1F else "belt_grey")
            self.status.set(f"Tile {code:02X} is conveyor physics; use the Belt tool so it stays paired with a CV visual object.")
            return
        # 0x07 is used both as a platform support footprint and as a standalone
        # invisible solid tile in several original rooms.  Selecting it from the
        # tile palette must therefore keep the user in the Terrain brush instead
        # of switching to platform placement.
        self.editor_tool_var.set("terrain")
        self.editor_selected_ref = None
        self.editor_drag_offset = None
        self.tile_value_var.set(f"{code & 0xFF:02X}")
        self.palette_selection_var.set(f"Painting tile {code & 0xFF:02X}")
        if hasattr(self, "editor_palettes"):
            self.editor_palettes.select(0)
        self.refresh_placeable_settings()
        self.redraw_tile_palette()
        self.redraw_editor_room()

    def select_editor_object(self, value: str) -> None:
        self.editor_selected_ref = None
        self.editor_drag_offset = None
        if value == "belt_grey":
            self.editor_tool_var.set("belt")
            self.belt_kind_var.set("grey")
        elif value == "belt_teal":
            self.editor_tool_var.set("belt")
            self.belt_kind_var.set("teal")
        elif value.startswith("platform_"):
            self.editor_tool_var.set("platform")
            self.platform_kind_var.set(value.removeprefix("platform_"))
        else:
            self.editor_tool_var.set("object")
            self.editor_object_var.set(value)
        if hasattr(self, "editor_palettes"):
            self.editor_palettes.select(1)
        self.refresh_placeable_settings()
        self.redraw_editor_object_palette()
        self.redraw_objects_atlas()
        self.redraw_decor_palette()
        self.redraw_editor_room()

    def select_decor_code(self, code: int) -> None:
        self.editor_selected_ref = None
        self.editor_drag_offset = None
        self.decor_code_var.set(f"{code & 0xFF:02X}")
        self.decor_flip_var.set(bool(code & 0x40))
        self.select_decor_mode()

    def _brush_size(self) -> int:
        try:
            value = int(self.brush_size_var.get())
        except (tk.TclError, ValueError):
            value = 1
        value = max(1, min(5, value))
        self.brush_size_var.set(value)
        return value

    def _tile_brush_mode(self) -> str:
        mode = self.tile_brush_mode_var.get()
        if mode not in {"exact", "auto solid", "auto rope"}:
            mode = "exact"
            self.tile_brush_mode_var.set(mode)
        return mode

    def _auto_solid_code_for_cell(self, active: set[tuple[int, int]], painted: set[tuple[int, int]], x: int, y: int) -> int:
        north = (x, y - 1) in active
        south = (x, y + 1) in active
        west = (x - 1, y) in active
        east = (x + 1, y) in active
        northwest = (x - 1, y - 1) in active
        southwest = (x - 1, y + 1) in active
        if not west:
            if not north:
                return 0x01
            if not south:
                return 0x06
            return 0x03
        if not north:
            if (x - 1, y) not in painted and east and (northwest or southwest):
                return 0x05
            return 0x02
        return 0x04

    def _auto_rope_code_for_cell(self, active: set[tuple[int, int]], x: int, y: int) -> int:
        north = (x, y - 1) in active
        south = (x, y + 1) in active
        if not north:
            return 0x90
        if not south:
            return 0xC0
        depth = 0
        yy = y - 1
        while (x, yy) in active:
            depth += 1
            yy -= 1
        return 0xA0 if depth % 3 == 0 else 0xB0

    def _belt_length(self) -> int:
        try:
            value = int(self.belt_length_var.get())
        except (tk.TclError, ValueError):
            value = 4
        value = max(1, min(ROOM_COLUMNS, value))
        self.belt_length_var.set(value)
        return value

    def _belt_tile_code(self) -> int:
        return 0x1F if self.belt_kind_var.get() == "teal" else 0x0F

    def _belt_default_props(self) -> int:
        # Existing rooms strongly correlate grey/0F belts with props 00-03 and
        # teal/1F belts with props 04-07.  Keep the raw field visible because
        # these bits are probably also used as state/trigger data.
        return 0x07 if self.belt_kind_var.get() == "teal" else 0x00

    def _cv_ref(self, cv) -> tuple[str, int]:
        return ("conveyor", cv.index)

    def _cv_from_ref(self, room, ref):
        if ref is None or ref[0] != "conveyor":
            return None
        index = ref[1]
        for cv in parse_conveyor_visual_records(room):
            if cv.index == index:
                return cv
        return None

    def _decor_from_ref(self, room, ref):
        if ref is None or ref[0] != "decor":
            return None
        table = visual_compact3_table(room)
        if table is None:
            return None
        index = ref[1]
        for entry in table.entries:
            if entry.index == index:
                return entry
        return None

    def _animated_decor_from_ref(self, room, ref):
        if ref is None or ref[0] != "animated_decor":
            return None
        table = animated_decor_table(room)
        if table is None:
            return None
        index = ref[1]
        for record in table.records:
            if record.index == index:
                return record
        return None

    def _format_animated_sequence(self, sequence_raw: bytes) -> str:
        values = []
        for value in sequence_raw:
            if value == 0:
                break
            values.append(f"{max(0, value - 1):02X}")
        return ",".join(values)

    def _parse_animated_sequence_text(self, text: str, current_raw: bytes) -> bytes:
        raw = text.strip()
        if not raw:
            return current_raw
        parts = [p for p in re.split(r"[\s,;>\-]+", raw) if p]
        values: list[int] = []
        for part in parts:
            value = self._parse_int_property(part, default=0)
            if value < 0:
                raise ValueError("animated frame indexes must be >= 0")
            values.append((value + 1) & 0xFF)
            if len(values) >= 8:
                break
        while len(values) < 8:
            values.append(0)
        return bytes(values[:8] + [0])

    def _cv_records_touching_cells(self, room, cells: set[tuple[int, int]]) -> list:
        return [cv for cv in parse_conveyor_visual_records(room) if cv.cells & cells]

    def _clear_cv_composite(self, room, cv) -> bool:
        # Remove the visible CV object and its matching physics footprint.
        for x, y in sorted(cv.cells):
            if 0 <= x < ROOM_COLUMNS and 0 <= y < ROOM_ROWS and room.get(x, y) in {0x0F, 0x1F}:
                room.set(x, y, 0)
        delete_conveyor_visual_record(room, cv.index)
        return True

    def _belt_run_ref(self, run) -> tuple[str, int, int, int, int]:
        # Belts are terrain-run objects, not payload-slot objects. Use the
        # run geometry as the selection handle identity.
        return ("belt", run.start_x, run.y, run.length, run.code)

    def _belt_run_from_ref(self, room, ref):
        if ref is None or ref[0] != "belt":
            return None
        _kind, start_x, y, length, code = ref
        for run in iter_conveyor_runs(room):
            if run.start_x == start_x and run.y == y and run.length == length and run.code == code:
                return run
        return None

    def _belt_runs_touching_cells(self, room, cells: set[tuple[int, int]]) -> list:
        return [run for run in iter_conveyor_runs(room) if run.cells & cells]

    def _clear_belt_run(self, room, run) -> bool:
        changed = False
        for x in range(run.start_x, min(ROOM_COLUMNS, run.start_x + run.length)):
            if room.get(x, run.y) == run.code:
                room.set(x, run.y, 0)
                changed = True
        return changed

    def _clear_belt_composite(self, room, ref) -> bool:
        run = self._belt_run_from_ref(room, ref)
        if run is None:
            return False
        return self._clear_belt_run(room, run)

    def _write_belt_footprint(self, room, *, start_x: int, y: int, length: int, tile_code: int) -> bool:
        changed = False
        for x in range(start_x, min(ROOM_COLUMNS, start_x + length)):
            if room.get(x, y) != tile_code:
                room.set(x, y, tile_code)
                changed = True
        return changed

    def _platform_flags(self) -> int:
        return PLATFORM_KIND_FLAGS.get(self.platform_kind_var.get(), 0x40)

    def _platform_orientation_for_flags(self, flags: int) -> str:
        return "vertical" if (flags & 0xF0) in {0x80, 0xA0} else "horizontal"

    def _platform_footprint_cells(self, platform) -> set[tuple[int, int]]:
        x_px, y_px = platform_xy(platform)
        cols, rows = PLATFORM_FOOTPRINT_CELLS.get(platform.orientation, PLATFORM_FOOTPRINT_CELLS["unknown"])
        start_x = max(0, min(ROOM_COLUMNS - 1, (x_px + 4) // CELL_SIZE))
        start_y = max(0, min(ROOM_ROWS - 1, (y_px + 8) // CELL_SIZE))
        return {
            (x, y)
            for y in range(start_y, min(ROOM_ROWS, start_y + rows))
            for x in range(start_x, min(ROOM_COLUMNS, start_x + cols))
        }

    def _clear_platform_footprint(self, room, platform) -> bool:
        changed = False
        for x, y in self._platform_footprint_cells(platform):
            if room.get(x, y) == COLLISION_TILE_CODE:
                room.set(x, y, 0)
                changed = True
        return changed

    def _write_platform_footprint(self, room, platform) -> bool:
        changed = False
        for x, y in self._platform_footprint_cells(platform):
            if room.get(x, y) != COLLISION_TILE_CODE:
                room.set(x, y, COLLISION_TILE_CODE)
                changed = True
        return changed

    def _green_block_footprint_cells(self, rec: bytes, *, alternate: bool = False) -> set[tuple[int, int]]:
        if len(rec) < (4 if alternate else 2):
            return set()
        base = 2 if alternate else 0
        return green_block_footprint_cells(rec[base], rec[base + 1])

    def _clear_green_block_footprint(self, room, rec: bytes, *, alternate: bool = False) -> bool:
        changed = False
        for x, y in self._green_block_footprint_cells(rec, alternate=alternate):
            if room.get(x, y) == COLLISION_TILE_CODE:
                room.set(x, y, 0)
                changed = True
        return changed

    def _write_green_block_footprint(self, room, rec: bytes, *, alternate: bool = False) -> bool:
        changed = False
        for x, y in self._green_block_footprint_cells(rec, alternate=alternate):
            if room.get(x, y) != COLLISION_TILE_CODE:
                room.set(x, y, COLLISION_TILE_CODE)
                changed = True
        return changed

    def _rewrite_green_block_footprints(self, room, rec: bytes) -> bool:
        # Only the PD/default green-block position is backed by real 0x07
        # collision tiles in the room data.  PB/alternate is a target position
        # stored in the record12 mechanism and must not rewrite the tile map.
        return self._write_green_block_footprint(room, rec, alternate=False)

    def _platforms_touching_cells(self, room, cells: set[tuple[int, int]]) -> list:
        return [platform for platform in parse_platform_triplets(room) if platform.visible and self._platform_footprint_cells(platform) & cells]

    def _update_editor_info(self) -> None:
        tool = self.editor_tool_var.get()
        if tool == "terrain":
            self.editor_info.set(f"tile {self.tile_value_var.get().upper()}  brush {self._brush_size()}x{self._brush_size()}  {self._tile_brush_mode()}")
        elif tool == "belt":
            self.editor_info.set(f"belt {self.belt_kind_var.get()} {self._belt_tile_code():02X}  len {self._belt_length()}  (click place/replace; select+Del removes)")
        elif tool == "platform":
            self.editor_info.set(f"platform {self.platform_kind_var.get().replace('_', ' ')}  (P slot + 07 footprint)")
        elif tool == "decor":
            self.editor_info.set(f"decor decal {self.decor_code_var.get().upper()}")
        elif tool == "actor":
            self.editor_info.set("actors inspect/select")
        elif tool == "select":
            if self.editor_selected_ref is None:
                self.editor_info.set("select")
            else:
                kind = self.editor_selected_ref[0]
                slot = self.editor_selected_ref[1] if len(self.editor_selected_ref) > 1 else None
                suffix = "" if slot is None or kind in {"belt", "conveyor"} else f" {slot}"
                self.editor_info.set(f"selected {kind.replace('_', ' ')}{suffix}")
        else:
            self.editor_info.set(self.editor_object_var.get().replace("_", " "))

    def _screen_xy_from_event(self, event, canvas: tk.Canvas) -> tuple[int, int]:
        zoom = self.zoom_var.get()
        x = int(canvas.canvasx(event.x) // zoom)
        y = int(canvas.canvasy(event.y) // zoom)
        return x, y

    def _cell_from_event(self, event, canvas: tk.Canvas | None = None) -> tuple[int, int] | None:
        canvas = canvas or self.canvas
        x_px, y_px = self._screen_xy_from_event(event, canvas)
        x = x_px // CELL_SIZE
        y = y_px // CELL_SIZE
        if 0 <= x < ROOM_COLUMNS and 0 <= y < ROOM_ROWS:
            return x, y
        return None

    def _set_dirty(self) -> None:
        level_index = self.current_level().index
        self.project.mark_level_dirty(level_index)
        if hasattr(self, "_record_undo_snapshot"):
            self._record_undo_snapshot(level_index)
        suffix = " *" if self.project.dirty else ""
        self.title(f"Ancient Empires Level Editor{suffix}")

    def _parse_int_property(self, value: str, *, default: int = 0) -> int:
        text = value.strip()
        if not text:
            return default
        base = 16 if text.lower().startswith("0x") or any(c in "abcdefABCDEF" for c in text) else 10
        return int(text, base)

    def _parse_room_property(self, *, default: int) -> int:
        value = self.property_room_var.get().strip()
        if not value:
            return max(0, min(ROOM_COUNT - 1, default))
        return max(0, min(ROOM_COUNT - 1, self._parse_int_property(value, default=default)))

    def _format_control_targets(self, cmd) -> str:
        return ",".join(target.label for target in control_targets(cmd))

    def _parse_control_targets(self, text: str, *, current: list[int]) -> list[int]:
        text = text.strip()
        if not text:
            return current
        parts = [part.strip() for part in text.replace(";", ",").split(",")]
        targets: list[int] = []
        for part in parts:
            if not part:
                continue
            upper = part.upper()
            if upper.startswith("CV"):
                idx = self._parse_int_property(part[2:], default=0)
                if not 0 <= idx < 16:
                    raise ValueError(f"CV target index must be 0..15, got {idx}")
                value = 0x10 + idx
            elif upper.startswith("P"):
                idx = self._parse_int_property(part[1:], default=0)
                if not 0 <= idx < 16:
                    raise ValueError(f"platform target index must be 0..15, got {idx}")
                value = idx
            elif upper.startswith("R") or upper.startswith("M"):
                idx = self._parse_int_property(part[1:], default=0)
                if not 0 <= idx < 16:
                    raise ValueError(f"reflector target index must be 0..15, got {idx}")
                value = 0x40 + idx
            else:
                value = self._parse_int_property(part, default=0) & 0xFF
            targets.append(value)
        return targets

    def _rewrite_control_targets(self, body: bytearray, targets: list[int]) -> None:
        if len(body) < 4:
            if targets:
                raise ValueError("this control record has no state/subtype byte before the target list")
            return
        # body[3] is state/subtype. Do not treat it as a target id.
        # Target lists are intentionally resizable in the editor: one switch can
        # control multiple runtime objects, e.g. P1,P2 or P0,CV0.
        del body[4:]
        body.extend(target & 0xFF for target in targets)

    def _reset_property_labels(self) -> None:
        self.property_label_x_var.set("x")
        self.property_label_y_var.set("y")
        self.property_label_len_var.set("len")
        self.property_label_code_var.set("code")
        self.property_label_props_var.set("props/raw")
        self.property_label_room_var.set("room")
        self.property_note_var.set("")

    def _clear_property_values(self) -> None:
        self.property_x_var.set("")
        self.property_y_var.set("")
        self.property_len_var.set("")
        self.property_code_var.set("")
        self.property_props_var.set("")
        self.property_room_var.set("")

    def _set_property_row_visible(self, row_index: int, visible: bool) -> None:
        widgets = self.property_rows[row_index]
        if not visible:
            for widget in widgets:
                if widget is not None:
                    widget.grid_remove()
            return
        row = row_index + 1
        if row_index < 2:
            label_a, entry_a, label_b, entry_b = widgets
            label_a.grid(row=row, column=0, sticky="e", padx=(6, 2), pady=2)
            entry_a.grid(row=row, column=1, sticky="w", pady=2)
            label_b.grid(row=row, column=2, sticky="e", padx=(8, 2), pady=2)
            entry_b.grid(row=row, column=3, sticky="w", pady=2)
        else:
            label, entry, _unused_a, _unused_b = widgets
            label.grid(row=row, column=0, sticky="e", padx=(6, 2), pady=2)
            entry.grid(row=row, column=1, columnspan=3, sticky="ew", pady=2)

    def _layout_property_panel(
        self,
        *,
        rows: tuple[bool, ...] = (False, False, False, False),
        actor_bools: bool = False,
        decor_flip: bool = False,
        apply: bool = False,
    ) -> None:
        padded_rows = tuple(rows) + (False,) * max(0, len(self.property_rows) - len(rows))
        for index in range(len(self.property_rows)):
            self._set_property_row_visible(index, bool(padded_rows[index]))
        base_row = 1 + len(self.property_rows)
        if actor_bools:
            self.property_actor_bool_row.grid(row=base_row, column=0, columnspan=4, sticky="w", padx=6, pady=(2, 2))
            action_row = base_row + 1
        else:
            self.property_actor_bool_row.grid_remove()
            action_row = base_row
        if decor_flip:
            self.property_decor_flip_check.grid(row=action_row, column=0, columnspan=4, sticky="w", padx=6, pady=(2, 2))
            action_row += 1
        else:
            self.property_decor_flip_check.grid_remove()
        if apply:
            self.property_apply_button.grid(row=action_row, column=0, columnspan=4, sticky="ew", padx=6, pady=(4, 4))
            note_row = action_row + 1
        else:
            self.property_apply_button.grid_remove()
            note_row = action_row
        self.property_note_label.grid(row=note_row, column=0, columnspan=4, sticky="w", padx=6, pady=(0, 4))

    def _set_actor_bool_controls(self, *, facing: bool, hidden: bool, show_facing: bool, show_hidden: bool, enabled: bool = False) -> None:
        self.property_actor_facing_var.set(facing)
        self.property_actor_hidden_var.set(hidden)
        self.property_actor_facing_check.pack_forget()
        self.property_actor_hidden_check.pack_forget()
        if show_facing:
            self.property_actor_facing_check.pack(side=tk.LEFT)
        if show_hidden:
            self.property_actor_hidden_check.pack(side=tk.LEFT, padx=(12 if show_facing else 0, 0))
        state = tk.NORMAL if enabled else tk.DISABLED
        self.property_actor_facing_check.configure(state=state)
        self.property_actor_hidden_check.configure(state=state)

    def refresh_property_panel(self) -> None:
        ref = self.editor_selected_ref
        room = self.current_room()
        self._reset_property_labels()
        if ref is None:
            self.property_title_var.set("No object selected")
            self._clear_property_values()
            self._layout_property_panel()
            self.property_note_var.set("Use Select to edit existing CV belts, controls, platforms and actors. Tool-specific placement options are in the tool tabs above.")
            return
        kind = ref[0]
        if kind == "conveyor":
            cv = self._cv_from_ref(room, ref)
            if cv is None:
                self.property_title_var.set("Selected CV no longer exists")
                self._clear_property_values()
                self._layout_property_panel()
                return
            self._layout_property_panel(rows=(True, True, True), apply=True)
            footprint_codes = sorted({room.get(x, y) for x, y in cv.cells if 0 <= x < ROOM_COLUMNS and 0 <= y < ROOM_ROWS})
            self.property_title_var.set(f"CV{cv.index} conveyor visual object")
            self.property_label_x_var.set("cell x")
            self.property_label_y_var.set("cell y")
            self.property_label_len_var.set("length")
            self.property_label_code_var.set("raw code")
            self.property_label_props_var.set("props")
            self.property_x_var.set(str(cv.start_x))
            self.property_y_var.set(str(cv.cell_y))
            self.property_len_var.set(str(cv.length))
            self.property_code_var.set(f"{cv.code:02X}")
            refs = [cmd.record.index for cmd in control_commands(room) if any(t.kind == "conveyor" and t.index == cv.index for t in control_targets(cmd))]
            self.property_props_var.set(f"{cv.props:02X}")
            controlled_by = ", ".join(f"C{i}" for i in refs) or "none"
            self.property_note_var.set(f"Controlled by: {controlled_by}. Physics tiles under CV: {', '.join(f'{c:02X}' for c in footprint_codes) or 'none'}. 0F/1F controls pushing; CV props looks like state/frame bits, while target links usually live in control bytes as CV0/CV1/...")
        elif kind == "belt":
            run = self._belt_run_from_ref(room, ref)
            if run is None:
                self.property_title_var.set("Selected tile-only belt no longer exists")
                self._clear_property_values()
                self._layout_property_panel()
                return
            self._layout_property_panel(rows=(True, True, True))
            self.property_title_var.set("Tile-only conveyor footprint")
            self.property_label_x_var.set("cell x")
            self.property_label_y_var.set("cell y")
            self.property_label_len_var.set("length")
            self.property_label_code_var.set("tile")
            self.property_label_props_var.set("CV")
            self.property_x_var.set(str(run.start_x))
            self.property_y_var.set(str(run.y))
            self.property_len_var.set(str(run.length))
            self.property_code_var.set(f"{run.code:02X}")
            self.property_props_var.set("")
            self.property_note_var.set("This pushes the player but is invisible in game until paired with a CV visual object.")
        elif kind == "platform":
            platforms = [p for p in parse_platform_triplets(room) if p.index == ref[1]]
            if not platforms:
                self.property_title_var.set("Selected platform no longer exists")
                self._clear_property_values()
                self._layout_property_panel()
                return
            self._layout_property_panel(rows=(True, True, False), apply=True)
            pl = platforms[0]
            refs = [cmd.record.index for cmd in control_commands(room) if any(t.kind == "platform" and t.index == pl.index for t in control_targets(cmd))]
            controlled_by = ", ".join(f"C{i}" for i in refs) or "none"
            self.property_title_var.set(f"P{pl.index} platform/runtime object")
            self.property_label_x_var.set("raw x")
            self.property_label_y_var.set("raw y")
            self.property_label_len_var.set("target slot")
            self.property_label_code_var.set("flags")
            self.property_x_var.set(str(pl.x_raw))
            self.property_y_var.set(str(pl.y))
            self.property_len_var.set(f"P{pl.index}")
            self.property_code_var.set(f"{pl.flags:02X}")
            self.property_props_var.set("")
            self.property_note_var.set(f"Controlled by: {controlled_by}. Target slot is fixed. Buttons/switches point here with P0/P1/... target bytes; edit links on the selected control's Targets field. Flags 40/60 are horizontal families, 80/A0 vertical families.")
        elif kind == "symbol":
            idx = ref[1]
            table = section_a_symbol_table(room)
            entry = None if table is None or idx is None else next((e for e in table.entries if e.index == idx), None)
            if entry is None:
                self.property_title_var.set("Selected symbol no longer exists")
                self._clear_property_values()
                self._layout_property_panel()
                return
            symbol_id = (entry.code & 0x07) + 1
            self._layout_property_panel(rows=(True, True, False, True), apply=True)
            self.property_title_var.set(f"S{symbol_id} / M{entry.index}")
            self.property_label_x_var.set("raw x")
            self.property_label_y_var.set("raw y")
            self.property_label_len_var.set("symbol")
            self.property_label_code_var.set("raw code")
            self.property_x_var.set(str(entry.x_raw))
            self.property_y_var.set(str(entry.y))
            self.property_len_var.set(str(symbol_id))
            self.property_code_var.set(f"{entry.code:02X}")
            self.property_room_var.set(str(room.index))
            self.property_note_var.set("Section_a symbol button/emitter. Actor emit_symbol uses a zero-based raw id, so emit_symbol 0 sends S1. Raw symbol-table code is also stored zero-based in bits 0..2. Change Room to move this symbol to another room that has a symbol table.")
        elif kind in {"green_block", "green_block_alt"}:
            idx = ref[1]
            _off, records = record12_green_block_records(room)
            if idx is None or not 0 <= idx < len(records):
                self.property_title_var.set("Selected green block no longer exists")
                self._clear_property_values()
                self._layout_property_panel()
                return
            rec = records[idx]
            if len(rec) < 12:
                self.property_title_var.set("Selected green block is malformed")
                self._clear_property_values()
                self._layout_property_panel()
                return
            self._layout_property_panel(rows=(True, True, True, True), apply=True)
            self.property_title_var.set(f"Green block PB{idx}/PD{idx}")
            self.property_label_x_var.set("default x")
            self.property_label_y_var.set("default y")
            self.property_label_len_var.set("alt x")
            self.property_label_code_var.set("alt y")
            self.property_label_props_var.set("sequence")
            dx, dy = self._green_block_xy_from_raw(rec[0], rec[1])
            ax, ay = self._green_block_xy_from_raw(rec[2], rec[3])
            self.property_x_var.set(str(dx))
            self.property_y_var.set(str(dy))
            self.property_len_var.set(str(ax))
            self.property_code_var.set(str(ay))
            self.property_props_var.set(self._format_symbol_sequence(rec))
            self.property_room_var.set(str(room.index))
            raw = rec.hex(" ")
            self.property_note_var.set(f"Record12 green sequence block. PD/default uses byte0/1; PB/alternate uses byte2/3. Only PD/default owns the 6x2 tile-0x07 footprint. Sequence is up to 5 one-based symbol ids; 0 terminates. Change Room to move the whole mechanism to another room that has a green-block table. Raw: {raw}")
        elif kind == "control":
            idx = ref[1]
            cmds = [cmd for cmd in control_commands(room) if cmd.record.index == idx]
            if not cmds:
                self.property_title_var.set("Selected control no longer exists")
                self._clear_property_values()
                self._layout_property_panel()
                return
            self._layout_property_panel(rows=(True, True, True), apply=True)
            cmd = cmds[0]
            self.property_title_var.set(f"C{idx} trigger/control command @{cmd.record.source_offset:02X}")
            self.property_label_x_var.set("raw x")
            self.property_label_y_var.set("raw y")
            self.property_label_len_var.set("targets")
            self.property_label_code_var.set("type")
            self.property_label_props_var.set("raw body")
            self.property_x_var.set("" if cmd.x_raw is None else str(cmd.x_raw))
            self.property_y_var.set("" if cmd.y_raw is None else str(cmd.y_raw))
            self.property_len_var.set(self._format_control_targets(cmd))
            self.property_code_var.set("" if cmd.command is None else f"{cmd.command:02X}")
            self.property_props_var.set(cmd.body.hex(" "))
            state = cmd.body[3] if len(cmd.body) >= 4 else None
            state_text = "n/a" if state is None else f"{state:02X}"
            self.property_note_var.set("Friendly model: body = type, x, y, state/subtype, target0, target1...  Targets are typed bytes: P0=00, CV0=10, R0=40. One button can control multiple things, e.g. P1,P2,R0,R2. State/subtype is preserved as raw byte " + state_text + ".")
        elif kind == "decor":
            entry = self._decor_from_ref(room, ref)
            if entry is None:
                self.property_title_var.set("Selected decor decal no longer exists")
                self._clear_property_values()
                self._layout_property_panel()
                return
            self._layout_property_panel(rows=(True, True, False, True), decor_flip=True, apply=True)
            sprite_ref = visual_sprite_ref(
                entry,
                theme=self.current_level().part(self.part_var.get()).theme,
                level_index=self.current_level().index,
                room_index=room.index,
                part_index=self.part_var.get(),
            )
            self.property_title_var.set(f"V{entry.index} decor decal")
            self.property_label_x_var.set("raw x")
            self.property_label_y_var.set("raw y")
            self.property_label_len_var.set("raw code")
            self.property_label_code_var.set("sprite")
            self.property_x_var.set(str(entry.x_raw))
            self.property_y_var.set(str(entry.y))
            self.property_len_var.set(f"{entry.code:02X}")
            self.property_code_var.set(f"{sprite_ref.archive}:{sprite_ref.resource_id:03d}:{sprite_ref.sprite_index}")
            self.property_props_var.set("")
            self.property_decor_flip_var.set(bool(entry.code & 0x40))
            self.property_room_var.set(str(room.index))
            self.property_note_var.set((sprite_ref.note or "Theme visual compact3 entry.") + "  Flip edits bit 0x40 while preserving the raw code/layer bits. Change Room to move this decal to another room that has a visual table.")
        elif kind == "animated_decor":
            record = self._animated_decor_from_ref(room, ref)
            if record is None:
                self.property_title_var.set("Selected animated decor no longer exists")
                self._clear_property_values()
                self._layout_property_panel()
                return
            self._layout_property_panel(rows=(True, True, True, True), apply=True)
            theme = self.current_level().part(self.part_var.get()).theme
            self.property_title_var.set(f"AD{record.index} animated decor")
            self.property_label_x_var.set("raw x")
            self.property_label_y_var.set("raw y")
            self.property_label_len_var.set("phase")
            self.property_label_code_var.set("sprite")
            self.property_label_props_var.set("frames")
            self.property_x_var.set(str(record.x_raw))
            self.property_y_var.set(str(record.y))
            self.property_len_var.set(str(record.phase))
            self.property_code_var.set(f"AE001:{25 + theme:03d}:{record.preview_sprite_index}")
            self.property_props_var.set(self._format_animated_sequence(record.sequence_raw))
            self.property_room_var.set(str(room.index))
            self.property_note_var.set("Animated theme decal after the static visual table. Frame values here are zero-based sprite indexes; raw data stores them as +1 and ends with 00. L09 R01 uses four torch-holder AD records with ping-pong frames 14,14,15,15,16,16,15,15.")
        elif kind == "actor":
            idx = ref[1]
            actors = [a for a in actor_records_for_room(self.current_level().part(self.part_var.get()), room.index) if a.index == idx]
            if not actors:
                self.property_title_var.set("Selected actor no longer exists")
                self._clear_property_values()
                self._layout_property_panel()
                return
            actor = actors[0]
            binary_facing = actor.frame_variant in {0, 1}
            binary_hidden = actor.hidden in {0, 1}
            self._layout_property_panel(rows=(True, True, not binary_hidden, True), actor_bools=binary_facing or binary_hidden, apply=True)
            if binary_facing:
                self.property_rows[1][0].grid_remove()
                self.property_rows[1][1].grid_remove()
            self._set_actor_bool_controls(
                facing=bool(actor.frame_variant & 0x01),
                hidden=bool(actor.hidden),
                show_facing=binary_facing,
                show_hidden=binary_hidden,
                enabled=True,
            )
            self.property_title_var.set(f"A{actor.index} {actor.confirmed_name or 'actor'}")
            self.property_label_x_var.set("x")
            self.property_label_y_var.set("y")
            self.property_label_len_var.set("variant")
            self.property_label_code_var.set("frame")
            self.property_label_props_var.set("hidden")
            self.property_x_var.set(str(actor.x))
            self.property_y_var.set(str(actor.y))
            self.property_len_var.set(f"{actor.frame_variant:02X}")
            self.property_code_var.set(f"{actor.frame:02X}")
            self.property_props_var.set(f"{actor.hidden:02X}")
            self.property_room_var.set(str(actor.room_index))
            decoded = decode_actor_script(self.current_level().part(self.part_var.get()), actor, max_bytes=96, max_segments=8)
            note_bits = []
            if binary_facing:
                note_bits.append("variant is shown as a boolean when it is 0/1")
            if binary_hidden:
                note_bits.append("hidden is shown as a checkbox when it is 0/1")
            bool_text = ("; " + "; ".join(note_bits)) if note_bits else ""
            self.property_note_var.set(
                "Actor record. Placement/flags are edited here; behavior steps live in the shared Script space. Record layout: "
                f"mode={actor.actor_type:02X}, room={actor.room_index}, delay={actor.delay}, cooldown={actor.cooldown}, "
                f"frame_range={actor.frame_min:02X}-{actor.frame_max:02X}, script={actor.script_offset:04X}, "
                f"saved_pc={actor.saved_script_offset:04X}, restart={actor.restart_script_offset:04X}, "
                f"loops={actor.loop_counter_a}/{actor.loop_counter_b}/{actor.loop_counter_c}, "
                f"contact={actor.contact_behavior:02X}, activated={actor.activated_flag:02X}. "
                f"{self._format_runtime_offsets_in_text(decoded.summary)}{bool_text}."
            )
        elif kind == "crystal":
            idx = ref[1]
            table = laser_crystal_table(room)
            entry = None if table is None else next((e for e in table.entries if e.index == idx), None)
            if entry is None:
                self.property_title_var.set("Selected reflector no longer exists")
                self._clear_property_values()
                self._layout_property_panel()
                return
            cmd_by_index = {cmd.record.index: cmd for cmd in control_commands(room)}
            refs = [cmd.record.index for cmd in cmd_by_index.values() if any(t.kind == "reflector" and t.index == entry.index for t in control_targets(cmd))]
            def _ctrl_label(i: int) -> str:
                cmd = cmd_by_index.get(i)
                if cmd is None:
                    return f"C{i}"
                if cmd.command == 0x00:
                    return f"B{i}"
                if cmd.command == 0x01:
                    return f"S{i}"
                if cmd.command == 0x02:
                    return f"J{i}"
                return f"C{i}"
            controlled_by = ", ".join(_ctrl_label(i) for i in refs) or "none"
            self._layout_property_panel(rows=(True, True, True), apply=True)
            self.property_title_var.set(f"Reflector R{entry.index}")
            self.property_label_x_var.set("raw x")
            self.property_label_y_var.set("raw y")
            self.property_label_len_var.set("raw code")
            self.property_label_code_var.set("orientation")
            self.property_label_props_var.set("controlled by")
            self.property_x_var.set(str(entry.x_raw))
            self.property_y_var.set(str(entry.y))
            self.property_len_var.set(f"{entry.code:02X}")
            self.property_code_var.set(str(entry.code & 0x1F))
            self.property_props_var.set(controlled_by)
            reverse = "yes" if entry.code & 0x40 else "no"
            auto = "yes" if entry.code & 0x80 else "no"
            self.property_note_var.set(f"Section_c reflector entry. Controls rotate it with R{entry.index} target byte {0x40 | entry.index:02X}. Code bits: 0..4=orientation/frame ({entry.code & 0x1F}), 0x40=reverse rotation ({reverse}), 0x80=auto-rotate ({auto}). Controlled-by is informational; edit links on the selected button/switch Targets field.")
        elif kind == "room_links":
            links = transition_links_for_room(self.current_level().part(self.part_var.get()), room.index)
            self._layout_property_panel(rows=(True, True, False), apply=True)
            self.property_title_var.set(f"Room {room.index:02d} links")
            self.property_label_x_var.set("left")
            self.property_label_y_var.set("right")
            self.property_label_len_var.set("up")
            self.property_label_code_var.set("down")
            def fmt(value: int | None) -> str:
                if value is None or value == 0:
                    return "-"
                return str(value - 1)
            self.property_x_var.set(fmt(None if links is None else links.left))
            self.property_y_var.set(fmt(None if links is None else links.right))
            self.property_len_var.set(fmt(None if links is None else links.up))
            self.property_code_var.set(fmt(None if links is None else links.down))
            self.property_note_var.set("Room navigation data. Values are zero-based room ids; '-' means no link. Stored format is one-based, but the editor hides that.")
        elif kind == "known_pickup":
            idx = ref[1]
            part = self.current_level().part(self.part_var.get())
            apple = self._apple_pickup_for_room(part, room)
            if idx not in (None, 0) or apple is None:
                self.property_title_var.set("Selected apple no longer exists")
                self._clear_property_values()
                self._layout_property_panel()
                return
            self._layout_property_panel(rows=(True, True, False, True), apply=True)
            self.property_title_var.set("Apple")
            self.property_label_x_var.set("raw x")
            self.property_label_y_var.set("y")
            self.property_label_len_var.set("storage")
            self.property_label_code_var.set("sprite")
            marker = part_apple_marker(part, room.index)
            x_raw, y_raw = apple_marker_raw_xy(marker)
            self.property_x_var.set(str(x_raw))
            self.property_y_var.set(str(y_raw))
            self.property_len_var.set("runtime tail")
            self.property_code_var.set("AE000:045:0")
            self.property_room_var.set(str(room.index))
            self.property_note_var.set("Real red apple pickup. Runtime storage is split across the current record tail and the next record preamble: x_raw, y, room+1 gate. The game supports one such apple marker per room. Change Room to move it.")
        elif kind in {"exit_door", "player_start", "artifact"}:
            self._layout_property_panel(rows=(True, True, False), apply=True)
            self.property_label_x_var.set("raw x")
            self.property_label_y_var.set("raw y")
            self.property_label_len_var.set("room")
            self.property_label_code_var.set("slot")
            if kind == "exit_door":
                door = header_exit_door(self.current_level().part(self.part_var.get()).header)
                if door is None:
                    self.property_title_var.set("Exit door is not configured")
                    self._clear_property_values()
                    self._layout_property_panel()
                    return
                self.property_title_var.set("Exit door")
                self.property_x_var.set(str(door.x_raw))
                self.property_y_var.set(str(door.y_raw))
                self.property_len_var.set(str(door.room_index))
                self.property_code_var.set("-")
                self.property_note_var.set("Header object. Move the handle or edit raw x/y here.")
            elif kind == "player_start":
                start = header_player_start(self.current_level().part(self.part_var.get()).header)
                if start is None:
                    self.property_title_var.set("Player start is not configured")
                    self._clear_property_values()
                    self._layout_property_panel()
                    return
                self.property_title_var.set("Player start")
                self.property_x_var.set(str(start.x_raw))
                self.property_y_var.set(str(start.y_raw))
                self.property_len_var.set(str(start.room_index))
                self.property_code_var.set("-")
                self.property_note_var.set("Header object. The original game always starts in room 00; only raw x/y are editable.")
            else:
                slot = ref[1]
                cands = [cand for cand in header_object_candidates(self.current_level().part(self.part_var.get()).header) if cand.index == slot]
                if not cands:
                    self.property_title_var.set("Selected artifact no longer exists")
                    self._clear_property_values()
                    self._layout_property_panel()
                    return
                cand = cands[0]
                self.property_title_var.set(f"Artifact {slot}")
                self.property_x_var.set(str(cand.x_raw))
                self.property_y_var.set(str(cand.y_raw))
                self.property_len_var.set(str(cand.room_plus_one - 1))
                self.property_code_var.set(f"{slot}")
                self.property_note_var.set("Header artifact slot. Room is zero-based here.")
        else:
            self.property_title_var.set(kind.replace("_", " "))
            self._clear_property_values()
            self._layout_property_panel()

    def apply_selected_properties(self) -> None:
        ref = self.editor_selected_ref
        if ref is None:
            self.status.set("Select a CV/platform/belt object first.")
            return
        room = self.current_room()
        kind = ref[0]
        try:
            if kind == "conveyor":
                cv = self._cv_from_ref(room, ref)
                if cv is None:
                    self.status.set("Selected CV no longer exists.")
                    return
                x_cell = max(0, min(ROOM_COLUMNS - 1, self._parse_int_property(self.property_x_var.get(), default=cv.start_x)))
                y_cell = max(0, min(ROOM_ROWS - 1, self._parse_int_property(self.property_y_var.get(), default=cv.cell_y)))
                length = max(1, min(ROOM_COLUMNS - x_cell, self._parse_int_property(self.property_len_var.get(), default=cv.length)))
                code = self._parse_int_property(self.property_code_var.get(), default=max(0, length - 2)) & 0xFF
                props = self._parse_int_property(self.property_props_var.get(), default=cv.props) & 0xFF
                x_raw, y_raw, auto_code = cv_geometry_to_raw(x_cell, y_cell, length)
                # Empty code means derive it from length; non-empty code lets the
                # user preserve or investigate raw game values.
                if not self.property_code_var.get().strip():
                    code = auto_code
                # Move the matching physics footprint together with the CV.
                old_tile = 0x1F if any(room.get(x, y) == 0x1F for x, y in cv.cells if 0 <= x < ROOM_COLUMNS and 0 <= y < ROOM_ROWS) else self._belt_tile_code()
                for x, y in cv.cells:
                    if 0 <= x < ROOM_COLUMNS and 0 <= y < ROOM_ROWS and room.get(x, y) in {0x0F, 0x1F}:
                        room.set(x, y, 0)
                set_conveyor_visual_record(room, cv.index, x_raw=x_raw, y=y_raw, code=code, props=props)
                self._write_belt_footprint(room, start_x=x_cell, y=y_cell, length=length, tile_code=old_tile)
                self.status.set(f"Updated CV{cv.index}: x={x_cell} y={y_cell} len={length} code={code:02X} props={props:02X}")
            elif kind == "platform":
                slot = ref[1]
                platforms = [p for p in parse_platform_triplets(room) if p.index == slot]
                old_flags = platforms[0].flags if platforms else 0x40
                old_x = platforms[0].x_raw if platforms else 0
                old_y = platforms[0].y if platforms else 0
                flags = self._parse_int_property(self.property_code_var.get(), default=old_flags) & 0xFF
                x_raw = self._parse_int_property(self.property_x_var.get(), default=old_x) & 0xFF
                y_raw = self._parse_int_property(self.property_y_var.get(), default=old_y) & 0xFF
                requested_slot = self.property_len_var.get().strip()
                if requested_slot and requested_slot.upper() not in {f"P{slot}", str(slot)}:
                    self.status.set(f"P{slot} target slot is fixed. Edit control target lists instead; position/flags were not changed.")
                    self.redraw_editor_room()
                    return
                old_platforms = [p for p in parse_platform_triplets(room) if p.index == slot]
                if old_platforms:
                    self._clear_platform_footprint(room, old_platforms[0])
                room.set_trailing_bytes(slot * PLATFORM_TRIPLET_SIZE, [flags, x_raw, y_raw])
                new_platforms = [p for p in parse_platform_triplets(room) if p.index == slot]
                if new_platforms:
                    self._write_platform_footprint(room, new_platforms[0])
                self.status.set(f"Updated P{slot}: flags={flags:02X} x={x_raw} y={y_raw}")
            elif kind == "symbol":
                idx = ref[1]
                table = section_a_symbol_table(room)
                entry = None if table is None or idx is None else next((e for e in table.entries if e.index == idx), None)
                if entry is None:
                    self.status.set("Selected symbol no longer exists.")
                    return
                x_raw = self._parse_int_property(self.property_x_var.get(), default=entry.x_raw) & 0xFF
                y_raw = self._parse_int_property(self.property_y_var.get(), default=entry.y) & 0xFF
                symbol_id = max(1, min(7, self._parse_int_property(self.property_len_var.get(), default=(entry.code & 0x07) + 1)))
                code = (entry.code & ~0x07) | ((symbol_id - 1) & 0x07)
                target_room_index = self._parse_room_property(default=room.index)
                if target_room_index != room.index:
                    target_room = self.current_level().part(self.part_var.get()).room(target_room_index)
                    new_index = add_section_a_symbol_entry(target_room, x_raw=x_raw, y=y_raw, code=code)
                    delete_section_a_symbol_entry(room, entry.index)
                    self.editor_selected_ref = ("symbol", new_index)
                    self.status.set(f"Moved symbol to room {target_room_index:02d}: S{symbol_id} x={x_raw * 2} y={y_raw}")
                    self._set_dirty()
                    self.set_room(target_room_index)
                    self.editor_selected_ref = ("symbol", new_index)
                    self.redraw_editor_room()
                    return
                set_section_a_symbol_entry(room, entry.index, x_raw=x_raw, y=y_raw, code=code)
                self.status.set(f"Updated symbol M{entry.index}: S{symbol_id} x={x_raw * 2} y={y_raw}")
            elif kind in {"green_block", "green_block_alt"}:
                idx = ref[1]
                _off, records = record12_green_block_records(room)
                if idx is None or not 0 <= idx < len(records):
                    self.status.set("Selected green block no longer exists.")
                    return
                rec = bytearray(records[idx])
                dx = self._parse_int_property(self.property_x_var.get(), default=self._green_block_xy_from_raw(rec[0], rec[1])[0])
                dy = self._parse_int_property(self.property_y_var.get(), default=self._green_block_xy_from_raw(rec[0], rec[1])[1])
                ax = self._parse_int_property(self.property_len_var.get(), default=self._green_block_xy_from_raw(rec[2], rec[3])[0])
                ay = self._parse_int_property(self.property_code_var.get(), default=self._green_block_xy_from_raw(rec[2], rec[3])[1])
                old_rec = bytes(rec)
                rec[0], rec[1] = self._green_block_raw_from_xy(dx, dy)
                rec[2], rec[3] = self._green_block_raw_from_xy(ax, ay)
                seq = self._parse_symbol_sequence_text(self.property_props_var.get(), self._record12_sequence(rec))
                self._write_record12_sequence(rec, seq)
                target_room_index = self._parse_room_property(default=room.index)
                if target_room_index != room.index:
                    target_room = self.current_level().part(self.part_var.get()).room(target_room_index)
                    self._clear_green_block_footprint(room, old_rec, alternate=False)
                    new_index = add_record12_green_block(target_room, bytes(rec))
                    self._rewrite_green_block_footprints(target_room, rec)
                    delete_record12_green_block(room, idx)
                    self.status.set(f"Moved green block {idx} to room {target_room_index:02d} as {new_index}: sequence={','.join(map(str, seq)) or '-'}")
                    self._set_dirty()
                    self.set_room(target_room_index)
                    self.editor_selected_ref = ("green_block", new_index)
                    self.redraw_editor_room()
                    return
                self._clear_green_block_footprint(room, old_rec, alternate=False)
                self._rewrite_green_block_footprints(room, rec)
                set_record12_green_block(room, idx, bytes(rec))
                self.status.set(f"Updated green block {idx}: sequence={','.join(map(str, seq)) or '-'}")
            elif kind == "control":
                idx = ref[1]
                cmds = [cmd for cmd in control_commands(room) if cmd.record.index == idx]
                if not cmds:
                    self.status.set("Selected control no longer exists.")
                    return
                cmd = cmds[0]
                body = bytearray(cmd.body)
                raw_text = self.property_props_var.get().strip()
                # If the user edited the raw body, trust it but keep the same length.
                raw_candidate = bytes.fromhex(raw_text) if raw_text else bytes(body)
                if len(raw_candidate) == len(body) and raw_candidate != bytes(body):
                    body[:] = raw_candidate
                if len(body) >= 1 and self.property_code_var.get().strip():
                    body[0] = self._parse_int_property(self.property_code_var.get(), default=body[0]) & 0xFF
                if len(body) >= 2 and self.property_x_var.get().strip():
                    body[1] = self._parse_int_property(self.property_x_var.get(), default=body[1]) & 0xFF
                if len(body) >= 3 and self.property_y_var.get().strip():
                    body[2] = self._parse_int_property(self.property_y_var.get(), default=body[2]) & 0xFF
                if self.property_len_var.get().strip():
                    current_targets = [target.raw for target in control_targets(cmd)]
                    targets = self._parse_control_targets(self.property_len_var.get(), current=current_targets)
                    self._rewrite_control_targets(body, targets)
                set_control_command_body(room, idx, bytes(body), allow_resize=True)
                new_targets = [decode_control_target(value).label for value in body[4:]]
                self.status.set(f"Updated C{idx}: targets={','.join(new_targets)} body={bytes(body).hex(' ')}")
            elif kind == "room_links":
                part = self.current_level().part(self.part_var.get())
                def parse_room_link(text: str, current_stored: int) -> int:
                    raw = text.strip()
                    if raw in {"", "-", "none", "None", "NONE"}:
                        return -1
                    return max(0, min(ROOM_COUNT - 1, self._parse_int_property(raw, default=max(0, current_stored - 1))))
                links = transition_links_for_room(part, room.index)
                cur_left = 0 if links is None else links.left
                cur_right = 0 if links is None else links.right
                cur_up = 0 if links is None else links.up
                cur_down = 0 if links is None else links.down
                part.set_room_transition_links(
                    room.index,
                    left=parse_room_link(self.property_x_var.get(), cur_left),
                    right=parse_room_link(self.property_y_var.get(), cur_right),
                    up=parse_room_link(self.property_len_var.get(), cur_up),
                    down=parse_room_link(self.property_code_var.get(), cur_down),
                )
                self.status.set(f"Updated room {room.index:02d} links.")
            elif kind == "decor":
                entry = self._decor_from_ref(room, ref)
                if entry is None:
                    self.status.set("Selected decor decal no longer exists.")
                    return
                x_raw = self._parse_int_property(self.property_x_var.get(), default=entry.x_raw) & 0xFF
                y_raw = self._parse_int_property(self.property_y_var.get(), default=entry.y) & 0xFF
                code = self._parse_int_property(self.property_len_var.get(), default=entry.code) & 0xFF
                flip = self.property_decor_flip_var.get()
                code = (code | 0x40) if flip else (code & ~0x40)
                target_room_index = self._parse_room_property(default=room.index)
                if target_room_index != room.index:
                    target_room = self.current_level().part(self.part_var.get()).room(target_room_index)
                    new_index = add_visual_compact3_entry(target_room, x_raw=x_raw, y=y_raw, code=code)
                    delete_visual_compact3_entry(room, entry.index)
                    self.decor_code_var.set(f"{code:02X}")
                    self.status.set(f"Moved V{entry.index} to room {target_room_index:02d} as V{new_index}: code={code:02X} flip={'yes' if code & 0x40 else 'no'}")
                    self._set_dirty()
                    self.set_room(target_room_index)
                    self.editor_selected_ref = ("decor", new_index)
                    self.redraw_editor_room()
                    return
                set_visual_compact3_entry(room, entry.index, x_raw=x_raw, y=y_raw, code=code)
                self.decor_code_var.set(f"{code:02X}")
                self.status.set(f"Updated V{entry.index}: code={code:02X} flip={'yes' if code & 0x40 else 'no'} x={x_raw} y={y_raw}")
            elif kind == "animated_decor":
                record = self._animated_decor_from_ref(room, ref)
                if record is None:
                    self.status.set("Selected animated decor no longer exists.")
                    return
                x_raw = self._parse_int_property(self.property_x_var.get(), default=record.x_raw) & 0xFF
                y_raw = self._parse_int_property(self.property_y_var.get(), default=record.y) & 0xFF
                phase = self._parse_int_property(self.property_len_var.get(), default=record.phase) & 0xFF
                sequence = self._parse_animated_sequence_text(self.property_props_var.get(), record.sequence_raw)
                target_room_index = self._parse_room_property(default=room.index)
                if target_room_index != room.index:
                    target_room = self.current_level().part(self.part_var.get()).room(target_room_index)
                    new_index = add_animated_decor_record(target_room, phase=phase, x_raw=x_raw, y=y_raw, sequence=sequence)
                    delete_animated_decor_record(room, record.index)
                    self.status.set(f"Moved AD{record.index} to room {target_room_index:02d} as AD{new_index}.")
                    self._set_dirty()
                    self.set_room(target_room_index)
                    self.editor_selected_ref = ("animated_decor", new_index)
                    self.redraw_editor_room()
                    return
                set_animated_decor_record(room, record.index, phase=phase, x_raw=x_raw, y=y_raw, sequence=sequence)
                self.status.set(f"Updated AD{record.index}: phase={phase} x={x_raw} y={y_raw} frames={self._format_animated_sequence(sequence)}")
            elif kind == "actor":
                idx = ref[1]
                part = self.current_level().part(self.part_var.get())
                actor = self._actor_by_index(part, int(idx))
                if actor is None:
                    self.status.set("Selected actor no longer exists.")
                    return
                x_new = self._parse_int_property(self.property_x_var.get(), default=actor.x) & 0xFFFF
                y_new = self._parse_int_property(self.property_y_var.get(), default=actor.y) & 0xFFFF
                frame_variant = actor.frame_variant
                hidden = actor.hidden
                if actor.frame_variant in {0, 1}:
                    frame_variant = 1 if self.property_actor_facing_var.get() else 0
                elif self.property_len_var.get().strip():
                    frame_variant = self._parse_int_property(self.property_len_var.get(), default=actor.frame_variant) & 0xFF
                if actor.hidden in {0, 1}:
                    hidden = 1 if self.property_actor_hidden_var.get() else 0
                elif self.property_props_var.get().strip():
                    hidden = self._parse_int_property(self.property_props_var.get(), default=actor.hidden) & 0xFF
                target_room_index = self._parse_room_property(default=actor.room_index)
                set_actor_record_placement(part, actor.index, room_index=target_room_index, x=x_new, y=y_new)
                set_actor_record_flags(part, actor.index, frame_variant=frame_variant, hidden=hidden)
                self.actor_script_share_source_index = actor.index
                self.status.set(f"Updated A{actor.index}: room={target_room_index:02d} x={x_new} y={y_new} variant={frame_variant:02X} hidden={hidden:02X}")
                if target_room_index != room.index:
                    self._set_dirty()
                    self.set_room(target_room_index)
                    self.editor_selected_ref = ("actor", actor.index)
                    self.redraw_editor_room()
                    return
            elif kind == "exit_door":
                part = self.current_level().part(self.part_var.get())
                x_raw = self._parse_int_property(self.property_x_var.get(), default=0) & 0xFF
                y_raw = self._parse_int_property(self.property_y_var.get(), default=0) & 0xFF
                room_index = max(0, min(ROOM_COUNT - 1, self._parse_int_property(self.property_len_var.get(), default=room.index)))
                part.set_exit_door(room_index, x_raw, y_raw)
                self.status.set(f"Updated exit door: room={room_index} x={x_raw} y={y_raw}")
            elif kind == "player_start":
                part = self.current_level().part(self.part_var.get())
                x_raw = self._parse_int_property(self.property_x_var.get(), default=0) & 0xFF
                y_raw = self._parse_int_property(self.property_y_var.get(), default=0) & 0xFF
                part.set_player_start(x_raw, y_raw)
                self.status.set(f"Updated player start: room=00 x={x_raw} y={y_raw}")
            elif kind == "artifact":
                slot = ref[1]
                part = self.current_level().part(self.part_var.get())
                x_raw = self._parse_int_property(self.property_x_var.get(), default=0) & 0xFF
                y_raw = self._parse_int_property(self.property_y_var.get(), default=0) & 0xFF
                room_index = max(0, min(ROOM_COUNT - 1, self._parse_int_property(self.property_len_var.get(), default=room.index)))
                part.set_artifact_slot(slot, room_index, x_raw, y_raw)
                self.status.set(f"Updated artifact {slot}: room={room_index} x={x_raw} y={y_raw}")
            elif kind == "known_pickup":
                part = self.current_level().part(self.part_var.get())
                x_raw = self._parse_int_property(self.property_x_var.get(), default=0) & 0xFF
                y_raw = self._parse_int_property(self.property_y_var.get(), default=0) & 0xFF
                target_room_index = self._parse_room_property(default=room.index)
                if target_room_index != room.index:
                    clear_part_apple_marker(part, room.index)
                    set_part_apple_marker(part, target_room_index, x_raw=x_raw, y=y_raw)
                    self.status.set(f"Moved apple to room {target_room_index:02d}: x={x_raw * 2} y={y_raw}")
                    self._set_dirty()
                    self.set_room(target_room_index)
                    self.editor_selected_ref = ("known_pickup", 0)
                    self.redraw_editor_room()
                    return
                set_part_apple_marker(part, room.index, x_raw=x_raw, y=y_raw)
                self.status.set(f"Updated apple: x={x_raw * 2} y={y_raw}")
            else:
                self.status.set("Properties are editable for CV belts, platforms, controls and header objects for now.")
                return
        except Exception as exc:
            self.status.set(f"Invalid properties: {exc}")
            return
        self._set_dirty()
        self.redraw_room()
        self.redraw_editor_object_palette()
        self.redraw_decor_palette()
        self.redraw_actor_palette()
        self.refresh_actor_scripting_tab()
