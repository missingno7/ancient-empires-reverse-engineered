from __future__ import annotations

from queue import Empty, Queue
from threading import Thread

from .common import (
    AudioItem,
    DEFAULT_PREVIEW_SPEED,
    Path,
    build_audio_atlas,
    describe_music_channels,
    filedialog,
    messagebox,
    play_audio_file,
    stop_audio_playback,
    synthesize_soundcard_music_wav,
    synthesize_wav,
    temp_preview_wav,
    tk,
    ttk,
    write_midi,
)


class AudioTabMixin:
    def _build_audio_tab(self, audio_tab: ttk.Frame) -> None:
        top = ttk.Frame(audio_tab)
        top.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(top, text="Audio atlas").pack(side=tk.LEFT)
        ttk.Button(top, text="Refresh", command=self.refresh_audio_atlas).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(top, text="Preview speed ×").pack(side=tk.LEFT, padx=(12, 0))
        ttk.Spinbox(top, from_=0.25, to=6.0, increment=0.25, width=5, textvariable=self.audio_speed_var).pack(side=tk.LEFT, padx=(2, 0))
        ttk.Button(top, text="Play preview", command=self.play_selected_audio).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(top, text="Stop", command=self.stop_audio_preview).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(top, text="Export WAV", command=self.export_selected_audio_wav).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(top, text="Export MIDI", command=self.export_selected_audio_midi).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(
            audio_tab,
            text=(
                "Audio Atlas shows confirmed PC-speaker SFX and complete music resources. "
                "Preview uses the internal WAV renderer; MIDI export can use the General MIDI mapping below."
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
        controls = ttk.LabelFrame(right, text="MIDI export instruments")
        controls.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(
            controls,
            text="Choose a General MIDI instrument per detected music channel. This affects MIDI export only; WAV preview keeps the recovered game-style renderer.",
            justify=tk.LEFT,
            wraplength=420,
        ).pack(fill=tk.X, padx=6, pady=(4, 2))
        self.audio_channel_frame = ttk.Frame(controls)
        self.audio_channel_frame.pack(fill=tk.X, padx=6, pady=(2, 4))
        row = ttk.Frame(controls)
        row.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Button(row, text="Reset to defaults", command=self.reset_audio_channel_defaults).pack(side=tk.LEFT)

        ttk.Label(right, text="Hex preview").pack(anchor="w")
        self.audio_hex_text = tk.Text(right, height=18, width=58, wrap="none")
        self.audio_hex_text.pack(fill=tk.BOTH, expand=True)

        self.refresh_audio_atlas()

    def refresh_audio_atlas(self) -> None:
        if not hasattr(self, "audio_tree"):
            return
        self.audio_items = build_audio_atlas(self.project)
        self.audio_item_by_key = {item.key: item for item in self.audio_items}
        self.sim_sound_items_by_id = None
        self.audio_tree.delete(*self.audio_tree.get_children())
        for item in self.audio_items:
            source = f"{item.archive_name}:{item.resource_index:03d}"
            offset = f"0x{item.offset:04X}" if item.offset is not None else "-"
            code = item.label
            self.audio_tree.insert("", tk.END, iid=item.key, values=(item.kind, code, source, offset, item.length, item.notes))
        self.audio_info_var.set(f"Found {len(self.audio_items)} audio entries.")
        self.audio_hex_text.delete("1.0", tk.END)
        self._refresh_audio_channel_controls(None)

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
            lines.append("AdLib/Sound Blaster music resource. The atlas keeps this as one complete mix, not extracted single channels.")
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
        self._refresh_audio_channel_controls(item)

    def _refresh_audio_channel_controls(self, item: AudioItem | None) -> None:
        if not hasattr(self, "audio_channel_frame"):
            return
        for child in self.audio_channel_frame.winfo_children():
            child.destroy()
        self.audio_channel_program_vars.clear()
        self.audio_channel_default_programs.clear()
        if item is None or item.kind not in {"soundcard-music", "pc-speaker-music"}:
            ttk.Label(self.audio_channel_frame, text="Select a music resource to edit MIDI export instruments.").pack(anchor="w")
            return
        try:
            summaries = describe_music_channels(item.data, audio_kind=item.kind)
        except Exception as exc:
            ttk.Label(self.audio_channel_frame, text=f"Could not parse channels: {exc}").pack(anchor="w")
            return
        if not summaries:
            ttk.Label(self.audio_channel_frame, text="No playable channels detected.").pack(anchor="w")
            return
        for row_no, summary in enumerate(summaries):
            row = ttk.Frame(self.audio_channel_frame)
            row.pack(fill=tk.X, pady=1)
            kind = "rhythm/noise" if summary.is_rhythm else "melody"
            timbre_text = ", ".join(f"5D {value:02X}" for value in summary.timbres) or "no 5D"
            expr_text = ", ".join(f"6D {value:02X}" for value in summary.expressions[:4])
            if len(summary.expressions) > 4:
                expr_text += ", ..."
            label = f"Ch {summary.index} ({kind}; {timbre_text}"
            if expr_text:
                label += f"; {expr_text}"
            if summary.opl_instrument_id is not None:
                label += f"; OPL id {summary.opl_instrument_id:02X}"
                if summary.opl_config is not None:
                    label += f" cfg {summary.opl_config:02X}"
                if summary.opl_voice_level is not None:
                    label += f" lvl {summary.opl_voice_level:02X}"
            label += ")"
            ttk.Label(row, text=label, width=52).pack(side=tk.LEFT)
            var = tk.StringVar()
            if summary.default_program is None:
                default_index = 0
            else:
                default_index = max(0, min(127, summary.default_program))
            var.set(self.audio_gm_choices[default_index])
            self.audio_channel_program_vars[summary.index] = var
            self.audio_channel_default_programs[summary.index] = default_index if summary.default_program is not None else None
            combo = ttk.Combobox(row, values=self.audio_gm_choices, textvariable=var, width=32, state="readonly")
            combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def reset_audio_channel_defaults(self) -> None:
        for index, var in self.audio_channel_program_vars.items():
            default = self.audio_channel_default_programs.get(index)
            default_index = 0 if default is None else max(0, min(127, int(default)))
            var.set(self.audio_gm_choices[default_index])

    def _audio_channel_program_overrides(self) -> dict[int, int | None]:
        """Return only user-edited GM programs.

        An empty dict means: use the original MIDI export mapping unchanged.
        Edited channels are pinned to the chosen program for the whole MIDI export.
        """
        overrides: dict[int, int | None] = {}
        for index, var in self.audio_channel_program_vars.items():
            text = var.get().strip()
            try:
                program = int(text.split(":", 1)[0])
            except Exception:
                continue
            default = self.audio_channel_default_programs.get(index)
            if default is None:
                if program != 0:
                    overrides[index] = program
            elif program != default:
                overrides[index] = program
        return overrides

    def _write_selected_music_midi(self, path: Path | str) -> Path:
        item = self._selected_audio_item()
        if item is None:
            raise RuntimeError("No audio item selected")
        if item.kind not in {"soundcard-music", "pc-speaker-music"}:
            raise RuntimeError("MIDI export is available for music resources only")
        return write_midi(
            item.data,
            path,
            speed=self._audio_preview_speed(),
            audio_kind=item.kind,
            channel_programs=self._audio_channel_program_overrides(),
        )

    def stop_audio_preview(self) -> None:
        try:
            self._audio_preview_generation = getattr(self, "_audio_preview_generation", 0) + 1
            stop_audio_playback()
            self.status.set("Audio preview stopped")
        except Exception as exc:
            messagebox.showerror("Stop failed", str(exc))

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
        generation = getattr(self, "_audio_preview_generation", 0) + 1
        self._audio_preview_generation = generation
        speed = self._audio_preview_speed()
        results: Queue[tuple[Path | None, Exception | None]] = Queue(maxsize=1)

        def render() -> None:
            try:
                # Worker threads only synthesize files. Tk and audio-player calls
                # remain on the UI thread inside poll().
                wav_path = temp_preview_wav(item, speed=speed, exe_path=self.project.exe)
                results.put((wav_path, None))
            except Exception as exc:
                results.put((None, exc))

        def poll() -> None:
            if generation != getattr(self, "_audio_preview_generation", 0):
                return
            try:
                wav_path, error = results.get_nowait()
            except Empty:
                self.after(40, poll)
                return
            if error is not None:
                messagebox.showerror("Audio playback failed", str(error))
                return
            try:
                play_audio_file(wav_path)
                self.status.set(f"Playing synthesized preview for {item.label}")
            except Exception as exc:
                messagebox.showerror("Audio playback failed", str(exc))

        self.status.set(f"Preparing audio preview for {item.label}...")
        Thread(target=render, name="audio-preview-render", daemon=True).start()
        self.after(0, poll)

    def export_selected_audio_wav(self) -> None:
        item = self._selected_audio_item()
        if item is None:
            return
        default = (item.label.replace("/", "_").replace(" ", "_").replace(":", "") + ".wav")
        path = filedialog.asksaveasfilename(defaultextension=".wav", initialfile=default, filetypes=[("WAV audio", "*.wav")])
        if not path:
            return
        try:
            if item.kind == "soundcard-music":
                synthesize_soundcard_music_wav(item.data, self.project.exe, path, speed=self._audio_preview_speed())
            else:
                synthesize_wav(item.data, path, music=item.kind != "pc-speaker-sfx", speed=self._audio_preview_speed(), audio_kind=item.kind)
            self.status.set(f"Exported WAV preview: {path}")
        except Exception as exc:
            messagebox.showerror("WAV export failed", str(exc))

    def export_selected_audio_raw(self) -> None:
        item = self._selected_audio_item()
        if item is None:
            return
        ext = ".ae_sfx" if item.kind == "pc-speaker-sfx" else (".ae_music" if "music" in item.kind or item.kind in {"pc-speaker-music"} else ".ae_audio")
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
        if item.kind not in {"soundcard-music", "pc-speaker-music"}:
            if not messagebox.askyesno("MIDI export", "This is not classified as music. Export a rough MIDI transcription anyway?"):
                return
        default = item.label.replace("/", "_").replace(" ", "_").replace(":", "") + ".mid"
        path = filedialog.asksaveasfilename(defaultextension=".mid", initialfile=default, filetypes=[("MIDI file", "*.mid")])
        if not path:
            return
        try:
            if item.kind in {"soundcard-music", "pc-speaker-music"}:
                self._write_selected_music_midi(path)
            else:
                write_midi(item.data, path, speed=self._audio_preview_speed(), audio_kind=item.kind)
            self.status.set(f"Exported MIDI: {path}")
        except Exception as exc:
            messagebox.showerror("MIDI export failed", str(exc))

