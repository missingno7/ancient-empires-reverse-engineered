from __future__ import annotations

from .common import (
    DIFFICULTY_LABELS,
    ROOM_COUNT,
    tk,
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
        self.refresh_room_link_buttons()
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
        self.refresh_room_link_buttons()
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

    def _room_link_targets(self) -> dict[str, int]:
        links = transition_links_for_room(self.current_level().part(self.part_var.get()), self.room_var.get())
        if links is None:
            return {}
        raw = {
            "left": links.left,
            "right": links.right,
            "up": links.up,
            "down": links.down,
        }
        targets: dict[str, int] = {}
        for direction, value in raw.items():
            if value:
                target = value - 1
                if 0 <= target < ROOM_COUNT:
                    targets[direction] = target
        return targets

    def refresh_room_link_buttons(self) -> None:
        if not hasattr(self, "room_link_buttons"):
            return
        targets = self._room_link_targets()
        arrows = {"left": "←", "right": "→", "up": "↑", "down": "↓"}
        for direction, button in self.room_link_buttons.items():
            target = targets.get(direction)
            if target is None:
                button.configure(text=f"{arrows[direction]} -", state=tk.DISABLED)
            else:
                button.configure(text=f"{arrows[direction]} {target:02d}", state=tk.NORMAL)

    def go_room_link(self, direction: str) -> None:
        target = self._room_link_targets().get(direction)
        if target is None:
            self.status.set(f"No {direction} room link from room {self.room_var.get():02d}.")
            return
        current = self.room_var.get()
        self.set_room(target)
        self.status.set(f"Room link {direction}: {current:02d} -> {target:02d}.")

    def redraw_room(self) -> None:
        image = self.current_image()
        self.tk_image = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_image)
        self.canvas.config(scrollregion=(0, 0, image.width, image.height))
        if self.grid_var.get():
            self.draw_room_grid(self.canvas)

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
        self.refresh_room_link_buttons()
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

