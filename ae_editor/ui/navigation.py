from __future__ import annotations

from .common import (
    DIFFICULTY_LABELS,
    ImageTk,
    actor_records_for_room,
    header_exit_door,
    laser_crystal_table,
    parse_exe_payload_directory,
    parse_platform_triplets,
    transition_links_for_room,
    visual_compact3_table,
)


class NavigationMixin:
    def set_part(self, index: int) -> None:
        self.part_var.set(index)
        self.part_combo.current(index)
        self.editor_selected_ref = None
        self.editor_drag_offset = None
        self.simulation = None
        self.simulation_key = None
        self.sim_selected_actor_index = None
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
        self.simulation = None
        self.simulation_key = None
        self.sim_selected_actor_index = None
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
        self.simulation = None
        self.simulation_key = None
        self.sim_selected_actor_index = None
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
        self.redraw_simulation()

