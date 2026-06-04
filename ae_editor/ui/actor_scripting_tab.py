from __future__ import annotations

from .common import (
    ActorScriptError,
    Instruction,
    OPCODE_NAMES,
    SCRIPT_OPCODE_VALUES,
    SCRIPT_PARAM_SPECS,
    actor_script_space,
    actor_script_space_reachable_addresses,
    decode_actor_script,
    decode_instruction,
    format_actor_ref,
    instruction_to_dsl,
    messagebox,
    opcode_size,
    parse_actor_ref,
    parse_actor_table,
    parse_int,
    patch_actor_script_region,
    re,
    room_cell_for_runtime_offset,
    runtime_offset_for_room_cell,
    tile_at_runtime_offset,
    tk,
    tkfont,
    ttk,
)


class ActorScriptingTabMixin:
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
        self.scripting_instruction_tree.tag_configure("branch_target", font=self.tree_bold_font)
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

    def _branch_targets_in_view(self, instructions: list[Instruction]) -> set[int]:
        offsets = {ins.offset for ins in instructions}
        targets: set[int] = set()
        label_offsets = {ins.label: ins.offset for ins in instructions if ins.label}
        for ins in instructions:
            target = label_offsets.get(ins.target_label) if ins.target_label else ins.target_offset()
            if target in offsets:
                targets.add(target)
        return targets

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
        branch_targets = self._branch_targets_in_view(self.scripting_instructions)
        for idx, ins in enumerate(self.scripting_instructions):
            text = self._script_instruction_display(ins, labels)
            tags = ("branch_target",) if ins.offset in branch_targets else ()
            self.scripting_instruction_tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(self._format_actor_addr(ins.offset), text),
                tags=tags,
            )
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

