from __future__ import annotations

from .common import (
    ACTOR_TEMPLATE_BY_KEY,
    ACTOR_TEMPLATE_SPECS,
    OVERLAY_OPTION_SPECS,
    RenderOptions,
    actor_records_for_room,
    tk,
    ttk,
)


class EditorTabMixin:
    def _build_editor_tab(self, editor_tab: ttk.Frame) -> None:
        main = ttk.PanedWindow(editor_tab, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left, weight=4)
        main.add(right, weight=1)

        self.editor_canvas = tk.Canvas(left, bg="black")
        self.editor_canvas.pack(fill=tk.BOTH, expand=True)
        self.editor_canvas.bind("<Button-1>", self.editor_click)
        self.editor_canvas.bind("<B1-Motion>", self.editor_drag)
        self.editor_canvas.bind("<Button-3>", self.editor_pick_tile)
        self.editor_canvas.bind("<Delete>", self.delete_selected_editor_object)
        self.editor_canvas.bind("<BackSpace>", self.delete_selected_editor_object)

        tools_row = ttk.Frame(right)
        tools_row.pack(fill=tk.X, padx=6, pady=(6, 2))
        ttk.Label(tools_row, text="Editor").pack(side=tk.LEFT)
        ttk.Label(tools_row, textvariable=self.palette_selection_var, wraplength=220, justify=tk.RIGHT).pack(side=tk.RIGHT)

        view_row = ttk.Frame(right)
        view_row.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Checkbutton(view_row, text="Overlay", variable=self.editor_overlay_var, command=self.redraw_editor_room).pack(side=tk.LEFT)

        action_row = ttk.Frame(right)
        action_row.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Button(action_row, text="Select / move", command=self.select_selection_mode).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(action_row, text="Delete selected", command=self.delete_selected_editor_object).pack(side=tk.LEFT, padx=(6, 0))

        self.editor_palettes = ttk.Notebook(right)
        self.editor_palettes.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        tile_tab = ttk.Frame(self.editor_palettes)
        object_tab = ttk.Frame(self.editor_palettes)
        decor_tab = ttk.Frame(self.editor_palettes)
        room_data_tab = ttk.Frame(self.editor_palettes)
        self.editor_palettes.add(tile_tab, text="Tile brush")
        self.editor_palettes.add(object_tab, text="Objects")
        self.editor_palettes.add(decor_tab, text="Decor")
        self.editor_palettes.add(room_data_tab, text="Room data")
        self.editor_palettes.bind("<<NotebookTabChanged>>", self.on_editor_palette_tab_changed)

        tile_settings_host = ttk.Frame(tile_tab)
        tile_settings_host.pack(fill=tk.X, padx=6, pady=(6, 0))
        mechanics_settings_host = ttk.Frame(object_tab)
        mechanics_settings_host.pack(fill=tk.X, padx=6, pady=(6, 0))

        self.select_settings_frame = ttk.LabelFrame(mechanics_settings_host, text="Selection")
        ttk.Label(
            self.select_settings_frame,
            text="Select, move and delete existing room objects. Tile painting is handled separately by Tile brush.",
            wraplength=260,
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(self.select_settings_frame, textvariable=self.editor_info, justify=tk.LEFT).pack(fill=tk.X, padx=6, pady=(0, 6))

        self.tile_settings_frame = ttk.LabelFrame(tile_settings_host, text="Tile brush")
        tile_row = ttk.Frame(self.tile_settings_frame)
        tile_row.pack(fill=tk.X, padx=6, pady=(6, 6))
        ttk.Label(tile_row, text="Tile").pack(side=tk.LEFT)
        ttk.Entry(tile_row, textvariable=self.tile_value_var, width=6).pack(side=tk.LEFT, padx=(4, 0))
        brush_row = ttk.Frame(self.tile_settings_frame)
        brush_row.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Label(brush_row, text="Brush").pack(side=tk.LEFT)
        ttk.Spinbox(brush_row, from_=1, to=5, textvariable=self.brush_size_var, width=4).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(brush_row, text="Mode").pack(side=tk.LEFT, padx=(10, 0))
        tile_mode = ttk.Combobox(
            brush_row,
            state="readonly",
            textvariable=self.tile_brush_mode_var,
            values=["exact", "auto solid", "auto rope"],
            width=10,
        )
        tile_mode.pack(side=tk.LEFT, padx=(4, 0))
        tile_mode.bind("<<ComboboxSelected>>", lambda _event: self.on_palette_setting_changed())
        ttk.Label(self.tile_settings_frame, text="Auto modes retile nearby known terrain cells. Belts stay in the Belt tool so 0F/1F physics cannot be painted without a CV visual object.", wraplength=260, justify=tk.LEFT).pack(fill=tk.X, padx=6, pady=(0, 6))

        self.belt_settings_frame = ttk.LabelFrame(mechanics_settings_host, text="Belt placement")
        belt_row = ttk.Frame(self.belt_settings_frame)
        belt_row.pack(fill=tk.X, padx=6, pady=(6, 6))
        ttk.Label(belt_row, text="Kind").pack(side=tk.LEFT)
        belt_kind = ttk.Combobox(
            belt_row,
            state="readonly",
            textvariable=self.belt_kind_var,
            values=["grey", "teal"],
            width=6,
        )
        belt_kind.pack(side=tk.LEFT, padx=(4, 0))
        belt_kind.bind("<<ComboboxSelected>>", lambda _event: self.on_palette_setting_changed())
        ttk.Label(belt_row, text="Len").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Spinbox(belt_row, from_=1, to=38, textvariable=self.belt_length_var, width=4, command=self.redraw_editor_room).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(self.belt_settings_frame, text="Belt = physics tile run + CV visual object. Select the CV afterwards to edit props/trigger links.", wraplength=260, justify=tk.LEFT).pack(fill=tk.X, padx=6, pady=(0, 6))

        self.platform_settings_frame = ttk.LabelFrame(mechanics_settings_host, text="Platform placement")
        platform_row = ttk.Frame(self.platform_settings_frame)
        platform_row.pack(fill=tk.X, padx=6, pady=(6, 6))
        ttk.Label(platform_row, text="Move").pack(side=tk.LEFT)
        platform_kind = ttk.Combobox(
            platform_row,
            state="readonly",
            textvariable=self.platform_kind_var,
            values=["horizontal_left", "horizontal_right", "vertical_down", "vertical_up"],
            width=16,
        )
        platform_kind.pack(side=tk.LEFT, padx=(4, 0))
        platform_kind.bind("<<ComboboxSelected>>", lambda _event: self.on_palette_setting_changed())
        ttk.Label(self.platform_settings_frame, text="Platform = runtime P slot + invisible 07 support footprint. Placement uses the first free P slot.", wraplength=260, justify=tk.LEFT).pack(fill=tk.X, padx=6, pady=(0, 6))

        self.control_settings_frame = ttk.LabelFrame(mechanics_settings_host, text="New control / trigger")
        ttk.Label(self.control_settings_frame, text="Targets").grid(row=0, column=0, sticky="e", padx=(6, 2), pady=(6, 2))
        ttk.Entry(self.control_settings_frame, textvariable=self.control_targets_var, width=22).grid(row=0, column=1, sticky="ew", padx=(0, 6), pady=(6, 2))
        ttk.Label(self.control_settings_frame, text="State").grid(row=1, column=0, sticky="e", padx=(6, 2), pady=2)
        ttk.Entry(self.control_settings_frame, textvariable=self.control_state_var, width=6).grid(row=1, column=1, sticky="w", padx=(0, 6), pady=2)
        self.control_settings_frame.columnconfigure(1, weight=1)
        ttk.Label(
            self.control_settings_frame,
            text="Targets use typed ids: P0 = platform, CV0 = belt, R0 = reflector. One control can target multiple items, e.g. P1,P2,R0,R2.",
            wraplength=260,
            justify=tk.LEFT,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 6))

        self.object_settings_frame = ttk.LabelFrame(mechanics_settings_host, text="Object placement")
        ttk.Label(self.object_settings_frame, text="Choose an object from this palette to enter the placement tool. Use Select / move to edit existing objects; empty clicks never place while Select / move is active.", wraplength=260, justify=tk.LEFT).pack(fill=tk.X, padx=6, pady=6)

        tile_frame = ttk.Frame(tile_tab)
        tile_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(6, 0))
        self.tile_palette_canvas = tk.Canvas(tile_frame, bg="#202020", width=260)
        tile_scroll = ttk.Scrollbar(tile_frame, orient=tk.VERTICAL, command=self.tile_palette_canvas.yview)
        self.tile_palette_canvas.configure(yscrollcommand=tile_scroll.set)
        self.tile_palette_canvas.grid(row=0, column=0, sticky="nsew")
        tile_scroll.grid(row=0, column=1, sticky="ns")
        tile_frame.rowconfigure(0, weight=1)
        tile_frame.columnconfigure(0, weight=1)
        self.tile_palette_canvas.bind("<Button-1>", self.tile_palette_click)

        object_frame = ttk.Frame(object_tab)
        object_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(6, 0))
        self.object_palette_canvas = tk.Canvas(object_frame, bg="#202020", width=260)
        object_scroll = ttk.Scrollbar(object_frame, orient=tk.VERTICAL, command=self.object_palette_canvas.yview)
        self.object_palette_canvas.configure(yscrollcommand=object_scroll.set)
        self.object_palette_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        object_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        object_frame.columnconfigure(0, weight=1)
        self.object_palette_canvas.bind("<Button-1>", self.object_palette_click)

        decor_settings = ttk.Frame(decor_tab)
        decor_settings.pack(fill=tk.X, padx=6, pady=(6, 4))
        ttk.Label(decor_settings, text="Code").pack(side=tk.LEFT)
        ttk.Entry(decor_settings, textvariable=self.decor_code_var, width=6).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(
            decor_tab,
            text="Theme decor from the room visual compact3 table. Choose a decal, click to place it, or select an existing V handle to move/delete it.",
            wraplength=260,
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=6, pady=(0, 4))
        decor_frame = ttk.Frame(decor_tab)
        decor_frame.pack(fill=tk.BOTH, expand=True)
        self.decor_palette_canvas = tk.Canvas(decor_frame, bg="#202020", width=260)
        decor_scroll = ttk.Scrollbar(decor_frame, orient=tk.VERTICAL, command=self.decor_palette_canvas.yview)
        self.decor_palette_canvas.configure(yscrollcommand=decor_scroll.set)
        self.decor_palette_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        decor_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.decor_palette_canvas.bind("<Button-1>", self.decor_palette_click)

        self.actor_settings_frame = ttk.LabelFrame(mechanics_settings_host, text="New actor behavior")
        ttk.Label(
            self.actor_settings_frame,
            text="Actors are normal placeable objects here. Their behavior is an entry pointer into the shared Script space.",
            wraplength=260,
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=6, pady=(6, 4))
        ttk.Radiobutton(self.actor_settings_frame, text="New blank/wait script", variable=self.actor_script_mode_var, value="new").pack(anchor="w", padx=6, pady=(0, 0))
        ttk.Radiobutton(self.actor_settings_frame, text="Share selected actor's script_pc", variable=self.actor_script_mode_var, value="share_selected").pack(anchor="w", padx=6)
        addr_row = ttk.Frame(self.actor_settings_frame)
        addr_row.pack(fill=tk.X, padx=6, pady=(0, 4))
        ttk.Radiobutton(addr_row, text="Use address", variable=self.actor_script_mode_var, value="address").pack(side=tk.LEFT)
        ttk.Label(addr_row, text="start").pack(side=tk.LEFT, padx=(6, 2))
        ttk.Entry(addr_row, textvariable=self.actor_script_address_var, width=8).pack(side=tk.LEFT)
        ttk.Label(addr_row, text="hex").pack(side=tk.LEFT, padx=(2, 0))
        ttk.Label(addr_row, text="reset").pack(side=tk.LEFT, padx=(8, 2))
        ttk.Entry(addr_row, textvariable=self.actor_script_reset_address_var, width=8).pack(side=tk.LEFT)
        ttk.Label(addr_row, text="hex").pack(side=tk.LEFT, padx=(2, 0))

        self.room_data_settings_frame = ttk.LabelFrame(right, text="Room data")
        ttk.Label(
            self.room_data_settings_frame,
            text="Room data contains metadata without a physical scene object, such as left/right/up/down room links.",
            wraplength=260,
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=6, pady=(6, 4))
        ttk.Button(self.room_data_settings_frame, text="Edit current room links", command=self.select_room_links_mode).pack(fill=tk.X, padx=6, pady=(0, 6))

        ttk.Label(
            room_data_tab,
            text="Room parameters / data. These are per-room fields, not objects in the scene.",
            wraplength=260,
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=6, pady=(6, 4))
        ttk.Button(room_data_tab, text="Edit current room links", command=self.select_room_links_mode).pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Label(room_data_tab, text="Select this tab to edit room links in the properties panel.", wraplength=260, justify=tk.LEFT).pack(fill=tk.X, padx=6, pady=(0, 6))

        prop_box = ttk.LabelFrame(right, text="Selected object properties")
        prop_box.pack(fill=tk.X, padx=6, pady=(0, 6))
        self.property_title_label = ttk.Label(prop_box, textvariable=self.property_title_var, wraplength=260, justify=tk.LEFT)
        self.property_title_label.grid(row=0, column=0, columnspan=4, sticky="w", padx=6, pady=(4, 2))
        self.property_rows = [
            (
                ttk.Label(prop_box, textvariable=self.property_label_x_var),
                ttk.Entry(prop_box, textvariable=self.property_x_var, width=8),
                ttk.Label(prop_box, textvariable=self.property_label_y_var),
                ttk.Entry(prop_box, textvariable=self.property_y_var, width=8),
            ),
            (
                ttk.Label(prop_box, textvariable=self.property_label_len_var),
                ttk.Entry(prop_box, textvariable=self.property_len_var, width=8),
                ttk.Label(prop_box, textvariable=self.property_label_code_var),
                ttk.Entry(prop_box, textvariable=self.property_code_var, width=8),
            ),
            (
                ttk.Label(prop_box, textvariable=self.property_label_props_var),
                ttk.Entry(prop_box, textvariable=self.property_props_var, width=18),
                None,
                None,
            ),
            (
                ttk.Label(prop_box, textvariable=self.property_label_room_var),
                ttk.Entry(prop_box, textvariable=self.property_room_var, width=8),
                None,
                None,
            ),
        ]
        self.property_actor_bool_row = ttk.Frame(prop_box)
        self.property_actor_facing_check = ttk.Checkbutton(self.property_actor_bool_row, text="Facing variant", variable=self.property_actor_facing_var)
        self.property_actor_hidden_check = ttk.Checkbutton(self.property_actor_bool_row, text="Hidden", variable=self.property_actor_hidden_var)
        self.property_apply_button = ttk.Button(prop_box, text="Apply", command=self.apply_selected_properties)
        self.property_note_label = ttk.Label(prop_box, textvariable=self.property_note_var, wraplength=260, justify=tk.LEFT)
        prop_box.columnconfigure(3, weight=1)

    def on_editor_tool_changed(self) -> None:
        self.refresh_placeable_settings()
        self.redraw_editor_room()

    def on_editor_palette_tab_changed(self, _event=None) -> None:
        if not hasattr(self, "editor_palettes"):
            return
        selected = self.editor_palettes.index(self.editor_palettes.select())
        if selected == 0:
            if self.editor_tool_var.get() != "terrain":
                self.select_tile_brush_mode()
        elif selected == 1:
            if self.editor_tool_var.get() not in {"select", "belt", "platform", "object", "actor"}:
                self.select_selection_mode()
        elif selected == 2:
            if self.editor_tool_var.get() != "decor":
                self.select_decor_mode()
        elif selected == 3:
            self.select_room_links_mode()

    def select_tile_brush_mode(self) -> None:
        self.editor_tool_var.set("terrain")
        self.editor_selected_ref = None
        self.editor_drag_offset = None
        if hasattr(self, "editor_palettes"):
            self.editor_palettes.select(0)
        self.refresh_placeable_settings()
        self.redraw_tile_palette()
        self.redraw_editor_room()

    def select_selection_mode(self) -> None:
        self.editor_tool_var.set("select")
        self.palette_selection_var.set("Selection mode")
        if hasattr(self, "editor_palettes"):
            self.editor_palettes.select(1)
        self.refresh_placeable_settings()
        self.redraw_editor_room()

    def select_decor_mode(self) -> None:
        self.editor_tool_var.set("decor")
        self.editor_selected_ref = None
        self.editor_drag_offset = None
        if hasattr(self, "editor_palettes"):
            self.editor_palettes.select(2)
        self.refresh_placeable_settings()
        self.redraw_decor_palette()
        self.redraw_editor_room()

    def select_actor_mode(self) -> None:
        self.editor_tool_var.set("actor")
        self.editor_selected_ref = None
        self.editor_drag_offset = None
        if hasattr(self, "editor_palettes"):
            self.editor_palettes.select(1)
        self.refresh_placeable_settings()
        self.redraw_editor_object_palette()
        self.redraw_editor_room()

    def select_room_links_mode(self) -> None:
        self.editor_tool_var.set("room_data")
        self.editor_selected_ref = ("room_links", self.current_room().index)
        self.editor_drag_offset = None
        if hasattr(self, "editor_palettes"):
            try:
                if self.editor_palettes.index(self.editor_palettes.select()) != 3:
                    self.editor_palettes.select(3)
            except tk.TclError:
                self.editor_palettes.select(3)
        self.refresh_placeable_settings()
        self.refresh_property_panel()
        self.redraw_editor_room()

    def refresh_placeable_settings(self) -> None:
        if not hasattr(self, "select_settings_frame"):
            return
        frames = [
            self.select_settings_frame,
            self.tile_settings_frame,
            self.belt_settings_frame,
            self.platform_settings_frame,
            self.control_settings_frame,
            self.object_settings_frame,
        ]
        if hasattr(self, "actor_settings_frame"):
            frames.append(self.actor_settings_frame)
        for frame in frames:
            frame.pack_forget()
        tool = self.editor_tool_var.get()
        if tool == "terrain":
            self.tile_settings_frame.pack(fill=tk.X)
            self.palette_selection_var.set(f"Tile brush: {self.tile_value_var.get().upper()} ({self._tile_brush_mode()})")
        elif tool == "belt":
            self.belt_settings_frame.pack(fill=tk.X)
            self.palette_selection_var.set(f"Object placement: {self.belt_kind_var.get()} belt, length {self._belt_length()}")
        elif tool == "platform":
            self.platform_settings_frame.pack(fill=tk.X)
            self.palette_selection_var.set(f"Object placement: platform {self.platform_kind_var.get().replace('_', ' ')}")
        elif tool == "object":
            obj = self.editor_object_var.get().replace("_", " ")
            if self.editor_object_var.get() in {"ceiling_button", "floor_switch", "jello"}:
                self.control_settings_frame.pack(fill=tk.X)
            else:
                self.object_settings_frame.pack(fill=tk.X)
            self.palette_selection_var.set(f"Object placement: {obj}")
        elif tool == "room_data":
            self.palette_selection_var.set(f"Room data: room {self.current_room().index:02d} links")
        elif tool == "decor":
            self.palette_selection_var.set(f"Decor decals: code {self.decor_code_var.get().upper()}")
        elif tool == "actor":
            self.actor_settings_frame.pack(fill=tk.X)
            spec = ACTOR_TEMPLATE_BY_KEY.get(self.actor_template_var.get(), ACTOR_TEMPLATE_SPECS[0])
            self.palette_selection_var.set(f"Object placement: actor {spec.label}")
        else:
            self.select_settings_frame.pack(fill=tk.X)
            self.palette_selection_var.set("Object selection")

    def on_palette_setting_changed(self) -> None:
        self.refresh_placeable_settings()
        self.redraw_editor_object_palette()
        self.redraw_objects_atlas()
        self.redraw_editor_room()

    def apply_overlay_preset(self, preset: str) -> None:
        if preset not in {"minimal", "logic", "debug"}:
            return
        for spec in OVERLAY_OPTION_SPECS:
            getattr(self, spec.var_name).set(getattr(spec, preset))
        self.redraw_room()

    def room_labels(self) -> list[str]:
        level = self.project.levels[self.level_var.get()]
        part = level.part(self.part_var.get())
        return [f"{room.index:02d} {room.quality_label}" for room in part.rooms]

    def refresh_room_labels(self) -> None:
        self.room_combo.configure(values=self.room_labels())
        self.room_combo.current(self.room_var.get())

    def options(self, zoom: int | None = None) -> RenderOptions:
        return RenderOptions(
            mode=self.mode_var.get(),
            zoom=self.zoom_var.get() if zoom is None else zoom,
            grid=False,
            part_index=self.part_var.get(),
        )

    def current_level(self):
        return self.project.levels[self.level_var.get()]

    def current_image(self, zoom: int | None = None):
        return self.project.renderer.render_room(self.current_level(), self.room_var.get(), self.options(zoom))

    def current_room(self):
        return self.current_level().part(self.part_var.get()).room(self.room_var.get())

    def _current_room_actors(self):
        return actor_records_for_room(self.current_level().part(self.part_var.get()), self.current_room().index)

