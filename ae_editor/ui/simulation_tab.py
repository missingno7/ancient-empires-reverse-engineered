from __future__ import annotations

import time

from .common import (
    ACTOR_TICK_HZ,
    ActorScriptError,
    AudioItem,
    CELL_SIZE,
    ConveyorSpec,
    DEFAULT_PREVIEW_SPEED,
    Image,
    ImageDraw,
    ImageTk,
    Instruction,
    RenderOptions,
    RoomSimulation,
    actor_script_space,
    actor_script_space_reachable_addresses,
    actor_xy,
    build_audio_atlas,
    compose_conveyor,
    control_commands,
    control_targets,
    control_xy,
    decode_instruction,
    iter_conveyor_runs,
    laser_crystal_table,
    object_entry_xy,
    object_screen_xy,
    parse_conveyor_visual_records,
    parse_platform_triplets,
    pc_speaker_preview_duration_seconds,
    platform_motion_delta,
    platform_xy,
    play_audio_file,
    render_preview_async,
    section_a_symbol_table,
    tk,
    ttk,
)


class SimulationTabMixin:
    def _build_simulation_tab(self, simulation_tab: ttk.Frame) -> None:
        main = ttk.PanedWindow(simulation_tab, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left, weight=4)
        main.add(right, weight=1)

        self.sim_canvas = tk.Canvas(left, bg="black")
        self.sim_canvas.pack(fill=tk.BOTH, expand=True)
        self.sim_canvas.bind("<Button-1>", self.simulation_click)
        self.sim_canvas.bind("<Button-3>", self.simulation_set_player)

        toolbar = ttk.Frame(right)
        toolbar.pack(fill=tk.X, padx=6, pady=(6, 4))
        ttk.Checkbutton(toolbar, text="Run", variable=self.sim_running_var, command=self.redraw_simulation).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Step", command=self.step_simulation_once).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(toolbar, text="Reset", command=self.reset_simulation).pack(side=tk.LEFT, padx=(6, 0))

        speed_row = ttk.Frame(right)
        speed_row.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Label(speed_row, text="Ticks/s").pack(side=tk.LEFT)
        ttk.Spinbox(speed_row, from_=1, to=60, textvariable=self.sim_speed_var, width=5, command=self._schedule_simulation_tick).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(speed_row, text=f"game ~{ACTOR_TICK_HZ:.2f}").pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(right, textvariable=self.sim_info_var, justify=tk.LEFT, wraplength=260).pack(fill=tk.X, padx=6, pady=(0, 8))

        controls_frame = ttk.LabelFrame(right, text="Controls")
        controls_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        columns = ("control", "state", "targets")
        self.sim_control_tree = ttk.Treeview(controls_frame, columns=columns, show="headings", height=8, selectmode="browse")
        self.sim_control_tree.heading("control", text="Control")
        self.sim_control_tree.heading("state", text="State")
        self.sim_control_tree.heading("targets", text="Targets")
        self.sim_control_tree.column("control", width=72, anchor="w")
        self.sim_control_tree.column("state", width=56, anchor="w")
        self.sim_control_tree.column("targets", width=130, anchor="w")
        sim_scroll = ttk.Scrollbar(controls_frame, orient=tk.VERTICAL, command=self.sim_control_tree.yview)
        self.sim_control_tree.configure(yscrollcommand=sim_scroll.set)
        self.sim_control_tree.grid(row=0, column=0, sticky="nsew")
        sim_scroll.grid(row=0, column=1, sticky="ns")
        controls_frame.rowconfigure(0, weight=1)
        controls_frame.columnconfigure(0, weight=1)
        self.sim_control_tree.bind("<Double-1>", self.toggle_selected_simulation_control)

        actor_frame = ttk.LabelFrame(right, text="Actor script")
        actor_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        actor_columns = ("actor", "state", "pc")
        self.sim_actor_tree = ttk.Treeview(actor_frame, columns=actor_columns, show="headings", height=4, selectmode="browse")
        self.sim_actor_tree.heading("actor", text="Actor")
        self.sim_actor_tree.heading("state", text="State")
        self.sim_actor_tree.heading("pc", text="PC")
        self.sim_actor_tree.column("actor", width=112, anchor="w")
        self.sim_actor_tree.column("state", width=86, anchor="w")
        self.sim_actor_tree.column("pc", width=54, anchor="w", stretch=False)
        actor_scroll = ttk.Scrollbar(actor_frame, orient=tk.VERTICAL, command=self.sim_actor_tree.yview)
        self.sim_actor_tree.configure(yscrollcommand=actor_scroll.set)
        self.sim_actor_tree.grid(row=0, column=0, sticky="nsew")
        actor_scroll.grid(row=0, column=1, sticky="ns")
        self.sim_actor_tree.bind("<<TreeviewSelect>>", self.on_simulation_actor_selected)

        ttk.Label(actor_frame, textvariable=self.sim_actor_debug_var, justify=tk.LEFT, wraplength=260).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(3, 3)
        )

        script_columns = ("pc", "mark", "instruction")
        self.sim_script_tree = ttk.Treeview(actor_frame, columns=script_columns, show="headings", height=8, selectmode="browse")
        self.sim_script_tree.heading("pc", text="PC")
        self.sim_script_tree.heading("mark", text="")
        self.sim_script_tree.heading("instruction", text="Instruction")
        self.sim_script_tree.column("pc", width=54, anchor="w", stretch=False)
        self.sim_script_tree.column("mark", width=48, anchor="w", stretch=False)
        self.sim_script_tree.column("instruction", width=178, anchor="w")
        self.sim_script_tree.tag_configure("current", background="#ffe58a")
        self.sim_script_tree.tag_configure("entry", foreground="#56606b")
        self.sim_script_tree.tag_configure("branch_target", font=self.tree_bold_font)
        script_scroll = ttk.Scrollbar(actor_frame, orient=tk.VERTICAL, command=self.sim_script_tree.yview)
        self.sim_script_tree.configure(yscrollcommand=script_scroll.set)
        self.sim_script_tree.grid(row=2, column=0, sticky="nsew")
        script_scroll.grid(row=2, column=1, sticky="ns")
        actor_frame.rowconfigure(2, weight=1)
        actor_frame.columnconfigure(0, weight=1)

        ttk.Label(right, textvariable=self.sim_detail_var, justify=tk.LEFT, wraplength=260).pack(fill=tk.X, padx=6, pady=(0, 6))

    def _simulation_context_key(self) -> tuple[int, int, int]:
        return (self.level_var.get(), self.part_var.get(), self.room_var.get())

    def ensure_simulation(self) -> RoomSimulation:
        key = self._simulation_context_key()
        if self.simulation is None or self.simulation_key != key:
            self.simulation = RoomSimulation(self.current_level(), self.part_var.get(), self.room_var.get())
            self.simulation_key = key
        return self.simulation

    def reset_simulation(self, *, announce: bool = True) -> None:
        if not hasattr(self, "sim_canvas"):
            return
        self.simulation = RoomSimulation(self.current_level(), self.part_var.get(), self.room_var.get())
        self.simulation_key = self._simulation_context_key()
        self.sim_selected_actor_index = None
        self.redraw_simulation()
        if announce:
            self.status.set("Simulation reset.")

    def _simulation_speed(self) -> int:
        try:
            value = int(self.sim_speed_var.get())
        except (tk.TclError, ValueError):
            value = 12
        value = max(1, min(60, value))
        self.sim_speed_var.set(value)
        return value

    def _schedule_simulation_tick(self) -> None:
        if self.sim_after_id is not None:
            try:
                self.after_cancel(self.sim_after_id)
            except tk.TclError:
                pass
            self.sim_after_id = None
        interval = max(16, round(1000 / self._simulation_speed()))
        self.sim_after_id = self.after(interval, self._simulation_tick)

    def _simulation_tick(self) -> None:
        self.sim_after_id = None
        if self.sim_running_var.get():
            sim = self.ensure_simulation()
            sim.step()
            self._play_pending_simulation_sounds(sim)
            self.redraw_simulation()
        self._schedule_simulation_tick()

    def _simulation_sound_items(self) -> dict[int, AudioItem]:
        if self.sim_sound_items_by_id is None:
            if not self.audio_items:
                self.audio_items = build_audio_atlas(self.project)
                self.audio_item_by_key = {item.key: item for item in self.audio_items}
            self.sim_sound_items_by_id = {
                item.sound_id: item
                for item in self.audio_items
                if item.kind == "pc-speaker-sfx" and item.sound_id is not None
            }
        return self.sim_sound_items_by_id

    def _simulation_sound_duration(self, item: AudioItem) -> float:
        try:
            duration = pc_speaker_preview_duration_seconds(
                item.data,
                music=False,
                audio_kind=item.kind,
            )
        except Exception:
            duration = 0.15
        return max(0.05, min(8.0, duration / DEFAULT_PREVIEW_SPEED))

    def _simulation_sound_is_blocked(self, sound_id: int) -> bool:
        active_id = getattr(self, "_simulation_active_sound_id", None)
        busy_until = getattr(self, "_simulation_active_sound_until", 0.0)
        if active_id is None or time.monotonic() >= busy_until:
            return False
        # CAF1 is a single PC-speaker output.  Lower ids have higher priority;
        # do not let repeated actor VM play_sound calls restart the same or a
        # lower-priority effect every simulation tick.
        return sound_id >= int(active_id)

    def _play_simulation_sound(self, sound_id: int) -> None:
        item = self._simulation_sound_items().get(sound_id)
        if item is None:
            self.sim_last_sound_status = f"play_sound 0x{sound_id:02X}: no CAF1 SFX stream found"
            return
        if self._simulation_sound_is_blocked(sound_id):
            self.sim_last_sound_status = f"play_sound 0x{sound_id:02X}: ignored while 0x{getattr(self, '_simulation_active_sound_id', 0):02X} is active"
            return
        duration = self._simulation_sound_duration(item)
        self._simulation_active_sound_id = sound_id
        self._simulation_active_sound_until = time.monotonic() + duration
        generation = getattr(self, "_simulation_audio_generation", 0) + 1
        self._simulation_audio_generation = generation
        # Use the canonical cached WAV path for CAF1 SFX in the editor UI.
        # The sounddevice PC-speaker callback remains available for experiments,
        # but WAV preview is the timing reference and avoids device-rate drift.
        task = render_preview_async(item, speed=DEFAULT_PREVIEW_SPEED)

        def poll() -> None:
            if generation != getattr(self, "_simulation_audio_generation", 0):
                return
            result = task.poll()
            if result is None:
                self.after(20, poll)
                return
            wav_path, error = result
            if error is not None:
                self.sim_last_sound_status = f"play_sound 0x{sound_id:02X} failed: {error}"
                return
            try:
                play_audio_file(wav_path)
                self.sim_last_sound_status = f"play_sound 0x{sound_id:02X} -> {item.label}"
            except Exception as exc:
                self.sim_last_sound_status = f"play_sound 0x{sound_id:02X} failed: {exc}"

        self.sim_last_sound_status = f"play_sound 0x{sound_id:02X}: preparing"
        self.after(0, poll)

    def _play_pending_simulation_sounds(self, sim: RoomSimulation) -> None:
        sound_ids = sim.drain_pending_sound_ids()
        if not sound_ids:
            return
        # Real PC speaker is effectively a single output with CAF1 priority:
        # lower sound ids override higher ids.  Pick the highest-priority id
        # emitted by this VM burst instead of replaying every request.
        self._play_simulation_sound(min(sound_ids))

    def step_simulation_once(self) -> None:
        sim = self.ensure_simulation()
        sim.step()
        self._play_pending_simulation_sounds(sim)
        self.redraw_simulation()
        suffix = f" ({self.sim_last_sound_status})" if self.sim_last_sound_status else ""
        self.status.set(f"Simulation tick {sim.tick_count}.{suffix}")

    def redraw_simulation(self) -> None:
        if not hasattr(self, "sim_canvas"):
            return
        sim = self.ensure_simulation()
        zoom = self.zoom_var.get()
        image = self.project.renderer.render_room(
            self.current_level(),
            self.room_var.get(),
            RenderOptions(
                mode="game",
                zoom=1,
                grid=False,
                part_index=self.part_var.get(),
                display_mode=self.display_mode_var.get(),
                draw_platforms=False,
                draw_puzzle_panels=False,
                draw_actors=False,
                draw_player_start=False,
                control_state_overrides=sim.control_states,
            ),
        )
        self._draw_simulation_target_reactions(image, sim)
        self._draw_simulation_green_blocks(image, sim)
        self._draw_simulation_actors(image, sim)
        self._draw_simulation_player(image, sim)
        if zoom != 1:
            image = image.resize((image.width * zoom, image.height * zoom), Image.Resampling.NEAREST)
        self.tk_sim_image = ImageTk.PhotoImage(image)
        self.sim_canvas.delete("all")
        self.sim_canvas.create_image(0, 0, anchor="nw", image=self.tk_sim_image)
        self.sim_canvas.config(scrollregion=(0, 0, image.width, image.height))
        if self.grid_var.get():
            self.draw_room_grid(self.sim_canvas)
        if self.show_collision_var.get():
            self.draw_collision_overlay(self.sim_canvas, self.current_room())
        self.refresh_room_link_buttons()
        self.refresh_simulation_control_tree()
        self.refresh_simulation_actor_debug()
        visible_actors = [a for a in sim.actors.values() if a.room_index == sim.room_index and (self.overlay_hidden_var.get() or not a.hidden)]
        active_parts = [
            f"P{idx}" for idx in sorted(sim.active_target_indices("platform"))
        ] + [
            f"CV{idx} toggled" for idx in sorted(sim.active_target_indices("conveyor"))
        ] + sim.reflector_runtime_summary()
        self.sim_info_var.set(
            f"tick={sim.tick_count} running={'yes' if self.sim_running_var.get() else 'no'}\n"
            f"player x={sim.player_x} y={sim.player_y}\n"
            f"visible actors={len(visible_actors)} active targets={','.join(active_parts) or '-'}"
        )
        last_events = [f"A{a.index}: {a.last_event}" for a in visible_actors if a.last_event]
        block_events = [f"GB{block.index}: {block.last_event}" for block in sim.green_blocks if block.last_event]
        reflector_events = [f"R{idx}: {event}" for idx, event in sorted(sim.reflector_events.items())]
        self.sim_detail_var.set("\n".join((block_events + reflector_events + last_events)[:8]))

    def refresh_simulation_control_tree(self) -> None:
        if not hasattr(self, "sim_control_tree"):
            return
        selection = self.sim_control_tree.selection()
        selected = selection[0] if selection else None
        sim = self.ensure_simulation()
        self.sim_control_tree.delete(*self.sim_control_tree.get_children())
        for index, label, state, targets in sim.control_summary():
            iid = str(index)
            self.sim_control_tree.insert("", tk.END, iid=iid, values=(label, "on" if state else "off", targets))
        if selected is not None and self.sim_control_tree.exists(selected):
            self.sim_control_tree.selection_set(selected)
            self.sim_control_tree.focus(selected)

    def refresh_simulation_actor_debug(self) -> None:
        if not hasattr(self, "sim_actor_tree"):
            return
        sim = self.ensure_simulation()
        actors = sorted(
            (actor for actor in sim.actors.values() if actor.room_index == sim.room_index),
            key=lambda actor: actor.index,
        )
        actor_ids = {actor.index for actor in actors}
        if self.sim_selected_actor_index not in actor_ids:
            self.sim_selected_actor_index = actors[0].index if actors else None

        self._sim_actor_tree_refreshing = True
        try:
            self.sim_actor_tree.delete(*self.sim_actor_tree.get_children())
            for actor in actors:
                state_parts = ["active" if actor.active else "sleep"]
                if actor.hidden:
                    state_parts.append("hidden")
                if actor.halted:
                    state_parts.append("halted")
                iid = str(actor.index)
                self.sim_actor_tree.insert(
                    "",
                    tk.END,
                    iid=iid,
                    values=(f"A{actor.index} {actor.name}", " ".join(state_parts), f"{actor.pc:04X}"),
                )
            if self.sim_selected_actor_index is not None:
                selected_iid = str(self.sim_selected_actor_index)
                if self.sim_actor_tree.exists(selected_iid):
                    if tuple(self.sim_actor_tree.selection()) != (selected_iid,):
                        self.sim_actor_tree.selection_set(selected_iid)
                    self.sim_actor_tree.focus(selected_iid)
                    self.sim_actor_tree.see(selected_iid)
        finally:
            self._sim_actor_tree_refreshing = False

        self.refresh_simulation_actor_script()

    def on_simulation_actor_selected(self, _event=None) -> None:
        if getattr(self, "_sim_actor_tree_refreshing", False):
            return
        selection = self.sim_actor_tree.selection() if hasattr(self, "sim_actor_tree") else ()
        if not selection:
            return
        actor_index = int(selection[0])
        if actor_index == self.sim_selected_actor_index:
            return
        self.sim_selected_actor_index = actor_index
        self.refresh_simulation_actor_script()
        self.redraw_simulation()

    def refresh_simulation_actor_script(self) -> None:
        if not hasattr(self, "sim_script_tree"):
            return
        sim = self.ensure_simulation()
        self.sim_script_tree.delete(*self.sim_script_tree.get_children())
        actor = (
            sim.actors.get(self.sim_selected_actor_index)
            if self.sim_selected_actor_index is not None
            else None
        )
        if actor is None:
            self.sim_actor_debug_var.set("No actor selected.")
            return

        state = "active" if actor.active else "sleep"
        hidden = "hidden" if actor.hidden else "shown"
        event = f" last={actor.last_event}" if actor.last_event else ""
        self.sim_actor_debug_var.set(
            f"A{actor.index} {actor.name}: {state} {hidden} pc=0x{actor.pc:04X} "
            f"script=0x{actor.script_offset:04X} restart=0x{actor.restart_script_offset:04X}{event}"
        )

        entry_marks: dict[int, list[str]] = {}
        entry_marks.setdefault(actor.script_offset, []).append("script")
        entry_marks.setdefault(actor.restart_script_offset, []).append("restart")
        entry_marks.setdefault(actor.pc, []).append("next")
        current_iid: str | None = None
        rows: list[tuple[int, Instruction | None, str]] = []
        for pc in self._simulation_actor_script_addresses(sim, actor):
            try:
                ins = decode_instruction(sim.actor_block, pc)
                text = self._script_instruction_display(ins, {})
            except ActorScriptError as exc:
                ins = None
                text = str(exc)
            rows.append((pc, ins, text))

        branch_targets = self._branch_targets_in_view([ins for _pc, ins, _text in rows if ins is not None])
        for pc, _ins, text in rows:
            marks = entry_marks.get(pc, [])
            iid = f"pc-{pc:04X}"
            tags: list[str] = []
            if pc == actor.pc:
                tags.append("current")
            if pc in branch_targets:
                tags.append("branch_target")
            elif marks:
                tags.append("entry")
            self.sim_script_tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(f"{pc:04X}", ",".join(marks), text),
                tags=tuple(tags),
            )
            if pc == actor.pc:
                current_iid = iid
        if current_iid is not None:
            self.sim_script_tree.selection_set(current_iid)
            self.sim_script_tree.focus(current_iid)
            self.sim_script_tree.see(current_iid)

    def _simulation_actor_script_addresses(self, sim: RoomSimulation, actor) -> list[int]:
        part = self.current_level().part(self.part_var.get())
        space = actor_script_space(part)
        starts: list[int] = []
        for start in (actor.script_offset, actor.restart_script_offset, actor.pc):
            if 0 <= start < len(sim.actor_block) and start not in starts:
                starts.append(start)
        seen: set[int] = set()
        addresses: list[int] = []
        for start in starts:
            for pc in actor_script_space_reachable_addresses(space, start, max_commands=120):
                if pc not in seen:
                    seen.add(pc)
                    addresses.append(pc)
        if 0 <= actor.pc < len(sim.actor_block) and actor.pc not in seen:
            addresses.append(actor.pc)
        return sorted(addresses)

    def _select_simulation_actor(self, actor_index: int) -> None:
        self.sim_selected_actor_index = actor_index
        if hasattr(self, "sim_actor_tree"):
            iid = str(actor_index)
            if self.sim_actor_tree.exists(iid):
                self._sim_actor_tree_refreshing = True
                try:
                    if tuple(self.sim_actor_tree.selection()) != (iid,):
                        self.sim_actor_tree.selection_set(iid)
                    self.sim_actor_tree.focus(iid)
                    self.sim_actor_tree.see(iid)
                finally:
                    self._sim_actor_tree_refreshing = False
        self.refresh_simulation_actor_script()

    def toggle_selected_simulation_control(self, _event=None) -> None:
        sim = self.ensure_simulation()
        selection = self.sim_control_tree.selection() if hasattr(self, "sim_control_tree") else ()
        if not selection:
            return
        idx = int(selection[0])
        state = sim.toggle_control(idx)
        if state is not None:
            self.redraw_simulation()
            self.status.set(f"Simulation C{idx} {'on' if state else 'off'}.")

    def simulation_click(self, event) -> None:
        sim = self.ensure_simulation()
        cmd = self._simulation_control_at_event(event)
        if cmd is None:
            symbol = self._simulation_symbol_at_event(event)
            if symbol is None:
                actor = self._simulation_actor_at_event(event)
                if actor is not None:
                    self._select_simulation_actor(actor.index)
                    self.redraw_simulation()
                    self.status.set(f"Simulation selected A{actor.index} {actor.name}.")
                    return
                x, y = self._screen_xy_from_event(event, self.sim_canvas)
                self.status.set(f"Simulation click x={x} y={y}.")
                return
            sim.emit_symbol(symbol)
            self.redraw_simulation()
            self.status.set(f"Simulation emitted symbol S{symbol}.")
            return
        state = sim.toggle_control(cmd.record.index)
        self.redraw_simulation()
        targets = ",".join(target.label for target in control_targets(cmd)) or "-"
        self.status.set(f"Simulation toggled C{cmd.record.index} {'on' if state else 'off'} targets={targets}.")

    def simulation_set_player(self, event) -> None:
        sim = self.ensure_simulation()
        x, y = self._screen_xy_from_event(event, self.sim_canvas)
        sim.set_player_position(x, y)
        self.redraw_simulation()
        self.status.set(f"Simulation player position x={sim.player_x} y={sim.player_y}.")

    def _simulation_control_at_event(self, event):
        x, y = self._screen_xy_from_event(event, self.sim_canvas)
        for cmd in reversed(control_commands(self.current_room())):
            if cmd.command is None or cmd.x_raw is None or cmd.y_raw is None:
                continue
            resource_id = 39
            if cmd.command == 0x01:
                resource_id = 40
            elif cmd.command == 0x02:
                resource_id = 41
            cx, cy = control_xy(cmd)
            sprite = self.project.graphics.sprite("AE000", resource_id, 0)
            width = 24 if sprite is None else sprite.width
            height = 24 if sprite is None else sprite.height
            if cx - 6 <= x <= cx + width + 6 and cy - 6 <= y <= cy + height + 6:
                return cmd
        return None

    def _simulation_symbol_at_event(self, event) -> int | None:
        x, y = self._screen_xy_from_event(event, self.sim_canvas)
        table = section_a_symbol_table(self.current_room())
        if table is None:
            return None
        base = self.project.graphics.sprite("AE000", 9, 0)
        width = 24 if base is None else base.width
        height = 24 if base is None else base.height
        for entry in reversed(table.entries):
            # Match the medallion's top-left draw anchor (object_screen_xy).
            sx, sy = object_screen_xy(entry.x_raw, entry.y)
            if sx - 4 <= x <= sx + width + 4 and sy - 4 <= y <= sy + height + 4:
                return (entry.code & 0x07) + 1
        return None

    def _simulation_actor_at_event(self, event):
        sim = self.ensure_simulation()
        x, y = self._screen_xy_from_event(event, self.sim_canvas)
        for actor in reversed(list(sim.actors.values())):
            if actor.room_index != sim.room_index:
                continue
            if actor.hidden and not self.overlay_hidden_var.get():
                continue
            sprite = self.project.renderer._sprite_for_actor_record(actor)
            if sprite is None:
                continue
            ax, ay = actor_xy(actor.x, actor.y)
            if ax - 4 <= x <= ax + sprite.width + 4 and ay - 4 <= y <= ay + sprite.height + 4:
                return actor
        return None

    def _draw_simulation_target_reactions(self, image: Image.Image, sim: RoomSimulation) -> None:
        room = self.current_room()
        draw = ImageDraw.Draw(image, "RGBA")
        active_platforms = sim.active_target_indices("platform")
        active_conveyors = sim.active_target_indices("conveyor")
        horizontal = self.project.graphics.sprite("AE000", 47, 0)
        vertical = self.project.graphics.sprite("AE000", 48, 0)
        for platform in parse_platform_triplets(room):
            if not platform.visible:
                continue
            sprite = vertical if platform.orientation == "vertical" else horizontal
            if sprite is None:
                continue
            x, y = platform_xy(platform)
            dx, dy = self._simulation_platform_offset(platform) if platform.index in active_platforms else (0, 0)
            image.alpha_composite(sprite, (x + dx, y + dy))
            if dx or dy:
                self._draw_simulation_motion_arrow(draw, x + sprite.width // 2, y + sprite.height // 2, dx, dy)

        # Belts are always running.  A control signal does not start/stop a
        # conveyor; it toggles the conveyor family/direction.  The terrain
        # footprint mirrors this as 0x0F <-> 0x1F.
        parts = [self.project.graphics.sprite("AE000", 38, i) for i in range(24)]
        runs = iter_conveyor_runs(room)
        frame = (sim.tick_count // 3) % 4
        for cv in parse_conveyor_visual_records(room):
            kind = "teal"
            for run in runs:
                if run.cells & cv.cells:
                    kind = run.kind
                    break
            toggled = cv.index in active_conveyors
            if toggled:
                kind = "grey" if kind == "teal" else "teal"
            width = max(8, (cv.length + 1) * CELL_SIZE)
            strip = compose_conveyor(parts, ConveyorSpec(kind=kind, x=0, y=0, width=width, frame=frame))
            if strip is None:
                continue
            x, y = object_screen_xy(cv.x_raw, cv.y)
            image.alpha_composite(strip, (x, y))
            if toggled:
                draw.rectangle((x, y, x + strip.width - 1, y + strip.height - 1), outline=(80, 245, 255, 210), width=1)

        table = laser_crystal_table(room)
        if table is not None:
            for entry in table.entries:
                sprite_index = sim.reflector_sprite_index(entry)
                sprite = self.project.graphics.sprite("AE000", 19, sprite_index) or self.project.graphics.sprite("AE000", 19, entry.code & 0x3F)
                if sprite is None:
                    continue
                image.alpha_composite(sprite, object_entry_xy(entry))
                if entry.code & 0x80:
                    draw.ellipse((entry.x_raw * 2 - 9, entry.y - 9, entry.x_raw * 2 + 9, entry.y + 9), outline=(90, 220, 255, 220), width=2)
                elif entry.index in sim.reflector_events:
                    draw.ellipse((entry.x_raw * 2 - 9, entry.y - 9, entry.x_raw * 2 + 9, entry.y + 9), outline=(255, 210, 70, 220), width=2)

    def _simulation_platform_offset(self, platform) -> tuple[int, int]:
        return platform_motion_delta(platform)

    def _draw_simulation_motion_arrow(self, draw: ImageDraw.ImageDraw, x: int, y: int, dx: int, dy: int) -> None:
        end_x = x + dx
        end_y = y + dy
        colour = (255, 210, 70, 230)
        draw.line((x, y, end_x, end_y), fill=colour, width=2)
        if abs(dx) >= abs(dy):
            sign = 1 if dx >= 0 else -1
            points = ((end_x, end_y), (end_x - sign * 7, end_y - 4), (end_x - sign * 7, end_y + 4))
        else:
            sign = 1 if dy >= 0 else -1
            points = ((end_x, end_y), (end_x - 4, end_y - sign * 7), (end_x + 4, end_y - sign * 7))
        draw.polygon(points, fill=colour)

    def _draw_simulation_green_blocks(self, image: Image.Image, sim: RoomSimulation) -> None:
        panel = self.project.graphics.sprite("AE000", 17, 0)
        if panel is None:
            return
        for block in sim.green_blocks:
            x, y = block.current_xy
            image.alpha_composite(self._simulation_green_block_image(panel, block.remaining_sequence), (x, y))

    def _simulation_green_block_image(self, panel: Image.Image, seq_values: list[int]) -> Image.Image:
        out = panel.copy()
        symbols = []
        for value in seq_values[:5]:
            sprite = self.project.graphics.sprite("AE000", 9 + value, 0)
            if sprite is not None:
                symbols.append(sprite)
        if not symbols:
            return out
        total_w = sum(sprite.width for sprite in symbols) + max(0, len(symbols) - 1)
        if total_w > out.width:
            scale = max(1, min(sprite.width for sprite in symbols) - 1) / max(1, max(sprite.width for sprite in symbols))
            scaled = []
            for sprite in symbols:
                w = max(1, int(sprite.width * scale))
                h = max(1, int(sprite.height * scale))
                scaled.append(sprite.resize((w, h), Image.Resampling.NEAREST))
            symbols = scaled
            total_w = sum(sprite.width for sprite in symbols) + max(0, len(symbols) - 1)
        x = max(0, (out.width - total_w) // 2)
        for sprite in symbols:
            y = max(0, (out.height - sprite.height) // 2)
            out.alpha_composite(sprite, (x, y))
            x += sprite.width + 1
        return out

    def _draw_simulation_actors(self, image: Image.Image, sim: RoomSimulation) -> None:
        draw = ImageDraw.Draw(image, "RGBA")
        for actor in sim.actors.values():
            if actor.room_index != sim.room_index:
                continue
            if actor.hidden and not self.overlay_hidden_var.get():
                continue
            sprite = self.project.renderer._sprite_for_actor_record(actor)
            if sprite is None:
                continue
            x, y = actor_xy(actor.x, actor.y)
            image.alpha_composite(sprite, (int(x), int(y)))
            if actor.index == self.sim_selected_actor_index:
                draw.rectangle(
                    (int(x) - 1, int(y) - 1, int(x) + sprite.width, int(y) + sprite.height),
                    outline=(255, 230, 90, 230),
                    width=1,
                )

    def _draw_simulation_player(self, image: Image.Image, sim: RoomSimulation) -> None:
        sprite = self.project.graphics.sprite("AE000", 4, 0)
        draw = ImageDraw.Draw(image, "RGBA")
        if sprite is not None:
            image.alpha_composite(sprite, (sim.player_x - 4, sim.player_y - 16))
        draw.line((sim.player_x - 6, sim.player_y, sim.player_x + 6, sim.player_y), fill=(124, 255, 107, 230), width=1)
        draw.line((sim.player_x, sim.player_y - 6, sim.player_x, sim.player_y + 6), fill=(124, 255, 107, 230), width=1)

