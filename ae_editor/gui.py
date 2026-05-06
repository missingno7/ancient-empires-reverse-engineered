from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .constants import CELL_SIZE, ROOM_COUNT, ROOM_COLUMNS, ROOM_ROWS
from .exporters import export_bank_sheets, export_probe_csv, export_room_previews
from .overlay import build_room_overlay, control_ref_values, control_targets, decode_control_target
from .coordinates import control_xy, actor_xy
from .coordinates import platform_xy
from .conveyors import iter_conveyor_runs
from .project import AncientEmpiresProject
from .renderer import RenderOptions
from .object_mapping import visual_sprite_ref
from .tile_mapping import AUTO_SOLID_TILE_CODES, CONVEYOR_PHYSICS_TILE_CODES, ROPE_TILE_CODES
from .room_payload import (
    actor_records_for_room,
    control_commands,
    header_exit_door,
    header_object_candidates,
    header_player_start,
    laser_crystal_table,
    PLATFORM_TRIPLET_SIZE,
    clear_runtime_triplet_slot,
    first_free_runtime_triplet_slot,
    parse_exe_payload_directory,
    parse_platform_triplets,
    parse_conveyor_visual_records,
    add_conveyor_visual_record,
    set_conveyor_visual_record,
    set_control_command_body,
    delete_conveyor_visual_record,
    add_visual_compact3_entry,
    set_visual_compact3_entry,
    delete_visual_compact3_entry,
    add_laser_crystal_entry,
    set_laser_crystal_entry,
    delete_laser_crystal_entry,
    add_control_command,
    delete_control_command,
    cv_geometry_to_raw,
    transition_links_for_room,
    visual_compact3_table,
)

DIFFICULTY_LABELS = ["Explorer", "Expert"]
COLLISION_TILE_CODE = 0x07
PLATFORM_FOOTPRINT_CELLS = {
    "horizontal": (6, 1),
    "vertical": (1, 6),
    "unknown": (1, 1),
}
PLATFORM_KIND_FLAGS = {
    "horizontal_left": 0x40,
    "horizontal_right": 0x60,
    "vertical_down": 0x80,
    "vertical_up": 0xA0,
}
DELETE_SELECTION_HINT = (
    "Select an artifact, platform, CV, belt, control, decor decal, or reflector first. "
    "Actors are inspect-only for now."
)


@dataclass(frozen=True)
class OverlayOptionSpec:
    label: str
    var_name: str
    default: bool
    minimal: bool
    logic: bool
    debug: bool


@dataclass(frozen=True)
class EditorHandle:
    ref: tuple[str, int | None]
    x: int
    y: int
    label: str
    colour: str


OVERLAY_OPTION_SPECS = (
    OverlayOptionSpec("Platforms", "show_platforms_var", True, True, True, True),
    OverlayOptionSpec("Platform paths", "show_platform_paths_var", False, False, True, True),
    OverlayOptionSpec("Conveyors", "show_conveyors_var", False, False, True, True),
    OverlayOptionSpec("Controls", "show_controls_var", True, True, True, True),
    OverlayOptionSpec("Trigger links", "show_trigger_links_var", False, False, True, True),
    OverlayOptionSpec("Puzzle markers", "show_puzzle_markers_var", True, True, True, True),
    OverlayOptionSpec("Puzzle blocks", "show_puzzle_blocks_var", True, True, True, True),
    OverlayOptionSpec("Puzzle dest", "show_puzzle_destinations_var", False, False, True, True),
    OverlayOptionSpec("Puzzle links", "show_puzzle_links_var", False, False, True, True),
    OverlayOptionSpec("Puzzle moves", "show_puzzle_move_links_var", True, True, True, True),
    OverlayOptionSpec("Actors", "show_actors_var", True, True, True, True),
    OverlayOptionSpec("Actor paths", "show_actor_paths_var", False, False, True, True),
    OverlayOptionSpec("Projectile links", "show_projectile_links_var", True, False, True, True),
    OverlayOptionSpec("Pickups", "show_pickups_var", True, True, True, True),
    OverlayOptionSpec("Crystals", "show_crystals_var", True, True, True, True),
    OverlayOptionSpec("Exits", "show_exits_var", False, False, False, True),
)


class LevelEditorApp(tk.Tk):
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
        self.grid_var = tk.BooleanVar(value=False)
        self.show_collision_var = tk.BooleanVar(value=False)
        self.overlay_var = tk.BooleanVar(value=True)
        self.overlay_labels_var = tk.BooleanVar(value=True)
        self.overlay_links_var = tk.BooleanVar(value=True)
        self.overlay_hidden_var = tk.BooleanVar(value=False)
        self.tile_value_var = tk.StringVar(value="00")
        self.editor_tool_var = tk.StringVar(value="select")
        self.editor_object_var = tk.StringVar(value="exit_door")
        self.editor_grid_var = tk.BooleanVar(value=True)
        self.editor_overlay_var = tk.BooleanVar(value=True)
        self.editor_collision_var = tk.BooleanVar(value=True)
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
        self.property_label_x_var = tk.StringVar(value="x")
        self.property_label_y_var = tk.StringVar(value="y")
        self.property_label_len_var = tk.StringVar(value="len")
        self.property_label_code_var = tk.StringVar(value="code")
        self.property_label_props_var = tk.StringVar(value="props")
        self.property_note_var = tk.StringVar(value="")
        self.property_actor_facing_var = tk.BooleanVar(value=False)
        self.property_actor_hidden_var = tk.BooleanVar(value=False)
        self.editor_selected_ref: tuple[str, int | None] | None = None
        self.editor_drag_offset: tuple[int, int] | None = None

        for spec in OVERLAY_OPTION_SPECS:
            setattr(self, spec.var_name, tk.BooleanVar(value=spec.default))
        first_bank = next(iter(project.graphics.banks.keys()), "AE001:021")
        self.bank_var = tk.StringVar(value=first_bank)
        self.status = tk.StringVar(value="")
        self.tk_image = None
        self.tk_sheet = None
        self.tk_atlas_images = []
        self.tk_editor_image = None
        self.tk_tile_images = []
        self.tk_editor_object_images = []
        self.tk_decor_images = []
        self.tk_actor_images = []

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.close_window)
        self.redraw_room()
        self.redraw_bank_sheet()
        self.redraw_objects_atlas()
        self.redraw_tile_palette()
        self.redraw_editor_object_palette()
        self.redraw_decor_palette()
        self.redraw_actor_palette()
        self.refresh_placeable_settings()

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
        ttk.Button(top, text="Prev", command=lambda: self.set_room((self.room_var.get() - 1) % ROOM_COUNT)).pack(side=tk.LEFT)
        ttk.Button(top, text="Next", command=lambda: self.set_room((self.room_var.get() + 1) % ROOM_COUNT)).pack(side=tk.LEFT)

        ttk.Label(top, text="Mode").pack(side=tk.LEFT, padx=(10, 0))
        mode = ttk.Combobox(top, textvariable=self.mode_var, state="readonly", width=13, values=["game", "payload_debug", "codes_hex", "trailing_hex"])
        mode.pack(side=tk.LEFT)
        mode.bind("<<ComboboxSelected>>", lambda _event: self.redraw_room())

        ttk.Checkbutton(top, text="grid", variable=self.grid_var, command=self.redraw_room).pack(side=tk.LEFT, padx=6)

        ttk.Label(top, text="Zoom").pack(side=tk.LEFT)
        zoom = ttk.Combobox(top, textvariable=self.zoom_var, state="readonly", width=3, values=[1, 2, 3, 4])
        zoom.pack(side=tk.LEFT)
        zoom.bind("<<ComboboxSelected>>", lambda _event: self.redraw_room())

        ttk.Button(top, text="Export current", command=self.export_current).pack(side=tk.LEFT, padx=8)
        ttk.Button(top, text="Export all rooms", command=self.export_all_rooms).pack(side=tk.LEFT)
        ttk.Button(top, text="Export CSV", command=self.export_csv).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Export bank sheets", command=self.export_sheets).pack(side=tk.LEFT)
        ttk.Button(top, text="Save AE001", command=self.save_ae001).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(top, text="Save as...", command=self.save_ae001_as).pack(side=tk.LEFT, padx=(4, 0))

        self.status_label = ttk.Label(self, textvariable=self.status, justify=tk.LEFT, anchor="w")
        self.status_label.pack(side=tk.TOP, fill=tk.X, padx=6)
        self.status_label.bind("<Configure>", lambda event: self.status_label.configure(wraplength=max(200, event.width - 12)))

        tabs = ttk.Notebook(self)
        tabs.pack(fill=tk.BOTH, expand=True)

        level_tab = ttk.Frame(tabs)
        editor_tab = ttk.Frame(tabs)
        graphics_tab = ttk.Frame(tabs)
        objects_tab = ttk.Frame(tabs)
        tabs.add(level_tab, text="Level viewer")
        tabs.add(editor_tab, text="Editor")
        tabs.add(objects_tab, text="Objects atlas")
        tabs.add(graphics_tab, text="Graphics viewer")

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

        general = ttk.Frame(overlay_frame)
        general.pack(fill=tk.X, padx=6, pady=(4, 2))
        ttk.Checkbutton(general, text="Enable overlay", variable=self.overlay_var, command=self.redraw_room).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(general, text="Labels", variable=self.overlay_labels_var, command=self.redraw_room).grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Checkbutton(general, text="Master lines", variable=self.overlay_links_var, command=self.redraw_room).grid(row=0, column=2, sticky="w", padx=(10, 0))
        ttk.Checkbutton(general, text="Hidden actors", variable=self.overlay_hidden_var, command=self.redraw_room).grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(general, text="Collision 07", variable=self.show_collision_var, command=self.redraw_room).grid(row=1, column=1, sticky="w", padx=(10, 0))

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
            text="Sprite banks are now in the Graphics viewer tab.\nFuture object editor can live here.",
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=6, pady=(4, 0))

        self._build_editor_tab(editor_tab)

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
        ttk.Checkbutton(view_row, text="Grid", variable=self.editor_grid_var, command=self.on_editor_tool_changed).pack(side=tk.LEFT)
        ttk.Checkbutton(view_row, text="Overlay", variable=self.editor_overlay_var, command=self.redraw_editor_room).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Checkbutton(view_row, text="Collision", variable=self.editor_collision_var, command=self.redraw_editor_room).pack(side=tk.LEFT, padx=(8, 0))

        action_row = ttk.Frame(right)
        action_row.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Button(action_row, text="Select / move", command=self.select_selection_mode).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(action_row, text="Delete selected", command=self.delete_selected_editor_object).pack(side=tk.LEFT, padx=(6, 0))

        self.editor_palettes = ttk.Notebook(right)
        self.editor_palettes.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        tile_tab = ttk.Frame(self.editor_palettes)
        object_tab = ttk.Frame(self.editor_palettes)
        decor_tab = ttk.Frame(self.editor_palettes)
        actor_tab = ttk.Frame(self.editor_palettes)
        self.editor_palettes.add(tile_tab, text="Tile brush")
        self.editor_palettes.add(object_tab, text="Mechanics")
        self.editor_palettes.add(decor_tab, text="Decor")
        self.editor_palettes.add(actor_tab, text="Actors")
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
            text="Targets use typed ids: P0 = platform, CV0 = belt, M0 = mirror/reflector-like target. One control can target multiple items, e.g. P0,CV0.",
            wraplength=260,
            justify=tk.LEFT,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 6))

        self.object_settings_frame = ttk.LabelFrame(mechanics_settings_host, text="Object placement")
        ttk.Label(self.object_settings_frame, text="Choose an object from Object placement, then click in the room to place it. Use Select objects to move or delete existing objects.", wraplength=260, justify=tk.LEFT).pack(fill=tk.X, padx=6, pady=6)

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

        ttk.Label(
            actor_tab,
            text="Current room actors are selectable for inspection. Placement and path editing can plug in here next.",
            wraplength=260,
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=6, pady=(6, 4))
        self.actor_palette_canvas = tk.Canvas(actor_tab, bg="#202020", width=260)
        actor_scroll = ttk.Scrollbar(actor_tab, orient=tk.VERTICAL, command=self.actor_palette_canvas.yview)
        self.actor_palette_canvas.configure(yscrollcommand=actor_scroll.set)
        self.actor_palette_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0), pady=(0, 6))
        actor_scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=(0, 6))
        self.actor_palette_canvas.bind("<Button-1>", self.actor_palette_click)

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
            if self.editor_tool_var.get() not in {"select", "belt", "platform", "object"}:
                self.select_selection_mode()
        elif selected == 2:
            if self.editor_tool_var.get() != "decor":
                self.select_decor_mode()
        elif selected == 3:
            if self.editor_tool_var.get() != "actor":
                self.select_actor_mode()

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
        if hasattr(self, "editor_palettes"):
            self.editor_palettes.select(3)
        self.refresh_placeable_settings()
        self.redraw_actor_palette()
        self.redraw_editor_room()

    def refresh_placeable_settings(self) -> None:
        if not hasattr(self, "select_settings_frame"):
            return
        for frame in (
            self.select_settings_frame,
            self.tile_settings_frame,
            self.belt_settings_frame,
            self.platform_settings_frame,
            self.control_settings_frame,
            self.object_settings_frame,
        ):
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
            self.palette_selection_var.set(f"Mechanics: platform {self.platform_kind_var.get().replace('_', ' ')}")
        elif tool == "object":
            obj = self.editor_object_var.get().replace("_", " ")
            if self.editor_object_var.get() in {"ceiling_button", "floor_switch", "jello"}:
                self.control_settings_frame.pack(fill=tk.X)
            else:
                self.object_settings_frame.pack(fill=tk.X)
            self.palette_selection_var.set(f"Object placement: {obj}")
        elif tool == "decor":
            self.palette_selection_var.set(f"Decor decals: code {self.decor_code_var.get().upper()}")
        elif tool == "actor":
            self.palette_selection_var.set("Actors: select and inspect")
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
            grid=self.grid_var.get(),
            part_index=self.part_var.get(),
        )

    def current_level(self):
        return self.project.levels[self.level_var.get()]

    def current_image(self, zoom: int | None = None):
        return self.project.renderer.render_room(self.current_level(), self.room_var.get(), self.options(zoom))

    def current_room(self):
        return self.current_level().part(self.part_var.get()).room(self.room_var.get())

    def set_part(self, index: int) -> None:
        self.part_var.set(index)
        self.part_combo.current(index)
        self.editor_selected_ref = None
        self.editor_drag_offset = None
        self.refresh_room_labels()
        self.redraw_room()
        self.redraw_objects_atlas()
        self.redraw_tile_palette()
        self.redraw_editor_object_palette()
        self.redraw_decor_palette()
        self.redraw_actor_palette()

    def set_level(self, index: int) -> None:
        self.level_var.set(index)
        self.editor_selected_ref = None
        self.editor_drag_offset = None
        self.refresh_room_labels()
        self.redraw_room()
        self.redraw_objects_atlas()
        self.redraw_tile_palette()
        self.redraw_editor_object_palette()

    def set_room(self, index: int) -> None:
        self.room_var.set(index)
        self.room_combo.current(index)
        self.editor_selected_ref = None
        self.editor_drag_offset = None
        self.redraw_room()
        self.redraw_objects_atlas()
        self.redraw_editor_object_palette()
        self.redraw_decor_palette()
        self.redraw_actor_palette()

    def redraw_room(self) -> None:
        image = self.current_image()
        self.tk_image = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_image)
        self.canvas.config(scrollregion=(0, 0, image.width, image.height))

        level = self.current_level()
        part = level.part(self.part_var.get())
        room = part.room(self.room_var.get())
        unique = sorted(set(room.tiles))
        directory = parse_exe_payload_directory(room)
        visual = visual_compact3_table(room)
        crystals = laser_crystal_table(room)
        actors = actor_records_for_room(part, room.index)
        door = header_exit_door(part.header)
        links = transition_links_for_room(part, room.index)
        controls = 0 if directory is None else len(directory.control_records)
        visual_txt = "none" if visual is None else f"@{visual.offset:02X} n={visual.count}"
        crystal_txt = "none" if crystals is None else f"@{crystals.offset:02X} n={crystals.count}"
        door_txt = "none" if door is None else f"room={door.room_index} x={door.x_raw:02X} y={door.y_raw:02X}"
        platforms = ", ".join(p.label for p in parse_platform_triplets(room)) or "none"
        self.status.set(
            f"level={level.index + 1} difficulty={DIFFICULTY_LABELS[part.index]} room={room.index} theme={part.theme} "
            f"room_quality={room.quality_label} terrain_off=0x{room.terrain_offset:04X} preamble={room.preamble.hex(' ')} "
            f"platforms=[{platforms}] controls={controls} actors={len(actors)} links={links.label if links else 'none'} "
            f"exit_door={door_txt} crystals={crystal_txt} visual={visual_txt} "
            f"unique_tiles={unique} footer={part.footer.hex(' ')}"
        )
        if self.show_collision_var.get() and self.mode_var.get() != "trailing_hex":
            self.draw_collision_overlay(self.canvas, room)
        if self.mode_var.get() == "codes_hex":
            self.draw_codes_overlay(room)
        elif self.mode_var.get() == "trailing_hex":
            self.draw_trailing_overlay(room)
        elif self.overlay_var.get():
            self.draw_room_overlay(level, part, room)
        self.redraw_editor_room()

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
        self.project.mark_level_dirty(self.current_level().index)
        suffix = " *" if self.project.dirty else ""
        self.title(f"Ancient Empires Level Editor{suffix}")


    def _parse_int_property(self, value: str, *, default: int = 0) -> int:
        text = value.strip()
        if not text:
            return default
        base = 16 if text.lower().startswith("0x") or any(c in "abcdefABCDEF" for c in text) else 10
        return int(text, base)

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
            elif upper.startswith("M"):
                idx = self._parse_int_property(part[1:], default=0)
                if not 0 <= idx < 16:
                    raise ValueError(f"mirror target index must be 0..15, got {idx}")
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
        self.property_note_var.set("")

    def _clear_property_values(self) -> None:
        self.property_x_var.set("")
        self.property_y_var.set("")
        self.property_len_var.set("")
        self.property_code_var.set("")
        self.property_props_var.set("")

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

    def _layout_property_panel(self, *, rows: tuple[bool, bool, bool] = (False, False, False), actor_bools: bool = False, apply: bool = False) -> None:
        for index, visible in enumerate(rows):
            self._set_property_row_visible(index, visible)
        if actor_bools:
            self.property_actor_bool_row.grid(row=4, column=0, columnspan=4, sticky="w", padx=6, pady=(2, 2))
        else:
            self.property_actor_bool_row.grid_remove()
        if apply:
            self.property_apply_button.grid(row=5, column=0, columnspan=4, sticky="ew", padx=6, pady=(4, 4))
            note_row = 6
        else:
            self.property_apply_button.grid_remove()
            note_row = 5
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
            self.property_note_var.set("Friendly model: body = type, x, y, state/subtype, target0, target1...  Targets are typed bytes: P0=00, CV0=10, M0=40. One button can control multiple things, e.g. P0,CV0. State/subtype is preserved as raw byte " + state_text + ".")
        elif kind == "decor":
            entry = self._decor_from_ref(room, ref)
            if entry is None:
                self.property_title_var.set("Selected decor decal no longer exists")
                self._clear_property_values()
                self._layout_property_panel()
                return
            self._layout_property_panel(rows=(True, True, False), apply=True)
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
            self.property_label_len_var.set("code")
            self.property_label_code_var.set("sprite")
            self.property_x_var.set(str(entry.x_raw))
            self.property_y_var.set(str(entry.y))
            self.property_len_var.set(f"{entry.code:02X}")
            self.property_code_var.set(f"{sprite_ref.archive}:{sprite_ref.resource_id:03d}:{sprite_ref.sprite_index}")
            self.property_note_var.set(sprite_ref.note or "Theme visual compact3 entry.")
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
            self._layout_property_panel(rows=(True, True, not binary_hidden), actor_bools=binary_facing or binary_hidden)
            if binary_facing:
                self.property_rows[1][0].grid_remove()
                self.property_rows[1][1].grid_remove()
            self._set_actor_bool_controls(
                facing=bool(actor.frame_variant & 0x01),
                hidden=bool(actor.hidden),
                show_facing=binary_facing,
                show_hidden=binary_hidden,
                enabled=False,
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
            note_bits = []
            if binary_facing:
                note_bits.append("facing is shown as a boolean variant")
            if binary_hidden:
                note_bits.append("hidden is shown as a checkbox")
            suffix = "; ".join(note_bits) or "raw actor bytes are shown because this actor uses non-binary state values"
            self.property_note_var.set(f"Actor table is inspect-only for now; {suffix}.")
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
            refs = [cmd.record.index for cmd in cmd_by_index.values() if any(t.kind == "mirror" and t.index == entry.index for t in control_targets(cmd))]
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
            self.property_label_len_var.set("code")
            self.property_label_code_var.set("sprite")
            self.property_label_props_var.set("controlled by")
            self.property_x_var.set(str(entry.x_raw))
            self.property_y_var.set(str(entry.y))
            self.property_len_var.set(f"{entry.code:02X}")
            self.property_code_var.set(str(entry.code & 0x3F))
            self.property_props_var.set(controlled_by)
            self.property_note_var.set("Section_c laser/reflector entry. Controls point here with M0/M1/...; edit links on the selected button/switch Targets field. High bits in code are preserved as raw state/flags; a reflector with no incoming control may be autonomous or state-driven elsewhere.")
        elif kind == "known_pickup":
            idx = ref[1]
            pickups = self._known_extra_pickups_for_room(self.current_level().part(self.part_var.get()), room)
            if idx is None or not 0 <= idx < len(pickups):
                self.property_title_var.set("Selected pickup no longer exists")
                self._clear_property_values()
                self._layout_property_panel()
                return
            pickup = pickups[idx]
            self._layout_property_panel(rows=(True, True, False), apply=False)
            name = "Apple" if pickup.resource_id == 45 else "Known pickup"
            self.property_title_var.set(name)
            self.property_label_x_var.set("x")
            self.property_label_y_var.set("y")
            self.property_label_len_var.set("source")
            self.property_label_code_var.set("sprite")
            self.property_x_var.set(str(pickup.x))
            self.property_y_var.set(str(pickup.y))
            self.property_len_var.set("verified screenshot")
            self.property_code_var.set(f"{pickup.archive}:{pickup.resource_id:03d}:{pickup.sprite_index}")
            self.property_note_var.set("Read-only verified apple marker. Its original gameplay storage is still unknown, so the editor no longer writes fake apple compact3 records that break the real game.")
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
                self.property_len_var.set("0")
                self.property_code_var.set("-")
                self.property_note_var.set("Header object. Player start belongs to room 0 in the current model.")
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
                    self.refresh_property_panel()
                    return
                old_platforms = [p for p in parse_platform_triplets(room) if p.index == slot]
                if old_platforms:
                    self._clear_platform_footprint(room, old_platforms[0])
                room.set_trailing_bytes(slot * PLATFORM_TRIPLET_SIZE, [flags, x_raw, y_raw])
                new_platforms = [p for p in parse_platform_triplets(room) if p.index == slot]
                if new_platforms:
                    self._write_platform_footprint(room, new_platforms[0])
                self.status.set(f"Updated P{slot}: flags={flags:02X} x={x_raw} y={y_raw}")
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
                    current_targets = control_ref_values(cmd)
                    targets = self._parse_control_targets(self.property_len_var.get(), current=current_targets)
                    self._rewrite_control_targets(body, targets)
                set_control_command_body(room, idx, bytes(body), allow_resize=True)
                new_targets = [decode_control_target(value).label for value in body[4:]]
                self.status.set(f"Updated C{idx}: targets={','.join(new_targets)} body={bytes(body).hex(' ')}")
            elif kind == "decor":
                entry = self._decor_from_ref(room, ref)
                if entry is None:
                    self.status.set("Selected decor decal no longer exists.")
                    return
                x_raw = self._parse_int_property(self.property_x_var.get(), default=entry.x_raw) & 0xFF
                y_raw = self._parse_int_property(self.property_y_var.get(), default=entry.y) & 0xFF
                code = self._parse_int_property(self.property_len_var.get(), default=entry.code) & 0xFF
                set_visual_compact3_entry(room, entry.index, x_raw=x_raw, y=y_raw, code=code)
                self.decor_code_var.set(f"{code:02X}")
                self.status.set(f"Updated V{entry.index}: code={code:02X} x={x_raw} y={y_raw}")
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
                self.status.set(f"Updated player start: x={x_raw} y={y_raw}")
            elif kind == "artifact":
                slot = ref[1]
                part = self.current_level().part(self.part_var.get())
                x_raw = self._parse_int_property(self.property_x_var.get(), default=0) & 0xFF
                y_raw = self._parse_int_property(self.property_y_var.get(), default=0) & 0xFF
                room_index = max(0, min(ROOM_COUNT - 1, self._parse_int_property(self.property_len_var.get(), default=room.index)))
                part.set_artifact_slot(slot, room_index, x_raw, y_raw)
                self.status.set(f"Updated artifact {slot}: room={room_index} x={x_raw} y={y_raw}")
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
        # Renderer keeps visually verified pickups whose original storage schema
        # is still unknown.  Expose them in the editor as read-only handles so
        # they are visible/selectable instead of silently looking like terrain.
        key = (self.current_level().index + 1, part.index, room.index)
        return list(getattr(self.project.renderer, "KNOWN_EXTRA_PICKUPS", {}).get(key, []))

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

    def editor_object_handles(self, part, room) -> list[EditorHandle]:
        handles: list[EditorHandle] = []
        door = header_exit_door(part.header)
        if door and door.room_index == room.index:
            handles.append(EditorHandle(("exit_door", None), door.x_raw * 2, door.y_raw, "Exit", "#ffffff"))
        start = header_player_start(part.header)
        if start and room.index == 0:
            handles.append(EditorHandle(("player_start", None), start.x_raw * 2, start.y_raw, "Start", "#7cff6b"))
        for cand in header_object_candidates(part.header):
            if cand.room_plus_one == room.index + 1:
                handles.append(EditorHandle(("artifact", cand.index), cand.x_raw * 2, cand.y_raw, f"D{cand.index}", "#ff40ff"))
        for i, pickup in enumerate(self._known_extra_pickups_for_room(part, room)):
            label = "Apple" if pickup.resource_id == 45 else f"Pickup{i}"
            handles.append(EditorHandle(("known_pickup", i), pickup.x + 8, pickup.y + 8, label, "#ff5050"))
        for platform in parse_platform_triplets(room):
            if platform.visible:
                handles.append(EditorHandle(("platform", platform.index), platform.x_raw * 2, platform.y, f"P{platform.index}", "#ffb000"))
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
            if actor.hidden and not self.overlay_hidden_var.get():
                continue
            ax, ay = actor_xy(actor.x, actor.y, frame_min=actor.frame_min)
            handles.append(EditorHandle(("actor", actor.index), ax + 12, ay + 8, f"A{actor.index}", "#7cff6b" if not actor.hidden else "#7a7a7a"))
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
                if entry.code == 0xFD:
                    label = f"Apple V{entry.index}"
                    colour = "#ff5050"
                handles.append(EditorHandle(("decor", entry.index), entry.x_raw * 2, entry.y, label, colour))
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
                    flag_to_kind = {0x40: "horizontal_left", 0x60: "horizontal_right", 0x80: "vertical_down", 0xA0: "vertical_up"}
                    self.platform_kind_var.set(flag_to_kind.get(platforms[0].flags & 0xF0, self.platform_kind_var.get()))
                    self.editor_tool_var.set("platform")
                    if hasattr(self, "editor_palettes"):
                        self.editor_palettes.select(1)
            elif kind == "decor" and slot is not None:
                entry = self._decor_from_ref(self.current_room(), handle.ref)
                if entry is not None:
                    self.decor_code_var.set(f"{entry.code:02X}")
                    self.editor_tool_var.set("decor")
                    if hasattr(self, "editor_palettes"):
                        self.editor_palettes.select(2)
            elif kind == "actor" and slot is not None:
                self.editor_tool_var.set("actor")
                if hasattr(self, "editor_palettes"):
                    self.editor_palettes.select(3)
            elif kind == "known_pickup":
                self.editor_object_var.set("apple")
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
        before_header = part.header
        before_tiles = list(room.tiles)
        before_trailing = room.trailing

        if kind == "exit_door":
            part.set_exit_door(room.index, self._clamp_byte(round(x / 2)), self._clamp_byte(y))
        elif kind == "player_start":
            if room.index != 0:
                self.status.set("Player start belongs to room 0 in the current header model.")
                return
            part.set_player_start(self._clamp_byte(round(x / 2)), self._clamp_byte(y))
        elif kind == "artifact" and slot is not None:
            part.set_artifact_slot(slot, room.index, self._clamp_byte(round(x / 2)), self._clamp_byte(y))
        elif kind == "platform" and slot is not None:
            platforms = [p for p in parse_platform_triplets(room) if p.index == slot]
            if platforms:
                self._clear_platform_footprint(room, platforms[0])
            off = slot * PLATFORM_TRIPLET_SIZE
            room.set_trailing_bytes(off + 1, [self._clamp_byte(round(x / 2)), self._clamp_byte(y)])
            platforms = [p for p in parse_platform_triplets(room) if p.index == slot]
            if platforms:
                self._write_platform_footprint(room, platforms[0])
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
        elif kind == "actor":
            self.status.set("Actor table handles are selectable for inspection; movement editing is not enabled yet.")
            return
        elif kind == "known_pickup":
            self.status.set("This apple is a verified read-only marker; original apple storage is still unknown, so the editor will not write fake apple records into the game data.")
            return
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

        if part.header == before_header and room.tiles == before_tiles and room.trailing == before_trailing:
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
                    flag_to_kind = {0x40: "horizontal_left", 0x60: "horizontal_right", 0x80: "vertical_down", 0xA0: "vertical_up"}
                    self.platform_kind_var.set(flag_to_kind.get(platforms[0].flags & 0xF0, self.platform_kind_var.get()))
                    self.editor_tool_var.set("platform")
                    if hasattr(self, "editor_palettes"):
                        self.editor_palettes.select(1)
            elif kind == "decor" and slot is not None:
                entry = self._decor_from_ref(self.current_room(), handle.ref)
                if entry is not None:
                    self.decor_code_var.set(f"{entry.code:02X}")
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
            x_raw = self._clamp_byte(round((x + 4) / 2))
            y_raw = self._clamp_byte(y + 16)
            part.set_player_start(x_raw, y_raw)
        elif obj.startswith("artifact_"):
            slot = int(obj.split("_", 1)[1])
            x_raw = self._clamp_byte(round((x + 8) / 2))
            y_raw = self._clamp_byte(y + 16)
            part.set_artifact_slot(slot, room.index, x_raw, y_raw)
        elif obj == "apple":
            self.status.set("Apple placement is disabled for now: the previous 0xFD marker was only an editor preview and appears as garbage in the real game. Existing verified apples stay visible/read-only until the gameplay storage is decoded.")
            return
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
            self.status.set(f"Placed reflector R{idx} sprite={sprite_index} at x={x} y={y}. Use M{idx} in a control Targets field to rotate/control it.")
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
        elif kind == "control":
            room = self.current_room()
            delete_control_command(room, slot)
        elif kind == "crystal":
            room = self.current_room()
            delete_laser_crystal_entry(room, slot)
        elif kind == "decor":
            room = self.current_room()
            delete_visual_compact3_entry(room, slot)
        elif kind == "actor":
            self.status.set("Actor deletion is intentionally disabled for now; use properties to inspect actor fields.")
            return "break"
        elif kind == "known_pickup":
            self.status.set("This is a read-only verified apple marker; original apple storage is still unknown.")
            return "break"
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

    def atlas_categories(self):
        """Return a grouped catalog of recognized gameplay objects.

        Each item is (label, archive, resource_id, sprite_index, note).  The
        static sections are the object catalog/picker. Current-room sections are
        an inspector and are intentionally not used for placement.
        """
        static = [
            (
                "Actors / enemies",
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
                "Projectiles / secondary actors",
                [
                    ("Pill Projectile", "AE000", 20, 2, "020:2-7"),
                    ("Energy Orb", "AE000", 21, 0, "021:0-3"),
                    ("Fireball", "AE000", 21, 4, "021:4-8"),
                    ("Sparkles", "AE000", 22, 37, "022:37-40"),
                ],
            ),
            (
                "Pickups",
                [
                    *[(f"D{i} artifact", "AE000", 44, 0, f"artifact slot {i}") for i in range(6)],
                    ("Apple", "AE000", 45, 0, "verified collectible, schema still WIP"),
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
                "Puzzle symbols",
                [(f"Symbol {i}", "AE000", 10 + i, 0, f"AE000:{10 + i:03d}:0") for i in range(7)],
            ),
            (
                "Puzzle / moving blocks",
                [
                    ("Puzzle sequence block", "AE000", 17, 0, "section_b record12"),
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
                "Laser / reflectors",
                [
                    ("Reflector 0", "AE000", 19, 0, "section_c compact3"),
                    ("Reflector 2", "AE000", 19, 2, "special compact3 code 7D"),
                    ("Reflector 9", "AE000", 19, 9, "section_c compact3"),
                ],
            ),
            (
                "Ropes",
                [
                    ("Rope top", "AE000", 5, 0, "terrain 90"),
                    ("Rope middle long", "AE000", 6, 0, "terrain A0"),
                    ("Rope middle short", "AE000", 7, 0, "terrain B0"),
                    ("Rope bottom", "AE000", 8, 0, "terrain C0"),
                ],
            ),
        ]

        dynamic = []
        level = self.current_level()
        part = level.part(self.part_var.get())
        room = part.room(self.room_var.get())
        actors = []
        for actor in actor_records_for_room(part, room.index):
            if actor.hidden and not self.overlay_hidden_var.get():
                continue
            actors.append((
                f"A{actor.index} {actor.confirmed_name or 'actor'}",
                "AE000",
                self._actor_resource_id(actor.frame),
                self._actor_sprite_index(actor.frame),
                f"frame={actor.frame:02X} type={actor.actor_type} hidden={actor.hidden}",
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
            pickups.append((label, pickup.archive, pickup.resource_id, pickup.sprite_index, f"x={pickup.x} y={pickup.y} verified/screenshot"))
        if pickups:
            dynamic.append(("Current room: pickups", pickups))

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
        if lower_note.startswith("platform "):
            kind = lower_note.removeprefix("platform ").strip()
            return f"platform_{kind}" if kind in PLATFORM_KIND_FLAGS else None
        if archive == "AE000" and resource_id == 19:
            return f"reflector_{sprite_index & 0x3F}"
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
            ("apple", "Apple (read-only / storage WIP)", "AE000", 45, 0),
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

        self.object_palette_canvas.create_text(8, y, anchor="nw", text="Mechanics and gameplay objects", fill="#ffffff", font=category_font)
        y += 24
        for title, items in self.atlas_categories():
            if title.startswith("Current room:"):
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
        self.object_palette_canvas.config(scrollregion=(0, 0, 260, y + 8))

    def object_palette_click(self, event) -> None:
        if not hasattr(self, "editor_object_palette_hitboxes"):
            return
        x = int(self.object_palette_canvas.canvasx(event.x))
        y = int(self.object_palette_canvas.canvasy(event.y))
        for x0, y0, x1, y1, value in self.editor_object_palette_hitboxes:
            if x0 <= x <= x1 and y0 <= y <= y1:
                self.select_editor_object(value)
                self.status.set(f"Selected {value.replace('_', ' ')}. Click in the editor to place it.")
                return

    def redraw_actor_palette(self) -> None:
        if not hasattr(self, "actor_palette_canvas"):
            return
        self.actor_palette_canvas.delete("all")
        self.tk_actor_images = []
        self.actor_palette_hitboxes = []
        part = self.current_level().part(self.part_var.get())
        room = self.current_room()
        actors = actor_records_for_room(part, room.index)
        y = 8
        title_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        item_font = tkfont.Font(family="Segoe UI", size=9)
        note_font = tkfont.Font(family="Segoe UI", size=8)
        self.actor_palette_canvas.create_text(8, y, anchor="nw", text="Current room actors", fill="#ffffff", font=title_font)
        y += 26
        if not actors:
            self.actor_palette_canvas.create_text(8, y, anchor="nw", text="No actors in this room.", fill="#c8c8c8", font=item_font)
            y += 28
        for actor in actors:
            fill = "#4f6f8f" if self.editor_selected_ref == ("actor", actor.index) else "#343434"
            outline = "#9ed0ff" if not actor.hidden else "#777777"
            self.actor_palette_canvas.create_rectangle(8, y, 246, y + 52, outline=outline, fill=fill)
            self.actor_palette_hitboxes.append((8, y, 246, y + 52, actor.index))
            sprite = self.project.graphics.sprite("AE000", self._actor_resource_id(actor.frame), self._actor_sprite_index(actor.frame))
            if sprite is not None:
                thumb = sprite.copy()
                scale = min(2, max(1, 32 // max(1, max(thumb.size))))
                thumb = thumb.resize((max(1, thumb.width * scale), max(1, thumb.height * scale)), Image.Resampling.NEAREST)
                tk_img = ImageTk.PhotoImage(thumb)
                self.tk_actor_images.append(tk_img)
                self.actor_palette_canvas.create_image(30, y + 25, image=tk_img)
            name = actor.confirmed_name or "actor"
            self.actor_palette_canvas.create_text(56, y + 7, anchor="nw", text=f"A{actor.index} {name}", fill="#ffffff", font=item_font)
            note = f"frame={actor.frame:02X} var={actor.frame_variant:02X} hidden={actor.hidden}"
            self.actor_palette_canvas.create_text(56, y + 27, anchor="nw", text=note, fill="#c8c8c8", font=note_font)
            y += 58
        self.actor_palette_canvas.config(scrollregion=(0, 0, 260, y + 8))

    def actor_palette_click(self, event) -> None:
        if not hasattr(self, "actor_palette_hitboxes"):
            return
        x = int(self.actor_palette_canvas.canvasx(event.x))
        y = int(self.actor_palette_canvas.canvasy(event.y))
        for x0, y0, x1, y1, actor_index in self.actor_palette_hitboxes:
            if x0 <= x <= x1 and y0 <= y <= y1:
                self.editor_selected_ref = ("actor", actor_index)
                self.editor_drag_offset = None
                self.editor_tool_var.set("actor")
                if hasattr(self, "editor_palettes"):
                    self.editor_palettes.select(3)
                self.refresh_placeable_settings()
                self.redraw_actor_palette()
                self.redraw_editor_room()
                self.status.set(f"Selected actor A{actor_index}.")
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

    def _after_save(self, path: Path) -> None:
        self.title("Ancient Empires Level Editor")
        self.refresh_room_labels()
        self.redraw_room()
        self.redraw_objects_atlas()
        self.redraw_tile_palette()
        self.redraw_editor_object_palette()
        self.redraw_decor_palette()
        self.status.set(f"Saved AE001.DAT edits to {path}")

    def save_ae001(self) -> None:
        if not self.project.dirty:
            self.status.set("No edits to save.")
            return
        try:
            path = self.project.save_ae001()
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self._after_save(path)

    def save_ae001_as(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".DAT",
            initialfile="AE001_edited.DAT",
            filetypes=[("DAT archives", "*.DAT"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            saved = self.project.save_ae001(Path(path), backup=False)
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self._after_save(saved)

    def close_window(self) -> None:
        if self.project.dirty:
            choice = messagebox.askyesnocancel(
                "Unsaved edits",
                "Save AE001.DAT edits before closing?",
            )
            if choice is None:
                return
            if choice:
                self.save_ae001()
                if self.project.dirty:
                    return
        self.destroy()

    def export_current(self) -> None:
        diff = DIFFICULTY_LABELS[self.part_var.get()].lower()
        path = filedialog.asksaveasfilename(defaultextension=".png", initialfile=f"level_{self.level_var.get()+1:02d}_{diff}_room_{self.room_var.get():02d}.png")
        if path:
            self.current_image(zoom=1).save(path)

    def export_all_rooms(self) -> None:
        directory = filedialog.askdirectory(title="Export room previews")
        if directory:
            export_room_previews(self.project, Path(directory))

    def export_csv(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="ae_room_probe.csv")
        if path:
            export_probe_csv(self.project, Path(path))

    def export_sheets(self) -> None:
        directory = filedialog.askdirectory(title="Export bank sheets")
        if directory:
            export_bank_sheets(self.project, Path(directory))
