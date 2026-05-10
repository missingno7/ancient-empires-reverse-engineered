from __future__ import annotations

from ..ui.common import (
    ACTOR_TEMPLATE_SPECS,
    AncientEmpiresProject,
    AudioItem,
    DEFAULT_PREVIEW_SPEED,
    DEFAULT_SIMULATION_TICK_HZ,
    DIFFICULTY_LABELS,
    GM_PROGRAM_NAMES,
    Instruction,
    OVERLAY_OPTION_SPECS,
    RoomSimulation,
    tk,
    tkfont,
    ttk,
)
from ..ui.actor_scripting_tab import ActorScriptingTabMixin
from ..ui.audio_tab import AudioTabMixin
from ..ui.editor_canvas import EditorCanvasMixin
from ..ui.editor_tab import EditorTabMixin
from ..ui.editor_tools import EditorToolsMixin
from ..ui.file_actions import FileActionsMixin
from ..ui.navigation import NavigationMixin
from ..ui.palettes import PaletteMixin
from ..ui.simulation_tab import SimulationTabMixin


class LevelEditorApp(
    AudioTabMixin,
    SimulationTabMixin,
    ActorScriptingTabMixin,
    EditorTabMixin,
    EditorToolsMixin,
    EditorCanvasMixin,
    PaletteMixin,
    NavigationMixin,
    FileActionsMixin,
    tk.Tk,
):
    def __init__(self, project: AncientEmpiresProject):
        super().__init__()
        self.project = project
        self.title("Ancient Empires Level Editor")
        self.geometry("1220x840")

        self.level_var = tk.IntVar(value=0)
        self.room_var = tk.IntVar(value=0)
        self.part_var = tk.IntVar(value=0)
        self.zoom_var = tk.IntVar(value=3)
        self.mode_var = tk.StringVar(value="game")
        self.display_mode_var = tk.StringVar(value="vga")
        self.grid_var = tk.BooleanVar(value=False)
        self.show_collision_var = tk.BooleanVar(value=False)
        self.overlay_var = tk.BooleanVar(value=True)
        self.overlay_labels_var = tk.BooleanVar(value=True)
        self.overlay_links_var = tk.BooleanVar(value=True)
        self.overlay_hidden_var = tk.BooleanVar(value=False)
        self.tile_value_var = tk.StringVar(value="00")
        self.editor_tool_var = tk.StringVar(value="select")
        self.editor_object_var = tk.StringVar(value="exit_door")
        self.editor_overlay_var = tk.BooleanVar(value=True)
        self.belt_kind_var = tk.StringVar(value="grey")
        self.belt_length_var = tk.IntVar(value=4)
        self.platform_kind_var = tk.StringVar(value="horizontal_left")
        self.control_kind_var = tk.StringVar(value="ceiling_button")
        self.control_targets_var = tk.StringVar(value="P0")
        self.control_state_var = tk.StringVar(value="00")
        self.brush_size_var = tk.IntVar(value=1)
        self.tile_brush_mode_var = tk.StringVar(value="exact")
        self.decor_code_var = tk.StringVar(value="00")
        self.editor_info = tk.StringVar(value="")
        self.palette_selection_var = tk.StringVar(value="Selection mode")
        self.property_title_var = tk.StringVar(value="No object selected")
        self.property_x_var = tk.StringVar(value="")
        self.property_y_var = tk.StringVar(value="")
        self.property_len_var = tk.StringVar(value="")
        self.property_code_var = tk.StringVar(value="")
        self.property_props_var = tk.StringVar(value="")
        self.property_room_var = tk.StringVar(value="")
        self.property_label_x_var = tk.StringVar(value="x")
        self.property_label_y_var = tk.StringVar(value="y")
        self.property_label_len_var = tk.StringVar(value="len")
        self.property_label_code_var = tk.StringVar(value="code")
        self.property_label_props_var = tk.StringVar(value="props")
        self.property_label_room_var = tk.StringVar(value="room")
        self.property_note_var = tk.StringVar(value="")
        self.property_actor_facing_var = tk.BooleanVar(value=False)
        self.property_actor_hidden_var = tk.BooleanVar(value=False)
        self.scripting_actor_title_var = tk.StringVar(value="No actor selected")
        self.scripting_summary_var = tk.StringVar(value="")
        self.scripting_status_var = tk.StringVar(value="")
        self.scripting_address_var = tk.StringVar(value="")
        self.scripting_opcode_var = tk.StringVar(value="")
        self.actor_template_var = tk.StringVar(value=ACTOR_TEMPLATE_SPECS[0].key)
        self.actor_script_mode_var = tk.StringVar(value="new")
        self.actor_script_address_var = tk.StringVar(value="")
        self.actor_script_reset_address_var = tk.StringVar(value="")
        self.editor_selected_ref: tuple[str, int | None] | None = None
        self.editor_drag_offset: tuple[int, int] | None = None
        self.scripting_selected_actor_index: int | None = None
        self.actor_script_share_source_index: int | None = None
        self.scripting_selected_address: int | None = None
        self.scripting_script_start: int | None = None
        self.scripting_original_len = 0
        self.scripting_region_writable = False
        self.scripting_visible_addresses: list[int] = []
        self.scripting_instructions: list[Instruction] = []
        self.scripting_decoded = None
        self.scripting_space = None
        self.simulation: RoomSimulation | None = None
        self.simulation_key: tuple[int, int, int] | None = None
        self.sim_after_id: str | None = None
        self.sim_running_var = tk.BooleanVar(value=True)
        self.sim_speed_var = tk.IntVar(value=DEFAULT_SIMULATION_TICK_HZ)
        self.sim_info_var = tk.StringVar(value="")
        self.sim_detail_var = tk.StringVar(value="")
        self.sim_actor_debug_var = tk.StringVar(value="")
        self.sim_selected_actor_index: int | None = None
        self.room_link_buttons: dict[str, ttk.Button] = {}
        self.sim_sound_items_by_id: dict[int, AudioItem] | None = None
        self.sim_last_sound_status: str = ""

        for spec in OVERLAY_OPTION_SPECS:
            setattr(self, spec.var_name, tk.BooleanVar(value=spec.default))
        first_bank = next(iter(project.graphics.banks.keys()), "AE001:021")
        self.bank_var = tk.StringVar(value=first_bank)
        self.status = tk.StringVar(value="")
        self.tk_image = None
        self.tk_sim_image = None
        self.tk_sheet = None
        self.tk_atlas_images = []
        self.tk_editor_image = None
        self.tk_tile_images = []
        self.tk_editor_object_images = []
        self.tk_decor_images = []
        self.tk_actor_images = []
        self.audio_items: list[AudioItem] = []
        self.audio_item_by_key: dict[str, AudioItem] = {}
        self.audio_selected_key: str | None = None
        self.audio_info_var = tk.StringVar(value="")
        self.audio_speed_var = tk.StringVar(value=f"{DEFAULT_PREVIEW_SPEED:g}")
        self.audio_channel_program_vars: dict[int, tk.StringVar] = {}
        self.audio_channel_default_programs: dict[int, int | None] = {}
        self.audio_gm_choices = [f"{i:03d}: {name}" for i, name in enumerate(GM_PROGRAM_NAMES)]
        self.tree_bold_font = tkfont.nametofont("TkDefaultFont").copy()
        self.tree_bold_font.configure(weight="bold")

        self._build_menu_bar()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.close_window)
        self.redraw_room()
        self.redraw_bank_sheet()
        self.redraw_objects_atlas()
        if hasattr(self, "audio_tree"):
            self.refresh_audio_atlas()
        self.redraw_tile_palette()
        self.redraw_editor_object_palette()
        self.redraw_decor_palette()
        self.redraw_actor_palette()
        self.refresh_actor_scripting_tab()
        self.refresh_placeable_settings()
        self.reset_simulation(announce=False)
        self._schedule_simulation_tick()

    def _build_menu_bar(self) -> None:
        menu_bar = tk.Menu(self)

        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label="Save AE001", command=self.save_ae001, accelerator="Ctrl+S")
        file_menu.add_command(label="Save AE001 As...", command=self.save_ae001_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.close_window)
        menu_bar.add_cascade(label="File", menu=file_menu)

        export_menu = tk.Menu(menu_bar, tearoff=False)
        export_menu.add_command(label="Current room PNG...", command=self.export_current)
        export_menu.add_command(label="All room previews...", command=self.export_all_rooms)
        export_menu.add_command(label="Room probe CSV...", command=self.export_csv)
        export_menu.add_command(label="Graphics bank sheets...", command=self.export_sheets)
        menu_bar.add_cascade(label="Export", menu=export_menu)

        view_menu = tk.Menu(menu_bar, tearoff=False)
        display_menu = tk.Menu(view_menu, tearoff=False)
        display_menu.add_radiobutton(label="VGA", variable=self.display_mode_var, value="vga", command=self.set_display_mode)
        display_menu.add_radiobutton(label="EGA", variable=self.display_mode_var, value="ega", command=self.set_display_mode)
        display_menu.add_radiobutton(label="CGA", variable=self.display_mode_var, value="cga", command=self.set_display_mode)
        view_menu.add_cascade(label="Display mode", menu=display_menu)
        view_menu.add_separator()
        view_menu.add_checkbutton(label="Grid", variable=self.grid_var, command=self.redraw_room)
        view_menu.add_checkbutton(label="Hidden actors", variable=self.overlay_hidden_var, command=self.redraw_room)
        view_menu.add_checkbutton(label="Collision 07", variable=self.show_collision_var, command=self.redraw_room)
        menu_bar.add_cascade(label="View", menu=view_menu)

        self.config(menu=menu_bar)
        self.bind_all("<Control-s>", lambda _event: self.save_ae001())


    def set_display_mode(self) -> None:
        mode = self.display_mode_var.get()
        self.project.graphics.set_display_mode(mode)
        self.redraw_room()
        self.redraw_bank_sheet()
        self.redraw_objects_atlas()
        self.redraw_tile_palette()
        self.redraw_editor_object_palette()
        self.redraw_decor_palette()
        self.redraw_actor_palette()
        self.redraw_editor_room()
        self.redraw_simulation()
        self.status.set(f"Display mode: {mode.upper()}")

    def _build_ui(self) -> None:
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=5, pady=4)

        ttk.Label(top, text="Level").pack(side=tk.LEFT)
        self.level_combo = ttk.Combobox(
            top,
            state="readonly",
            width=16,
            values=[f"{i + 1:02d}" for i, _level in enumerate(self.project.levels)],
        )
        self.level_combo.current(0)
        self.level_combo.pack(side=tk.LEFT)
        self.level_combo.bind("<<ComboboxSelected>>", lambda _event: self.set_level(self.level_combo.current()))

        ttk.Label(top, text="Difficulty").pack(side=tk.LEFT, padx=(10, 0))
        self.part_combo = ttk.Combobox(top, state="readonly", width=10, values=DIFFICULTY_LABELS)
        self.part_combo.current(0)
        self.part_combo.pack(side=tk.LEFT)
        self.part_combo.bind("<<ComboboxSelected>>", lambda _event: self.set_part(self.part_combo.current()))

        ttk.Label(top, text="Room").pack(side=tk.LEFT, padx=(10, 0))
        self.room_combo = ttk.Combobox(top, state="readonly", width=10, values=self.room_labels())
        self.room_combo.current(0)
        self.room_combo.pack(side=tk.LEFT)
        self.room_combo.bind("<<ComboboxSelected>>", lambda _event: self.set_room(self.room_combo.current()))
        links = ttk.Frame(top)
        links.pack(side=tk.LEFT, padx=(8, 4))
        for direction, label in (("left", "←"), ("up", "↑"), ("down", "↓"), ("right", "→")):
            button = ttk.Button(links, text=label, width=5, command=lambda d=direction: self.go_room_link(d))
            button.pack(side=tk.LEFT, padx=1)
            self.room_link_buttons[direction] = button

        ttk.Label(top, text="Zoom").pack(side=tk.LEFT, padx=(8, 0))
        zoom = ttk.Combobox(top, textvariable=self.zoom_var, state="readonly", width=3, values=[1, 2, 3, 4])
        zoom.pack(side=tk.LEFT)
        zoom.bind("<<ComboboxSelected>>", lambda _event: self.redraw_room())

        self.status_label = ttk.Label(self, textvariable=self.status, justify=tk.LEFT, anchor="w")
        self.status_label.pack(side=tk.TOP, fill=tk.X, padx=6)
        self.status_label.bind("<Configure>", lambda event: self.status_label.configure(wraplength=max(200, event.width - 12)))

        tabs = ttk.Notebook(self)
        self.main_tabs = tabs
        tabs.pack(fill=tk.BOTH, expand=True)

        level_tab = ttk.Frame(tabs)
        simulation_tab = ttk.Frame(tabs)
        editor_tab = ttk.Frame(tabs)
        scripting_tab = ttk.Frame(tabs)
        graphics_tab = ttk.Frame(tabs)
        objects_tab = ttk.Frame(tabs)
        audio_tab = ttk.Frame(tabs)
        tabs.add(level_tab, text="Level viewer")
        tabs.add(simulation_tab, text="Simulation")
        tabs.add(editor_tab, text="Editor")
        tabs.add(scripting_tab, text="Script space")
        tabs.add(objects_tab, text="Objects atlas")
        tabs.add(graphics_tab, text="Graphics viewer")
        tabs.add(audio_tab, text="Audio atlas")

        main = ttk.PanedWindow(level_tab, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left, weight=4)
        main.add(right, weight=1)

        self.canvas = tk.Canvas(left, bg="black")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self.click_room)

        overlay_frame = ttk.LabelFrame(right, text="Overlay view")
        overlay_frame.pack(fill=tk.X, padx=4, pady=(0, 6))

        mode_frame = ttk.LabelFrame(right, text="Level viewer mode")
        mode_frame.pack(fill=tk.X, padx=4, pady=(0, 6))
        render_modes = (
            ("Game view", "game"),
            ("Payload debug", "payload_debug"),
            ("Tile codes hex", "codes_hex"),
            ("Trailing bytes hex", "trailing_hex"),
        )
        for label, value in render_modes:
            ttk.Radiobutton(mode_frame, text=label, variable=self.mode_var, value=value, command=self.redraw_room).pack(
                anchor="w", padx=6, pady=1
            )

        general = ttk.Frame(overlay_frame)
        general.pack(fill=tk.X, padx=6, pady=(4, 2))
        ttk.Checkbutton(general, text="Enable overlay", variable=self.overlay_var, command=self.redraw_room).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(general, text="Labels", variable=self.overlay_labels_var, command=self.redraw_room).grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Checkbutton(general, text="Master lines", variable=self.overlay_links_var, command=self.redraw_room).grid(row=0, column=2, sticky="w", padx=(10, 0))

        preset_bar = ttk.Frame(overlay_frame)
        preset_bar.pack(fill=tk.X, padx=6, pady=(0, 4))
        ttk.Button(preset_bar, text="Minimal", command=lambda: self.apply_overlay_preset("minimal")).pack(side=tk.LEFT)
        ttk.Button(preset_bar, text="Logic", command=lambda: self.apply_overlay_preset("logic")).pack(side=tk.LEFT, padx=4)
        ttk.Button(preset_bar, text="Debug", command=lambda: self.apply_overlay_preset("debug")).pack(side=tk.LEFT)

        groups = ttk.Frame(overlay_frame)
        groups.pack(fill=tk.X, padx=6, pady=(0, 6))

        for idx, spec in enumerate(OVERLAY_OPTION_SPECS):
            row = idx // 2
            col = idx % 2
            ttk.Checkbutton(
                groups,
                text=spec.label,
                variable=getattr(self, spec.var_name),
                command=self.redraw_room,
            ).grid(row=row, column=col, sticky="w", padx=(0, 12), pady=1)

        ttk.Label(
            right,
            text="Use Editor for write-back edits and Simulation for runtime behavior checks.",
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=6, pady=(4, 0))

        self._build_simulation_tab(simulation_tab)
        self._build_editor_tab(editor_tab)
        self._build_actor_scripting_tab(scripting_tab)

        atlas_top = ttk.Frame(objects_tab)
        atlas_top.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(atlas_top, text="Recognized object atlas").pack(side=tk.LEFT)
        ttk.Button(atlas_top, text="Refresh", command=self.redraw_objects_atlas).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(
            objects_tab,
            text="Grouped by known gameplay meaning. This is a catalog of things the parser currently recognizes.",
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=6, pady=(0, 4))

        objects_canvas_frame = ttk.Frame(objects_tab)
        objects_canvas_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self.objects_canvas = tk.Canvas(objects_canvas_frame, bg="#202020")
        self.objects_vscroll = ttk.Scrollbar(objects_canvas_frame, orient=tk.VERTICAL, command=self.objects_canvas.yview)
        self.objects_hscroll = ttk.Scrollbar(objects_canvas_frame, orient=tk.HORIZONTAL, command=self.objects_canvas.xview)
        self.objects_canvas.configure(yscrollcommand=self.objects_vscroll.set, xscrollcommand=self.objects_hscroll.set)
        self.objects_canvas.grid(row=0, column=0, sticky="nsew")
        self.objects_vscroll.grid(row=0, column=1, sticky="ns")
        self.objects_hscroll.grid(row=1, column=0, sticky="ew")
        objects_canvas_frame.rowconfigure(0, weight=1)
        objects_canvas_frame.columnconfigure(0, weight=1)
        self.objects_canvas.bind("<MouseWheel>", lambda event: self.objects_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units"))
        self.objects_canvas.bind("<Shift-MouseWheel>", lambda event: self.objects_canvas.xview_scroll(int(-1 * (event.delta / 120)), "units"))
        self.objects_canvas.bind("<Button-1>", self.objects_atlas_click)

        bank_top = ttk.Frame(graphics_tab)
        bank_top.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(bank_top, text="Sprite bank").pack(side=tk.LEFT)
        self.bank_combo = ttk.Combobox(
            bank_top,
            state="readonly",
            width=14,
            values=list(self.project.graphics.banks.keys()),
            textvariable=self.bank_var,
        )
        self.bank_combo.pack(side=tk.LEFT, padx=(4, 0))
        self.bank_combo.bind("<<ComboboxSelected>>", lambda _event: self.redraw_bank_sheet())

        ttk.Label(
            graphics_tab,
            text="Decoded graphics banks. Useful for identifying actors, pickups, triggers, projectiles and terrain art.",
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=6, pady=(0, 4))

        bank_canvas_frame = ttk.Frame(graphics_tab)
        bank_canvas_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self.bank_canvas = tk.Canvas(bank_canvas_frame, bg="white")
        self.bank_vscroll = ttk.Scrollbar(bank_canvas_frame, orient=tk.VERTICAL, command=self.bank_canvas.yview)
        self.bank_hscroll = ttk.Scrollbar(bank_canvas_frame, orient=tk.HORIZONTAL, command=self.bank_canvas.xview)
        self.bank_canvas.configure(yscrollcommand=self.bank_vscroll.set, xscrollcommand=self.bank_hscroll.set)
        self.bank_canvas.grid(row=0, column=0, sticky="nsew")
        self.bank_vscroll.grid(row=0, column=1, sticky="ns")
        self.bank_hscroll.grid(row=1, column=0, sticky="ew")
        bank_canvas_frame.rowconfigure(0, weight=1)
        bank_canvas_frame.columnconfigure(0, weight=1)
        self.bank_canvas.bind("<MouseWheel>", lambda event: self.bank_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units"))
        self.bank_canvas.bind("<Shift-MouseWheel>", lambda event: self.bank_canvas.xview_scroll(int(-1 * (event.delta / 120)), "units"))

        self._build_audio_tab(audio_tab)
