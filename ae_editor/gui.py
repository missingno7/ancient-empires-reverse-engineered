from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .constants import CELL_SIZE, ROOM_COUNT, ROOM_COLUMNS, ROOM_ROWS
from .exporters import export_bank_sheets, export_probe_csv, export_room_previews
from .overlay import build_room_overlay, control_ref_values, control_targets, decode_control_target
from .coordinates import control_xy, actor_xy
from .actor_scripts import decode_actor_script
from .actor_dsl import (
    ActorScriptError,
    Instruction,
    OPCODE_NAMES,
    decode_instruction,
    format_actor_ref,
    instruction_to_dsl,
    opcode_size,
    parse_actor_ref,
    parse_int,
)
from .coordinates import platform_xy
from .conveyors import iter_conveyor_runs
from .project import AncientEmpiresProject
from .renderer import RenderOptions, KnownExtraPickup
from .object_mapping import visual_sprite_ref
from .tile_mapping import AUTO_SOLID_TILE_CODES, CONVEYOR_PHYSICS_TILE_CODES, ROPE_TILE_CODES
from .audio import AudioItem, DEFAULT_PREVIEW_SPEED, build_audio_atlas, play_audio_file, synthesize_wav, temp_preview_wav, write_midi
from .room_payload import (
    actor_script_space,
    actor_script_space_reachable_addresses,
    actor_records_for_room,
    add_actor_record,
    parse_actor_table,
    control_commands,
    header_exit_door,
    header_object_candidates,
    header_player_start,
    laser_crystal_table,
    animated_decor_table,
    set_animated_decor_record,
    add_animated_decor_record,
    delete_animated_decor_record,
    room_apple_marker,
    set_room_apple_marker,
    clear_room_apple_marker,
    section_a_symbol_table,
    set_section_a_symbol_entry,
    add_section_a_symbol_entry,
    delete_section_a_symbol_entry,
    record12_green_block_records,
    set_record12_green_block,
    add_record12_green_block,
    delete_record12_green_block,
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
    patch_actor_script_region,
    delete_actor_record,
    room_cell_for_runtime_offset,
    runtime_offset_for_room_cell,
    tile_at_runtime_offset,
    set_actor_record_flags,
    set_actor_record_placement,
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
    "Select an artifact, platform, CV, belt, control, actor, symbol, green block, decor decal, or reflector first."
)
SCRIPT_PARAM_SPECS = {
    0x01: (("target", "target"),),
    0x02: (("target", "target"),),
    0x04: (("target", "target"), ("count", "count")),
    0x05: (("target", "target"), ("count", "count")),
    0x06: (("target", "target"), ("count", "count")),
    0x07: (("id", "sound id"),),
    0x08: (("id", "control id"),),
    0x09: (("id", "symbol id"),),
    0x0A: (("actor", "actor"),),
    0x0B: (("actor", "actor"),),
    0x0C: (("min", "min frame"), ("max", "max frame")),
    0x0D: (("frame", "frame"),),
    0x0E: (("dx", "dx"), ("dy", "dy"), ("frame_delta", "frame delta")),
    0x0F: (("x_raw", "x raw"), ("y", "y"), ("frame_delta", "frame delta")),
    0x10: (("x_raw", "x raw"), ("y", "y"), ("frame", "frame"), ("room", "room")),
    0x13: (("room", "room"), ("x", "tile x"), ("y", "tile y")),
    0x14: (("room", "room"), ("x", "tile x"), ("y", "tile y")),
    0x15: (("room", "room"), ("x", "tile x"), ("y", "tile y")),
    0x16: (("room", "room"), ("x", "tile x"), ("y", "tile y")),
    0x17: (("value", "value"),),
    0x18: (("value", "value"),),
    0x19: (("value", "value"),),
    0x1A: (("value", "value"),),
    0x1B: (("value", "value"),),
}
SCRIPT_OPCODE_VALUES = [OPCODE_NAMES[opcode] for opcode in sorted(OPCODE_NAMES)]


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


@dataclass(frozen=True)
class ActorTemplateSpec:
    key: str
    label: str
    archive: str
    resource_id: int
    sprite_index: int
    frame_min: int
    frame_max: int
    actor_type: int = 0

    @property
    def frame(self) -> int:
        return self.frame_min


OVERLAY_OPTION_SPECS = (
    OverlayOptionSpec("Platforms", "show_platforms_var", True, True, True, True),
    OverlayOptionSpec("Platform paths", "show_platform_paths_var", False, False, True, True),
    OverlayOptionSpec("Conveyors", "show_conveyors_var", False, False, True, True),
    OverlayOptionSpec("Controls", "show_controls_var", True, True, True, True),
    OverlayOptionSpec("Trigger links", "show_trigger_links_var", False, False, True, True),
    OverlayOptionSpec("Symbol buttons", "show_puzzle_markers_var", True, True, True, True),
    OverlayOptionSpec("Green block alternate", "show_puzzle_blocks_var", True, True, True, True),
    OverlayOptionSpec("Green block default", "show_puzzle_destinations_var", True, True, True, True),
    OverlayOptionSpec("Symbol links", "show_puzzle_links_var", False, False, True, True),
    OverlayOptionSpec("Green block moves", "show_puzzle_move_links_var", True, True, True, True),
    OverlayOptionSpec("Actors", "show_actors_var", True, True, True, True),
    OverlayOptionSpec("Actor paths", "show_actor_paths_var", False, False, True, True),
    OverlayOptionSpec("Projectile links", "show_projectile_links_var", True, False, True, True),
    OverlayOptionSpec("Pickups", "show_pickups_var", True, True, True, True),
    OverlayOptionSpec("Crystals", "show_crystals_var", True, True, True, True),
    OverlayOptionSpec("Exits", "show_exits_var", False, False, False, True),
)

ACTOR_TEMPLATE_SPECS = (
    ActorTemplateSpec("ant", "Ant", "AE000", 20, 0, 0x00, 0x01),
    ActorTemplateSpec("pill_projectile", "Pill Projectile", "AE000", 20, 2, 0x02, 0x07, 1),
    ActorTemplateSpec("bat", "Bat", "AE000", 20, 8, 0x08, 0x0E),
    ActorTemplateSpec("praying_mantis", "Praying Mantis", "AE000", 20, 15, 0x0F, 0x16),
    ActorTemplateSpec("energy_orb", "Energy Orb", "AE000", 21, 0, 0x17, 0x1A, 1),
    ActorTemplateSpec("fireball", "Fireball", "AE000", 21, 4, 0x1B, 0x1F, 1),
    ActorTemplateSpec("pegasus_frog", "Pegasus Frog", "AE000", 21, 9, 0x20, 0x2A),
    ActorTemplateSpec("ladybug", "Ladybug", "AE000", 22, 0, 0x2B, 0x2C),
    ActorTemplateSpec("scarab", "Scarab", "AE000", 22, 2, 0x2D, 0x31),
    ActorTemplateSpec("scorpion", "Scorpion", "AE000", 22, 7, 0x32, 0x36),
    ActorTemplateSpec("spider", "Spider", "AE000", 22, 12, 0x37, 0x3A),
    ActorTemplateSpec("neon_spider", "Neon Spider", "AE000", 22, 16, 0x3B, 0x3E),
    ActorTemplateSpec("snake", "Snake", "AE000", 22, 20, 0x3F, 0x41),
    ActorTemplateSpec("flea", "Flea", "AE000", 22, 23, 0x42, 0x49),
    ActorTemplateSpec("caterpillar", "Caterpillar", "AE000", 22, 31, 0x4A, 0x4F),
    ActorTemplateSpec("sparkles", "Sparkles", "AE000", 22, 37, 0x50, 0x53, 1),
)
ACTOR_TEMPLATE_BY_KEY = {spec.key: spec for spec in ACTOR_TEMPLATE_SPECS}


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
        self.audio_items: list[AudioItem] = []
        self.audio_item_by_key: dict[str, AudioItem] = {}
        self.audio_selected_key: str | None = None
        self.audio_info_var = tk.StringVar(value="")
        self.audio_speed_var = tk.StringVar(value=f"{DEFAULT_PREVIEW_SPEED:g}")

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
        scripting_tab = ttk.Frame(tabs)
        graphics_tab = ttk.Frame(tabs)
        objects_tab = ttk.Frame(tabs)
        audio_tab = ttk.Frame(tabs)
        tabs.add(level_tab, text="Level viewer")
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

    def _build_audio_tab(self, audio_tab: ttk.Frame) -> None:
        top = ttk.Frame(audio_tab)
        top.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(top, text="Audio atlas: PC speaker + sound-card audio").pack(side=tk.LEFT)
        ttk.Button(top, text="Refresh", command=self.refresh_audio_atlas).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(top, text="Preview speed ×").pack(side=tk.LEFT, padx=(12, 0))
        ttk.Spinbox(top, from_=0.25, to=6.0, increment=0.25, width=5, textvariable=self.audio_speed_var).pack(side=tk.LEFT, padx=(2, 0))
        ttk.Button(top, text="Play preview", command=self.play_selected_audio).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(top, text="Export WAV preview", command=self.export_selected_audio_wav).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(top, text="Export raw", command=self.export_selected_audio_raw).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(top, text="Export MIDI", command=self.export_selected_audio_midi).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(
            audio_tab,
            text=(
                "play_sound/event_07 uses the CAF1 PC-speaker sound-effect bank. "
                "Music has PC-speaker and AdLib/Sound Blaster resource pairs. "
                "Preview speed is adjustable; PC-speaker music currently matches the game best around 1.75×. "
                "Raw export preserves the exact in-game bytes; MIDI export is a best-effort transcription for music candidates."
            ),
            justify=tk.LEFT,
            wraplength=1100,
        ).pack(fill=tk.X, padx=6, pady=(0, 4))

        body = ttk.PanedWindow(audio_tab, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=3)
        body.add(right, weight=2)

        columns = ("kind", "code", "source", "offset", "length", "notes")
        self.audio_tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        headings = {
            "kind": "Kind",
            "code": "Code / label",
            "source": "Source",
            "offset": "Offset",
            "length": "Bytes",
            "notes": "Notes",
        }
        widths = {"kind": 72, "code": 180, "source": 115, "offset": 78, "length": 70, "notes": 360}
        for col in columns:
            self.audio_tree.heading(col, text=headings[col])
            self.audio_tree.column(col, width=widths[col], anchor="w")
        yscroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.audio_tree.yview)
        self.audio_tree.configure(yscrollcommand=yscroll.set)
        self.audio_tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.audio_tree.bind("<<TreeviewSelect>>", self.on_audio_select)
        self.audio_tree.bind("<Double-1>", lambda _event: self.play_selected_audio())

        ttk.Label(right, text="Selected audio").pack(anchor="w")
        ttk.Label(right, textvariable=self.audio_info_var, justify=tk.LEFT, wraplength=420).pack(fill=tk.X, pady=(4, 8))
        ttk.Label(right, text="Hex preview").pack(anchor="w")
        self.audio_hex_text = tk.Text(right, height=24, width=58, wrap="none")
        self.audio_hex_text.pack(fill=tk.BOTH, expand=True)

        self.refresh_audio_atlas()

    def refresh_audio_atlas(self) -> None:
        if not hasattr(self, "audio_tree"):
            return
        self.audio_items = build_audio_atlas(self.project)
        self.audio_item_by_key = {item.key: item for item in self.audio_items}
        self.audio_tree.delete(*self.audio_tree.get_children())
        for item in self.audio_items:
            source = f"{item.archive_name}:{item.resource_index:03d}"
            offset = f"0x{item.offset:04X}" if item.offset is not None else "-"
            code = item.label
            self.audio_tree.insert("", tk.END, iid=item.key, values=(item.kind, code, source, offset, item.length, item.notes))
        self.audio_info_var.set(f"Found {len(self.audio_items)} audio entries.")
        self.audio_hex_text.delete("1.0", tk.END)

    def on_audio_select(self, _event=None) -> None:
        selection = self.audio_tree.selection() if hasattr(self, "audio_tree") else ()
        self.audio_selected_key = selection[0] if selection else None
        item = self.audio_item_by_key.get(self.audio_selected_key or "")
        if item is None:
            return
        source = f"{item.archive_name}:{item.resource_index:03d}"
        lines = [
            f"{item.label}",
            f"kind: {item.kind}",
            f"source: {source}, type 0x{item.resource_type:02X}",
            f"offset: {f'0x{item.offset:04X}' if item.offset is not None else '-'}",
            f"length: {item.length} bytes",
            "",
            item.notes,
        ]
        if item.kind == "pc-speaker-sfx":
            lines.append("This is the id used by actor script play_sound/event_07. CAF1 appears to drive the PC speaker, not AdLib SFX.")
        elif item.kind == "soundcard-music":
            lines.append("AdLib/Sound Blaster music mix resource with multiple channel streams.")
        elif item.kind == "soundcard-channel":
            lines.append("Single channel from an AdLib/Sound Blaster music resource.")
        elif item.kind == "pc-speaker-music":
            lines.append("PC-speaker version of a music resource.")
        else:
            lines.append("Raw audio/patch resource; export raw for now.")
        self.audio_info_var.set("\n".join(lines))
        data = item.data[:512]
        hex_lines = []
        for i in range(0, len(data), 16):
            row = data[i:i+16]
            hex_part = " ".join(f"{b:02X}" for b in row)
            ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
            base = item.offset or 0
            hex_lines.append(f"{base+i:04X}: {hex_part:<47}  {ascii_part}")
        self.audio_hex_text.delete("1.0", tk.END)
        self.audio_hex_text.insert("1.0", "\n".join(hex_lines))

    def _audio_preview_speed(self) -> float:
        try:
            return max(0.10, min(8.0, float(self.audio_speed_var.get().replace(",", "."))))
        except Exception:
            return DEFAULT_PREVIEW_SPEED

    def _selected_audio_item(self) -> AudioItem | None:
        if not self.audio_selected_key and hasattr(self, "audio_tree"):
            selection = self.audio_tree.selection()
            self.audio_selected_key = selection[0] if selection else None
        item = self.audio_item_by_key.get(self.audio_selected_key or "")
        if item is None:
            messagebox.showinfo("Audio atlas", "Select a sound or music item first.")
        return item

    def play_selected_audio(self) -> None:
        item = self._selected_audio_item()
        if item is None:
            return
        try:
            wav_path = temp_preview_wav(item, speed=self._audio_preview_speed())
            play_audio_file(wav_path)
            self.status.set(f"Playing synthesized preview for {item.label}")
        except Exception as exc:
            messagebox.showerror("Audio playback failed", str(exc))

    def export_selected_audio_wav(self) -> None:
        item = self._selected_audio_item()
        if item is None:
            return
        default = (item.label.replace("/", "_").replace(" ", "_").replace(":", "") + ".wav")
        path = filedialog.asksaveasfilename(defaultextension=".wav", initialfile=default, filetypes=[("WAV audio", "*.wav")])
        if not path:
            return
        try:
            synthesize_wav(item.data, path, music=item.kind != "pc-speaker-sfx", speed=self._audio_preview_speed())
            self.status.set(f"Exported WAV preview: {path}")
        except Exception as exc:
            messagebox.showerror("WAV export failed", str(exc))

    def export_selected_audio_raw(self) -> None:
        item = self._selected_audio_item()
        if item is None:
            return
        ext = ".ae_sfx" if item.kind == "pc-speaker-sfx" else (".ae_music" if "music" in item.kind or item.kind in {"pc-speaker-music", "soundcard-channel"} else ".ae_audio")
        default = item.label.replace("/", "_").replace(" ", "_").replace(":", "") + ext
        path = filedialog.asksaveasfilename(defaultextension=ext, initialfile=default, filetypes=[("In-game audio bytes", f"*{ext}"), ("All files", "*.*")])
        if not path:
            return
        try:
            Path(path).write_bytes(item.data)
            self.status.set(f"Exported raw in-game audio bytes: {path}")
        except Exception as exc:
            messagebox.showerror("Raw export failed", str(exc))

    def export_selected_audio_midi(self) -> None:
        item = self._selected_audio_item()
        if item is None:
            return
        if item.kind not in {"soundcard-music", "soundcard-channel", "pc-speaker-music"}:
            if not messagebox.askyesno("MIDI export", "This is not classified as music. Export a rough MIDI transcription anyway?"):
                return
        default = item.label.replace("/", "_").replace(" ", "_").replace(":", "") + ".mid"
        path = filedialog.asksaveasfilename(defaultextension=".mid", initialfile=default, filetypes=[("MIDI file", "*.mid")])
        if not path:
            return
        try:
            write_midi(item.data, path, speed=self._audio_preview_speed())
            self.status.set(f"Exported best-effort MIDI: {path}")
        except Exception as exc:
            messagebox.showerror("MIDI export failed", str(exc))

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

    def _build_actor_scripting_tab(self, scripting_tab: ttk.Frame) -> None:
        main = ttk.PanedWindow(scripting_tab, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left, weight=1)
        main.add(right, weight=4)

        ttk.Label(left, text="Current room actors").pack(anchor="w", padx=6, pady=(6, 2))
        actor_frame = ttk.Frame(left)
        actor_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self.scripting_actor_tree = ttk.Treeview(
            actor_frame,
            columns=("name", "script", "restart"),
            show="headings",
            selectmode="browse",
            height=14,
        )
        self.scripting_actor_tree.heading("name", text="Actor")
        self.scripting_actor_tree.heading("script", text="script_pc")
        self.scripting_actor_tree.heading("restart", text="restart")
        self.scripting_actor_tree.column("name", width=130, stretch=True)
        self.scripting_actor_tree.column("script", width=70, stretch=False)
        self.scripting_actor_tree.column("restart", width=70, stretch=False)
        actor_scroll = ttk.Scrollbar(actor_frame, orient=tk.VERTICAL, command=self.scripting_actor_tree.yview)
        self.scripting_actor_tree.configure(yscrollcommand=actor_scroll.set)
        self.scripting_actor_tree.grid(row=0, column=0, sticky="nsew")
        actor_scroll.grid(row=0, column=1, sticky="ns")
        actor_frame.rowconfigure(0, weight=1)
        actor_frame.columnconfigure(0, weight=1)
        self.scripting_actor_tree.bind("<<TreeviewSelect>>", self.on_scripting_actor_selected)

        ttk.Label(left, textvariable=self.scripting_status_var, wraplength=260, justify=tk.LEFT).pack(fill=tk.X, padx=6, pady=(0, 6))

        top = ttk.Frame(right)
        top.pack(fill=tk.X, padx=6, pady=(6, 4))
        ttk.Label(top, textvariable=self.scripting_actor_title_var, font=tkfont.Font(family="Segoe UI", size=11, weight="bold")).pack(side=tk.LEFT)
        ttk.Button(top, text="Reload", command=self.reload_selected_actor_script).pack(side=tk.RIGHT)
        ttk.Button(top, text="Open address", command=self.open_script_address_from_field).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Entry(top, textvariable=self.scripting_address_var, width=10).pack(side=tk.RIGHT)
        ttk.Label(top, text="Address").pack(side=tk.RIGHT, padx=(12, 4))

        ttk.Label(right, textvariable=self.scripting_summary_var, wraplength=760, justify=tk.LEFT).pack(fill=tk.X, padx=6, pady=(0, 6))

        content = ttk.PanedWindow(right, orient=tk.VERTICAL)
        content.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        upper = ttk.Frame(content)
        lower = ttk.Frame(content)
        content.add(upper, weight=3)
        content.add(lower, weight=2)

        instruction_frame = ttk.Frame(upper)
        instruction_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scripting_instruction_tree = ttk.Treeview(
            instruction_frame,
            columns=("offset", "instruction"),
            show="headings",
            selectmode="browse",
        )
        self.scripting_instruction_tree.heading("offset", text="Addr")
        self.scripting_instruction_tree.heading("instruction", text="Instruction")
        self.scripting_instruction_tree.column("offset", width=76, stretch=False)
        self.scripting_instruction_tree.column("instruction", width=510, stretch=True)
        instruction_scroll = ttk.Scrollbar(instruction_frame, orient=tk.VERTICAL, command=self.scripting_instruction_tree.yview)
        self.scripting_instruction_tree.configure(yscrollcommand=instruction_scroll.set)
        self.scripting_instruction_tree.grid(row=0, column=0, sticky="nsew")
        instruction_scroll.grid(row=0, column=1, sticky="ns")
        instruction_frame.rowconfigure(0, weight=1)
        instruction_frame.columnconfigure(0, weight=1)
        self.scripting_instruction_tree.bind("<<TreeviewSelect>>", self.on_scripting_instruction_selected)

        detail = ttk.LabelFrame(upper, text="Instruction")
        detail.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        ttk.Label(detail, text="Opcode").grid(row=0, column=0, sticky="e", padx=(6, 2), pady=(8, 2))
        self.scripting_opcode_combo = ttk.Combobox(
            detail,
            state="readonly",
            values=SCRIPT_OPCODE_VALUES,
            textvariable=self.scripting_opcode_var,
            width=24,
        )
        self.scripting_opcode_combo.grid(row=0, column=1, sticky="ew", padx=(0, 6), pady=(8, 2))
        self.scripting_opcode_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_script_param_fields())
        self.scripting_param_rows = []
        self.scripting_param_vars = []
        for row in range(4):
            label = ttk.Label(detail, text=f"Arg {row + 1}")
            var = tk.StringVar(value="")
            entry = ttk.Entry(detail, textvariable=var, width=26)
            label.grid(row=1 + row, column=0, sticky="e", padx=(6, 2), pady=2)
            entry.grid(row=1 + row, column=1, sticky="ew", padx=(0, 6), pady=2)
            self.scripting_param_rows.append((label, entry))
            self.scripting_param_vars.append(var)
        button_row = ttk.Frame(detail)
        button_row.grid(row=5, column=0, columnspan=2, sticky="ew", padx=6, pady=(8, 6))
        ttk.Button(button_row, text="Apply", command=self.apply_script_instruction_edit).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(button_row, text="Add", command=self.add_script_instruction).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        ttk.Button(button_row, text="Remove", command=self.remove_script_instruction).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        ttk.Button(detail, text="Write region", command=self.write_actor_script_bytes).grid(row=6, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 8))
        detail.columnconfigure(1, weight=1)

        bottom_tabs = ttk.Notebook(lower)
        bottom_tabs.pack(fill=tk.BOTH, expand=True)
        dsl_tab = ttk.Frame(bottom_tabs)
        branch_tab = ttk.Frame(bottom_tabs)
        refs_tab = ttk.Frame(bottom_tabs)
        bottom_tabs.add(dsl_tab, text="DSL preview")
        bottom_tabs.add(branch_tab, text="Branches")
        bottom_tabs.add(refs_tab, text="References")

        self.scripting_dsl_text = tk.Text(dsl_tab, height=8, wrap="none", font=("Consolas", 9), state=tk.DISABLED)
        dsl_y = ttk.Scrollbar(dsl_tab, orient=tk.VERTICAL, command=self.scripting_dsl_text.yview)
        dsl_x = ttk.Scrollbar(dsl_tab, orient=tk.HORIZONTAL, command=self.scripting_dsl_text.xview)
        self.scripting_dsl_text.configure(yscrollcommand=dsl_y.set, xscrollcommand=dsl_x.set)
        self.scripting_dsl_text.grid(row=0, column=0, sticky="nsew")
        dsl_y.grid(row=0, column=1, sticky="ns")
        dsl_x.grid(row=1, column=0, sticky="ew")
        dsl_tab.rowconfigure(0, weight=1)
        dsl_tab.columnconfigure(0, weight=1)

        self.scripting_branch_tree = ttk.Treeview(branch_tab, columns=("branch", "conditions", "steps"), show="headings")
        self.scripting_branch_tree.heading("branch", text="#")
        self.scripting_branch_tree.heading("conditions", text="Conditions")
        self.scripting_branch_tree.heading("steps", text="Steps")
        self.scripting_branch_tree.column("branch", width=42, stretch=False)
        self.scripting_branch_tree.column("conditions", width=260, stretch=True)
        self.scripting_branch_tree.column("steps", width=460, stretch=True)
        branch_scroll = ttk.Scrollbar(branch_tab, orient=tk.VERTICAL, command=self.scripting_branch_tree.yview)
        self.scripting_branch_tree.configure(yscrollcommand=branch_scroll.set)
        self.scripting_branch_tree.grid(row=0, column=0, sticky="nsew")
        branch_scroll.grid(row=0, column=1, sticky="ns")
        branch_tab.rowconfigure(0, weight=1)
        branch_tab.columnconfigure(0, weight=1)

        self.scripting_refs_tree = ttk.Treeview(refs_tab, columns=("kind", "source", "detail"), show="headings")
        self.scripting_refs_tree.heading("kind", text="Kind")
        self.scripting_refs_tree.heading("source", text="Where")
        self.scripting_refs_tree.heading("detail", text="Detail")
        self.scripting_refs_tree.column("kind", width=110, stretch=False)
        self.scripting_refs_tree.column("source", width=150, stretch=False)
        self.scripting_refs_tree.column("detail", width=520, stretch=True)
        refs_scroll = ttk.Scrollbar(refs_tab, orient=tk.VERTICAL, command=self.scripting_refs_tree.yview)
        self.scripting_refs_tree.configure(yscrollcommand=refs_scroll.set)
        self.scripting_refs_tree.grid(row=0, column=0, sticky="nsew")
        refs_scroll.grid(row=0, column=1, sticky="ns")
        refs_tab.rowconfigure(0, weight=1)
        refs_tab.columnconfigure(0, weight=1)

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
            grid=self.grid_var.get(),
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

    def _selected_scripting_actor(self):
        if self.scripting_selected_actor_index is None:
            return None
        return next((actor for actor in self._current_room_actors() if actor.index == self.scripting_selected_actor_index), None)

    def _actor_by_index(self, part, index: int):
        return next((actor for actor in parse_actor_table(part) if actor.index == index), None)

    def _actor_selected_for_script_sharing(self):
        part = self.current_level().part(self.part_var.get())
        # Actor behavior bytecode is global for the whole level part, so keep the
        # last explicitly selected actor as a share source even after switching rooms.
        if self.actor_script_share_source_index is not None:
            actor = self._actor_by_index(part, self.actor_script_share_source_index)
            if actor is not None:
                return actor
        if self.editor_selected_ref is not None and self.editor_selected_ref[0] == "actor":
            actor = self._actor_by_index(part, int(self.editor_selected_ref[1]))
            if actor is not None:
                return actor
        if self.scripting_selected_actor_index is not None:
            actor = self._actor_by_index(part, self.scripting_selected_actor_index)
            if actor is not None:
                return actor
        actors = self._current_room_actors()
        return actors[0] if actors else None

    def _format_actor_short(self, actor) -> str:
        if actor is None:
            return "unknown actor"
        name = actor.confirmed_name or f"frame {actor.frame:02X}"
        hidden = " hidden" if actor.hidden else ""
        return f"A{actor.index} {name} room={actor.room_index}{hidden}"

    def open_script_address_from_field(self) -> None:
        try:
            address = self._parse_actor_addr(self.scripting_address_var.get())
        except ValueError as exc:
            messagebox.showerror("Invalid script address", str(exc))
            return
        self.scripting_selected_address = address
        self.scripting_selected_actor_index = None
        if hasattr(self, "scripting_actor_tree"):
            self.scripting_actor_tree.selection_remove(*self.scripting_actor_tree.selection())
        self.reload_selected_actor_script()

    def refresh_actor_scripting_tab(self) -> None:
        if not hasattr(self, "scripting_actor_tree"):
            return
        actors = self._current_room_actors()
        valid_indices = {actor.index for actor in actors}
        if self.scripting_selected_actor_index not in valid_indices:
            self.scripting_selected_actor_index = actors[0].index if actors else None
            self.scripting_selected_address = None if self.scripting_selected_actor_index is None else actors[0].script_offset

        self.scripting_actor_tree.delete(*self.scripting_actor_tree.get_children())
        for actor in actors:
            name = actor.confirmed_name or f"frame {actor.frame:02X}"
            hidden = " hidden" if actor.hidden else ""
            iid = str(actor.index)
            self.scripting_actor_tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(f"A{actor.index} {name}{hidden}", f"{actor.script_offset:04X}", f"{actor.restart_script_offset:04X}"),
            )
        if self.scripting_selected_actor_index is not None:
            self.scripting_actor_tree.selection_set(str(self.scripting_selected_actor_index))
            self.scripting_actor_tree.focus(str(self.scripting_selected_actor_index))
        self.reload_selected_actor_script()

    def on_scripting_actor_selected(self, _event=None) -> None:
        if not hasattr(self, "scripting_actor_tree"):
            return
        selected = self.scripting_actor_tree.selection()
        if not selected:
            return
        self.scripting_selected_actor_index = int(selected[0])
        self.actor_script_share_source_index = self.scripting_selected_actor_index
        actor = self._selected_scripting_actor()
        self.scripting_selected_address = None if actor is None else actor.script_offset
        self.reload_selected_actor_script()

    def reload_selected_actor_script(self) -> None:
        if not hasattr(self, "scripting_instruction_tree"):
            return
        actor = self._selected_scripting_actor()
        self.scripting_instructions = []
        self.scripting_decoded = None
        self.scripting_script_start = None
        self.scripting_original_len = 0
        self.scripting_region_writable = False
        self.scripting_visible_addresses = []
        part = self.current_level().part(self.part_var.get())
        if actor is not None and self.scripting_selected_address is None:
            self.scripting_selected_address = actor.script_offset
        address = self.scripting_selected_address
        if address is None:
            self.scripting_actor_title_var.set("No script space address selected")
            self.scripting_summary_var.set("")
            self.scripting_status_var.set("This room has no actor records.")
            self._set_script_text("")
            self.refresh_script_instruction_tree()
            self.refresh_script_branch_tree()
            self.refresh_script_refs_tree()
            return

        self.scripting_address_var.set(self._format_actor_addr(address))
        space = actor_script_space(part)
        self.scripting_space = space
        addresses = actor_script_space_reachable_addresses(space, address)
        self.scripting_visible_addresses = addresses
        by_address = space.instruction_by_address
        try:
            instructions = [decode_instruction(space.raw, addr) for addr in addresses]
            self.scripting_instructions = self._instructions_with_stable_targets(instructions)
            self.scripting_script_start = address
            self.scripting_region_writable = self._script_view_is_contiguous()
            if self.scripting_region_writable and self.scripting_instructions:
                first = self.scripting_instructions[0].offset
                last = self.scripting_instructions[-1]
                self.scripting_original_len = last.offset + last.byte_size() - first
                status = f"Decoded {len(self.scripting_instructions)} reachable script-space instructions from {self._format_actor_addr(first)} ({self.scripting_original_len} contiguous bytes)."
            else:
                self.scripting_original_len = 0
                status = f"Decoded {len(self.scripting_instructions)} reachable script-space instructions; view is non-contiguous/read-only until the central repacker can split shared routines."
        except ActorScriptError as exc:
            self.scripting_instructions = []
            self.scripting_original_len = 0
            status = f"Script decode error: {exc}"

        title = f"Script space @ {self._format_actor_addr(address)}"
        if actor is not None:
            title += f" from {self._format_actor_short(actor)}"
            decoded = decode_actor_script(part, actor, max_bytes=192, max_segments=16)
            self.scripting_decoded = decoded
            summary = self._format_runtime_offsets_in_text(decoded.summary)
        else:
            summary = "Address view opened directly; actor path summary is only available when an actor entry point is selected."
        self.scripting_actor_title_var.set(title)
        self.scripting_summary_var.set(self._script_space_summary(space, address, actor, summary))
        self.scripting_status_var.set(status)
        self.refresh_script_instruction_tree()
        self.refresh_script_branch_tree()
        self.refresh_script_refs_tree()
        self.update_script_dsl_preview()

    def _instructions_with_stable_targets(self, instructions: list[Instruction]) -> list[Instruction]:
        offsets = {ins.offset for ins in instructions}
        target_labels: dict[int, str] = {}
        for ins in instructions:
            target = ins.target_offset()
            if target is not None and target in offsets:
                target_labels.setdefault(target, f"L{target:04X}")
        out: list[Instruction] = []
        for ins in instructions:
            target = ins.target_offset()
            label = ins.label or target_labels.get(ins.offset)
            if target is not None and target in target_labels:
                if ins.opcode in {0x04, 0x05, 0x06}:
                    args = (ins.args[1],)
                else:
                    args = ()
                out.append(Instruction(ins.opcode, args, label, target_labels[target], ins.offset, ins.raw))
            else:
                out.append(Instruction(ins.opcode, tuple(ins.args), label, ins.target_label, ins.offset, ins.raw))
        return out

    def _script_view_is_contiguous(self) -> bool:
        if not self.scripting_instructions:
            return False
        if self.scripting_selected_address is not None and self.scripting_instructions[0].offset != self.scripting_selected_address:
            return False
        expected = self.scripting_instructions[0].offset
        for ins in self.scripting_instructions:
            if ins.offset != expected:
                return False
            expected += ins.byte_size()
        return True

    def _reflow_script_instruction_offsets(self) -> None:
        if not self.scripting_instructions:
            return
        offset = self.scripting_instructions[0].offset
        for ins in self.scripting_instructions:
            ins.offset = offset
            offset += ins.byte_size()

    def _script_space_summary(self, space, address: int, actor, actor_summary: str) -> str:
        part = self.current_level().part(self.part_var.get())
        actors = {a.index: a for a in parse_actor_table(part)}
        entries = [entry for entry in space.entry_points if entry.address == address]
        incoming = [jump for jump in space.jumps if jump.target == address]
        outgoing = [jump for jump in space.jumps if jump.source in set(self.scripting_visible_addresses)]
        shared = [entry for entry in entries if entry.field in {"script_pc", "restart_pc"}]
        entry_text = ", ".join(f"A{entry.actor_index}.{entry.field}" for entry in entries) or "none"
        shared_text = ", ".join(self._format_actor_short(actors.get(entry.actor_index)) for entry in shared) or "none"
        incoming_text = ", ".join(f"0x{jump.source:04X}" for jump in incoming[:8]) or "none"
        outgoing_text = ", ".join(f"0x{jump.source:04X}->0x{jump.target:04X}" for jump in outgoing[:8]) or "none"
        actor_text = "" if actor is None else (
            f" Actor state: script_pc=0x{actor.script_offset:04X}, restart_pc=0x{actor.restart_script_offset:04X}, "
            f"saved_pc=0x{actor.saved_script_offset:04X}, loops={actor.loop_counter_a}/{actor.loop_counter_b}/{actor.loop_counter_c}."
        )
        return (
            f"{actor_summary}{actor_text} Entry refs: {entry_text}. "
            f"Actors sharing this entry: {shared_text}. Incoming jumps: {incoming_text}. Outgoing jumps in view: {outgoing_text}."
        )

    def _selected_script_base(self) -> int:
        return 0

    def _script_label_offsets(self) -> dict[str, int]:
        return {ins.label: ins.offset for ins in self.scripting_instructions if ins.label}

    def _instruction_target_local(self, ins: Instruction) -> int | None:
        if ins.target_label:
            return self._script_label_offsets().get(ins.target_label)
        return ins.target_offset()

    def _instruction_target_abs(self, ins: Instruction) -> int | None:
        return self._instruction_target_local(ins)

    def _format_actor_addr(self, value: int) -> str:
        return f"0x{value:04X}"

    def _parse_actor_addr(self, text: str) -> int:
        value = text.strip()
        if not value:
            raise ValueError("target address is required")
        if value.lower().startswith("addr="):
            value = value.split("=", 1)[1].strip()
        if value.upper().startswith("A") and len(value) > 1:
            value = value[1:]
        # Script-space addresses are shown everywhere as hex.  For consistency,
        # bare values in this field are hex too: 565 == 0x0565, not decimal 565.
        if value.lower().startswith("0x") or value.lower().startswith("-0x"):
            return parse_int(value)
        return int(value, 16)

    def _ensure_script_target_label(self, target_address: int) -> str | None:
        for ins in self.scripting_instructions:
            if ins.offset == target_address:
                if not ins.label:
                    ins.label = f"L{target_address:04X}"
                return ins.label
        return None

    def _script_labels_by_offset(self) -> dict[int, str]:
        labels: dict[int, str] = {}
        offsets = {ins.offset for ins in self.scripting_instructions}
        for ins in self.scripting_instructions:
            target = ins.target_offset()
            if target is not None and target in offsets:
                labels.setdefault(target, f"L{target:04X}")
        for ins in self.scripting_instructions:
            if ins.label:
                labels[ins.offset] = ins.label
        return labels

    def _script_instruction_display(self, ins: Instruction, labels: dict[int, str]) -> str:
        if ins.opcode in {0x13, 0x14, 0x15, 0x16} and ins.args:
            return self._runtime_condition_text(ins.opcode, ins.args[0])
        if ins.opcode in {0x01, 0x02, 0x04, 0x05, 0x06}:
            target = self._instruction_target_abs(ins)
            target_text = "?" if target is None else self._format_actor_addr(target)
            if ins.opcode in {0x04, 0x05, 0x06}:
                count = ins.args[0] if ins.target_label else (ins.args[1] if len(ins.args) > 1 else 1)
                return f"{ins.mnemonic} target={target_text} count={count}"
            return f"{ins.mnemonic} target={target_text}"
        return instruction_to_dsl(ins, labels)

    def _runtime_condition_text(self, opcode: int, offset: int) -> str:
        checks = {
            0x13: "solid: tile lowbits > 0",
            0x14: "passable: tile lowbits = 0",
            0x15: "grey conveyor: tile 0x0F / bit 0x10 clear",
            0x16: "teal conveyor: tile 0x1F / bit 0x10 set",
        }
        cell = room_cell_for_runtime_offset(offset)
        tile = tile_at_runtime_offset(self.current_level().part(self.part_var.get()), offset)
        tile_text = "??" if tile is None else f"{tile:02X}"
        if cell is None:
            return f"{OPCODE_NAMES[opcode]} offset=0x{offset:04X} ({checks[opcode]}, tile={tile_text})"
        room_index, x, y = cell
        return f"{OPCODE_NAMES[opcode]} room={room_index} x={x} y={y} tile={tile_text} ({checks[opcode]})"

    def _format_branch_conditions(self, conditions: tuple[str, ...]) -> str:
        out: list[str] = []
        for condition in conditions:
            negated = condition.startswith("not(") and condition.endswith(")")
            inner = condition[4:-1] if negated else condition
            text = inner
            marker = " offset="
            if marker in inner:
                prefix, offset_text = inner.split(marker, 1)
                try:
                    offset = int(offset_text[:4], 16)
                except ValueError:
                    offset = None
                if offset is not None:
                    cell = room_cell_for_runtime_offset(offset)
                    tile = tile_at_runtime_offset(self.current_level().part(self.part_var.get()), offset)
                    tile_text = "??" if tile is None else f"{tile:02X}"
                    if cell is not None:
                        room_index, x, y = cell
                        text = f"{prefix} room={room_index} x={x} y={y} tile={tile_text}"
            out.append(f"not({text})" if negated else text)
        return " and ".join(out) or "always"

    def _format_runtime_offsets_in_text(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            offset = int(match.group(1), 16)
            cell = room_cell_for_runtime_offset(offset)
            tile = tile_at_runtime_offset(self.current_level().part(self.part_var.get()), offset)
            tile_text = "??" if tile is None else f"{tile:02X}"
            if cell is None:
                return f"offset={offset:04X} tile={tile_text}"
            room_index, x, y = cell
            return f"room={room_index} x={x} y={y} tile={tile_text}"

        return re.sub(r"offset=([0-9A-Fa-f]{4})", repl, text)

    def refresh_script_instruction_tree(self) -> None:
        if not hasattr(self, "scripting_instruction_tree"):
            return
        current = self.scripting_instruction_tree.selection()
        selected_iid = current[0] if current else ""
        self.scripting_instruction_tree.delete(*self.scripting_instruction_tree.get_children())
        labels = self._script_labels_by_offset()
        for idx, ins in enumerate(self.scripting_instructions):
            text = self._script_instruction_display(ins, labels)
            self.scripting_instruction_tree.insert("", tk.END, iid=str(idx), values=(self._format_actor_addr(ins.offset), text))
        if selected_iid and selected_iid in self.scripting_instruction_tree.get_children():
            self.scripting_instruction_tree.selection_set(selected_iid)
            self.scripting_instruction_tree.focus(selected_iid)
        elif self.scripting_instructions:
            self.scripting_instruction_tree.selection_set("0")
            self.scripting_instruction_tree.focus("0")
        self.on_scripting_instruction_selected()

    def refresh_script_branch_tree(self) -> None:
        if not hasattr(self, "scripting_branch_tree"):
            return
        self.scripting_branch_tree.delete(*self.scripting_branch_tree.get_children())
        decoded = self.scripting_decoded
        if decoded is None:
            return
        for idx, trace in enumerate(decoded.traces, start=1):
            conditions = self._format_branch_conditions(trace.conditions)
            steps = "; ".join(seg.human_label for seg in trace.segments) or "no movement"
            if trace.loop_detected:
                steps += " loop"
            if trace.truncated:
                steps += " ..."
            self.scripting_branch_tree.insert("", tk.END, values=(str(idx), conditions, steps))

    def refresh_script_refs_tree(self) -> None:
        if not hasattr(self, "scripting_refs_tree"):
            return
        self.scripting_refs_tree.delete(*self.scripting_refs_tree.get_children())
        space = self.scripting_space
        address = self.scripting_selected_address
        if space is None or address is None:
            return
        part = self.current_level().part(self.part_var.get())
        actors = {actor.index: actor for actor in parse_actor_table(part)}
        visible = set(self.scripting_visible_addresses)
        for entry in space.entry_points:
            if entry.address == address or entry.address in visible:
                actor = actors.get(entry.actor_index)
                self.scripting_refs_tree.insert(
                    "",
                    tk.END,
                    values=("entry point", f"A{entry.actor_index}.{entry.field}", f"0x{entry.address:04X} {self._format_actor_short(actor)}"),
                )
        for jump in space.jumps:
            if jump.target == address or jump.target in visible:
                self.scripting_refs_tree.insert(
                    "",
                    tk.END,
                    values=("incoming jump", f"0x{jump.source:04X}", f"target=0x{jump.target:04X}"),
                )
            if jump.source in visible:
                self.scripting_refs_tree.insert(
                    "",
                    tk.END,
                    values=("outgoing jump", f"0x{jump.source:04X}", f"target=0x{jump.target:04X}"),
                )
        for ref in space.actor_refs:
            if ref.source in visible:
                actor = actors.get(ref.actor_index)
                mode = 1 if ref.opcode == 0x0A else 0
                self.scripting_refs_tree.insert(
                    "",
                    tk.END,
                    values=("actor ref", f"0x{ref.source:04X}", f"set_actor_mode_{mode} A{ref.actor_index} {self._format_actor_short(actor)}"),
                )

    def _selected_script_instruction_index(self) -> int | None:
        if not hasattr(self, "scripting_instruction_tree"):
            return None
        selected = self.scripting_instruction_tree.selection()
        if not selected:
            return None
        try:
            idx = int(selected[0])
        except ValueError:
            return None
        return idx if 0 <= idx < len(self.scripting_instructions) else None

    def on_scripting_instruction_selected(self, _event=None) -> None:
        idx = self._selected_script_instruction_index()
        if idx is None:
            self.scripting_opcode_var.set("")
            self.refresh_script_param_fields()
            return
        ins = self.scripting_instructions[idx]
        self.scripting_opcode_var.set(ins.mnemonic)
        self.refresh_script_param_fields(ins)

    def _opcode_from_script_combo(self) -> int | None:
        name = self.scripting_opcode_var.get()
        for opcode, opcode_name in OPCODE_NAMES.items():
            if opcode_name == name:
                return opcode
        return None

    def refresh_script_param_fields(self, ins: Instruction | None = None) -> None:
        if not hasattr(self, "scripting_param_rows"):
            return
        opcode = self._opcode_from_script_combo()
        specs = SCRIPT_PARAM_SPECS.get(opcode, ()) if opcode is not None else ()
        labels = self._script_labels_by_offset()
        values = self._script_param_values(ins, labels) if ins is not None and opcode == ins.opcode else self._default_script_param_values(opcode)
        for idx, (label, entry) in enumerate(self.scripting_param_rows):
            if idx < len(specs):
                _key, text = specs[idx]
                label.configure(text=text)
                self.scripting_param_vars[idx].set(values[idx] if idx < len(values) else "")
                label.grid()
                entry.grid()
            else:
                self.scripting_param_vars[idx].set("")
                label.grid_remove()
                entry.grid_remove()

    def _default_script_param_values(self, opcode: int | None) -> list[str]:
        address = self.scripting_selected_address or 0
        if opcode in {0x01, 0x02}:
            return [self._format_actor_addr(address)]
        if opcode in {0x04, 0x05, 0x06}:
            return [self._format_actor_addr(address), "1"]
        if opcode in {0x07, 0x08, 0x09, 0x17, 0x18, 0x19, 0x1A, 0x1B}:
            return ["0"]
        if opcode in {0x0A, 0x0B}:
            return ["A0"]
        if opcode == 0x0C:
            return ["0x00", "0x00"]
        if opcode == 0x0D:
            return ["0x00"]
        if opcode == 0x0E:
            return ["0", "0", "0x00"]
        if opcode == 0x0F:
            return ["0", "0", "0x00"]
        if opcode == 0x10:
            return ["0", "0", "0x00", "0"]
        if opcode in {0x13, 0x14, 0x15, 0x16}:
            return [str(self.room_var.get()), "0", "0"]
        return []

    def _script_param_values(self, ins: Instruction, labels: dict[int, str]) -> list[str]:
        if ins.opcode in {0x01, 0x02}:
            target = self._instruction_target_abs(ins)
            return ["" if target is None else self._format_actor_addr(target)]
        if ins.opcode in {0x04, 0x05, 0x06}:
            target = self._instruction_target_abs(ins)
            count = ins.args[0] if ins.target_label else (ins.args[1] if len(ins.args) > 1 else 1)
            return ["" if target is None else self._format_actor_addr(target), str(count)]
        if ins.opcode in {0x0A, 0x0B} and ins.args:
            return [format_actor_ref(ins.args[0])]
        if ins.opcode in {0x0C, 0x0D}:
            return [f"0x{value:02X}" for value in ins.args]
        if ins.opcode == 0x0E:
            dx, dy, frame_delta = ins.args
            return [str(dx), str(dy), f"0x{frame_delta:02X}"]
        if ins.opcode == 0x0F:
            x_raw, y, frame_delta = ins.args
            return [str(x_raw), str(y), f"0x{frame_delta:02X}"]
        if ins.opcode == 0x10:
            x_raw, y, frame, room = ins.args
            return [str(x_raw), str(y), f"0x{frame:02X}", str(room)]
        if ins.opcode in {0x13, 0x14, 0x15, 0x16}:
            cell = room_cell_for_runtime_offset(ins.args[0])
            if cell is None:
                return [f"offset=0x{ins.args[0]:04X}", "", ""]
            room_index, x, y = cell
            return [str(room_index), str(x), str(y)]
        return [str(value) for value in ins.args]

    def _parse_branch_target(self, text: str) -> tuple[int | None, str | None]:
        value = text.strip()
        if not value:
            return 0, None
        if value.lower().startswith("rel="):
            return parse_int(value[4:]), None
        try:
            return parse_int(value), None
        except ValueError:
            return None, value

    def _instruction_from_script_fields(self) -> Instruction:
        opcode = self._opcode_from_script_combo()
        if opcode is None:
            raise ValueError("Choose an opcode first.")
        values = [var.get().strip() for var in self.scripting_param_vars]
        target_label: str | None = None
        args: tuple[int, ...]
        if opcode in {0x01, 0x02}:
            if values[0].lower().startswith("rel="):
                args = (parse_int(values[0][4:]),)
            else:
                idx = self._selected_script_instruction_index()
                current_offset = self.scripting_instructions[idx].offset if idx is not None else 0
                target_abs = self._parse_actor_addr(values[0])
                target_label = self._ensure_script_target_label(target_abs)
                args = () if target_label else (target_abs - (current_offset + opcode_size(opcode)),)
        elif opcode in {0x04, 0x05, 0x06}:
            count = parse_int(values[1] or "1")
            if values[0].lower().startswith("rel="):
                args = (parse_int(values[0][4:]), count)
            else:
                idx = self._selected_script_instruction_index()
                current_offset = self.scripting_instructions[idx].offset if idx is not None else 0
                target_abs = self._parse_actor_addr(values[0])
                target_label = self._ensure_script_target_label(target_abs)
                args = (count,) if target_label else (target_abs - (current_offset + opcode_size(opcode)), count)
        elif opcode in {0x0A, 0x0B}:
            args = (parse_actor_ref(values[0] or "A0"),)
        elif opcode in {0x13, 0x14, 0x15, 0x16}:
            if values[0].lower().startswith("offset="):
                args = (parse_int(values[0].split("=", 1)[1]),)
            else:
                room_index = parse_int(values[0] or str(self.room_var.get()))
                x = parse_int(values[1] or "0")
                y = parse_int(values[2] or "0")
                args = (runtime_offset_for_room_cell(room_index, x, y),)
        elif opcode in SCRIPT_PARAM_SPECS:
            args = tuple(parse_int(value or "0") for value in values[:len(SCRIPT_PARAM_SPECS[opcode])])
        else:
            args = ()
        return Instruction(opcode=opcode, args=args, target_label=target_label)

    def apply_script_instruction_edit(self) -> None:
        idx = self._selected_script_instruction_index()
        if idx is None:
            return
        if not self.scripting_region_writable:
            messagebox.showerror("Read-only script space view", "This reachable script-space view is non-contiguous or shared through cross-jumps. Edit it after selecting a contiguous routine address.")
            return
        try:
            new_ins = self._instruction_from_script_fields()
        except (ValueError, ActorScriptError) as exc:
            messagebox.showerror("Invalid instruction", str(exc))
            return
        old = self.scripting_instructions[idx]
        new_ins.offset = old.offset
        new_ins.label = old.label
        self.scripting_instructions[idx] = new_ins
        self._reflow_script_instruction_offsets()
        self.refresh_script_instruction_tree()
        self.scripting_instruction_tree.selection_set(str(idx))
        self.update_script_dsl_preview()

    def add_script_instruction(self) -> None:
        if not self.scripting_region_writable:
            messagebox.showerror("Read-only script space view", "This reachable script-space view is non-contiguous or shared through cross-jumps. Add instructions in a contiguous routine view.")
            return
        idx = self._selected_script_instruction_index()
        insert_at = len(self.scripting_instructions) if idx is None else idx + 1
        self.scripting_instructions.insert(insert_at, Instruction(0x00))
        self._reflow_script_instruction_offsets()
        self.refresh_script_instruction_tree()
        self.scripting_instruction_tree.selection_set(str(insert_at))
        self.update_script_dsl_preview()

    def remove_script_instruction(self) -> None:
        if not self.scripting_region_writable:
            messagebox.showerror("Read-only script space view", "This reachable script-space view is non-contiguous or shared through cross-jumps. Remove instructions in a contiguous routine view.")
            return
        idx = self._selected_script_instruction_index()
        if idx is None:
            return
        del self.scripting_instructions[idx]
        self._reflow_script_instruction_offsets()
        self.refresh_script_instruction_tree()
        if self.scripting_instructions:
            self.scripting_instruction_tree.selection_set(str(min(idx, len(self.scripting_instructions) - 1)))
        self.update_script_dsl_preview()

    def _set_script_text(self, text: str) -> None:
        if not hasattr(self, "scripting_dsl_text"):
            return
        self.scripting_dsl_text.configure(state=tk.NORMAL)
        self.scripting_dsl_text.delete("1.0", tk.END)
        self.scripting_dsl_text.insert("1.0", text)
        self.scripting_dsl_text.configure(state=tk.DISABLED)

    def _address_dsl_preview(self) -> str:
        targets = {
            target
            for ins in self.scripting_instructions
            for target in [self._instruction_target_local(ins)]
            if target is not None and any(other.offset == target for other in self.scripting_instructions)
        }
        labels = self._script_labels_by_offset()
        lines: list[str] = []
        guard_next = False
        for ins in self.scripting_instructions:
            if ins.offset in targets:
                lines.append(f"{self._format_actor_addr(ins.offset)}:")
            indent = "        " if guard_next else "    "
            lines.append(indent + self._script_instruction_display(ins, labels))
            guard_next = 0x13 <= ins.opcode <= 0x1B
        return "\n".join(lines) + ("\n" if lines else "")

    def _assemble_script_space_region(self) -> bytes:
        if not self.scripting_region_writable or not self.scripting_instructions:
            raise ActorScriptError("reachable script-space view is not a contiguous writable region")
        labels = self._script_label_offsets()

        def resolve(label: str) -> int:
            if label not in labels:
                raise ActorScriptError(f"unknown label: {label}")
            return labels[label]

        out = bytearray()
        expected = self.scripting_instructions[0].offset
        for ins in self.scripting_instructions:
            if ins.offset != expected:
                raise ActorScriptError("script-space instructions are not contiguous")
            out.extend(ins.to_bytes(resolve))
            expected += ins.byte_size()
        return bytes(out)

    def update_script_dsl_preview(self) -> bytes | None:
        if not hasattr(self, "scripting_dsl_text"):
            return None
        try:
            dsl = self._address_dsl_preview()
            encoded = self._assemble_script_space_region()
            delta = len(encoded) - self.scripting_original_len
            status = f"Assembled {len(encoded)} script-space bytes"
            if self.scripting_original_len:
                status += f" ({delta:+d} vs selected region)"
            self.scripting_status_var.set(status)
        except ActorScriptError as exc:
            encoded = None
            dsl = self._address_dsl_preview() or f"# actor script-space decode error: {exc}\n"
            self.scripting_status_var.set(f"Read-only/non-contiguous script-space view: {exc}")
        self._set_script_text(dsl)
        return encoded

    def write_actor_script_bytes(self) -> None:
        if self.scripting_script_start is None:
            return
        encoded = self.update_script_dsl_preview()
        if encoded is None:
            messagebox.showerror("Write failed", "This script-space view is not a contiguous writable region yet.")
            return
        part = self.current_level().part(self.part_var.get())
        try:
            patch_actor_script_region(part, script_offset=self.scripting_script_start, old_length=self.scripting_original_len, new_bytes=encoded)
        except ValueError as exc:
            messagebox.showerror("Write failed", str(exc))
            return
        start = self.scripting_script_start
        delta = len(encoded) - self.scripting_original_len
        self._set_dirty()
        self.reload_selected_actor_script()
        self.redraw_room()
        self.status.set(f"Wrote script-space region at 0x{start:04X} ({delta:+d} bytes).")

    def set_part(self, index: int) -> None:
        self.part_var.set(index)
        self.part_combo.current(index)
        self.editor_selected_ref = None
        self.editor_drag_offset = None
        self.refresh_room_labels()
        self.redraw_room()
        self.redraw_objects_atlas()
        if hasattr(self, "audio_tree"):
            self.refresh_audio_atlas()
        self.redraw_tile_palette()
        self.redraw_editor_object_palette()
        self.redraw_decor_palette()
        self.redraw_actor_palette()
        self.refresh_actor_scripting_tab()

    def set_level(self, index: int) -> None:
        self.level_var.set(index)
        self.editor_selected_ref = None
        self.editor_drag_offset = None
        self.refresh_room_labels()
        self.redraw_room()
        self.redraw_objects_atlas()
        if hasattr(self, "audio_tree"):
            self.refresh_audio_atlas()
        self.redraw_tile_palette()
        self.redraw_editor_object_palette()
        self.redraw_decor_palette()
        self.redraw_actor_palette()
        self.refresh_actor_scripting_tab()

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
        self.refresh_actor_scripting_tab()

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
            f"unique_tiles={unique} separator={part.separator.hex(' ')}"
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

    def _green_block_footprint_cells_from_xy(self, x_px: int, y_px: int) -> set[tuple[int, int]]:
        # Green sequence blocks use a 6x2 invisible-solid footprint (tile 07).
        # The sprite is 56px wide, but collision is the inner 48px strip.
        start_x = max(0, min(ROOM_COLUMNS - 1, (x_px + 4) // CELL_SIZE))
        start_y = max(0, min(ROOM_ROWS - 1, y_px // CELL_SIZE))
        return {
            (x, y)
            for y in range(start_y, min(ROOM_ROWS, start_y + 2))
            for x in range(start_x, min(ROOM_COLUMNS, start_x + 6))
        }

    def _green_block_footprint_cells(self, rec: bytes, *, alternate: bool = False) -> set[tuple[int, int]]:
        if len(rec) < (4 if alternate else 2):
            return set()
        base = 2 if alternate else 0
        x_px, y_px = self._green_block_xy_from_raw(rec[base], rec[base + 1])
        return self._green_block_footprint_cells_from_xy(x_px, y_px)

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
        self.project.mark_level_dirty(self.current_level().index)
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

    def _layout_property_panel(self, *, rows: tuple[bool, ...] = (False, False, False, False), actor_bools: bool = False, apply: bool = False) -> None:
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
            self.property_note_var.set("Section_a symbol button/emitter. Actor emit_symbol N sends the same 1-based symbol id as pressing S1..S7 in the room. Raw code is stored zero-based in bits 0..2. Change Room to move this symbol to another room that has a symbol table.")
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
            self._layout_property_panel(rows=(True, True, True, True), apply=True)
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
            self.property_label_props_var.set("flip")
            self.property_x_var.set(str(entry.x_raw))
            self.property_y_var.set(str(entry.y))
            self.property_len_var.set(f"{entry.code:02X}")
            self.property_code_var.set(f"{sprite_ref.archive}:{sprite_ref.resource_id:03d}:{sprite_ref.sprite_index}")
            self.property_props_var.set("1" if entry.code & 0x40 else "0")
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
            pickups = self._known_extra_pickups_for_room(self.current_level().part(self.part_var.get()), room)
            if idx is None or not 0 <= idx < len(pickups):
                self.property_title_var.set("Selected apple no longer exists")
                self._clear_property_values()
                self._layout_property_panel()
                return
            pickup = pickups[idx]
            self._layout_property_panel(rows=(True, True, False, True), apply=True)
            self.property_title_var.set("Apple")
            self.property_label_x_var.set("raw x")
            self.property_label_y_var.set("y")
            self.property_label_len_var.set("storage")
            self.property_label_code_var.set("sprite")
            self.property_x_var.set(str(self._clamp_byte(round(pickup.x / 2))))
            self.property_y_var.set(str(self._clamp_byte(pickup.y)))
            self.property_len_var.set("room tail")
            self.property_code_var.set("AE000:045:0")
            self.property_room_var.set(str(room.index))
            self.property_note_var.set("Real red apple pickup. New/moved apples are written to the final 3 bytes of this room record: x_raw, y, room+1. The game supports one such apple marker per room. Change Room to move it.")
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
                    current_targets = control_ref_values(cmd)
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
                flip_text = self.property_props_var.get().strip().lower()
                if flip_text:
                    flip = flip_text in {"1", "true", "yes", "y", "on", "flip", "flipped"}
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
                start = header_player_start(part.header)
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
                x_raw = self._parse_int_property(self.property_x_var.get(), default=0) & 0xFF
                y_raw = self._parse_int_property(self.property_y_var.get(), default=0) & 0xFF
                target_room_index = self._parse_room_property(default=room.index)
                if target_room_index != room.index:
                    target_room = self.current_level().part(self.part_var.get()).room(target_room_index)
                    clear_room_apple_marker(room)
                    set_room_apple_marker(target_room, x_raw=x_raw, y=y_raw)
                    self.status.set(f"Moved apple to room {target_room_index:02d}: x={x_raw * 2} y={y_raw}")
                    self._set_dirty()
                    self.set_room(target_room_index)
                    self.editor_selected_ref = ("known_pickup", 0)
                    self.redraw_editor_room()
                    return
                set_room_apple_marker(room, x_raw=x_raw, y=y_raw)
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
        from .room_payload import room_tail_marker
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
                    flag_to_kind = {0x40: "horizontal_left", 0x60: "horizontal_right", 0x80: "vertical_down", 0xA0: "vertical_up"}
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
                    flag_to_kind = {0x40: "horizontal_left", 0x60: "horizontal_right", 0x80: "vertical_down", 0xA0: "vertical_up"}
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

    def _after_save(self, path: Path) -> None:
        self.title("Ancient Empires Level Editor")
        self.refresh_room_labels()
        self.redraw_room()
        self.redraw_objects_atlas()
        if hasattr(self, "audio_tree"):
            self.refresh_audio_atlas()
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
