from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageTk

from ..constants import ACTOR_TICK_HZ, CELL_SIZE, DEFAULT_SIMULATION_TICK_HZ, ROOM_COUNT, ROOM_COLUMNS, ROOM_ROWS
from ..exporters import export_bank_sheets, export_probe_csv, export_room_previews
from ..rendering.overlay import build_room_overlay, control_ref_values, control_targets, decode_control_target
from ..rendering.coordinates import control_xy, actor_xy, object_entry_xy, object_screen_xy
from ..game_data.actor_scripts import decode_actor_script
from ..game_data.actor_dsl import (
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
from ..rendering.coordinates import platform_motion_delta, platform_xy
from ..game_data.conveyors import ConveyorSpec, compose_conveyor, iter_conveyor_runs
from ..project import AncientEmpiresProject
from ..rendering.room_renderer import RenderOptions
from ..rendering.object_mapping import visual_sprite_ref
from ..simulation import RoomSimulation
from ..rendering.tile_mapping import AUTO_SOLID_TILE_CODES, CONVEYOR_PHYSICS_TILE_CODES, ROPE_TILE_CODES
from ..audio import AudioItem, DEFAULT_PREVIEW_SPEED, GM_PROGRAM_NAMES, build_audio_atlas, describe_music_channels, play_audio_file, stop_audio_playback, synthesize_soundcard_music_wav, synthesize_wav, temp_preview_wav, write_midi
from ..game_data.room_payload import (
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
    part_apple_marker,
    apple_marker_screen_xy,
    apple_marker_raw_xy,
    set_part_apple_marker,
    clear_part_apple_marker,
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
    "horizontal_left": 0x60,
    "horizontal_right": 0x40,
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
