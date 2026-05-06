from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, ttk

from PIL import Image, ImageTk

from .constants import CELL_SIZE, ROOM_COUNT, ROOM_COLUMNS, ROOM_ROWS
from .exporters import export_bank_sheets, export_probe_csv, export_room_previews
from .overlay import build_room_overlay
from .project import AncientEmpiresProject
from .renderer import RenderOptions
from .room_payload import (
    actor_records_for_room,
    header_object_candidates,
    laser_crystal_table,
    parse_exe_payload_directory,
    parse_platform_triplets,
    transition_links_for_room,
    visual_compact3_table,
)

DIFFICULTY_LABELS = ["Explorer", "Expert"]


@dataclass(frozen=True)
class OverlayOptionSpec:
    label: str
    var_name: str
    default: bool
    minimal: bool
    logic: bool
    debug: bool


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
        self.overlay_var = tk.BooleanVar(value=True)
        self.overlay_labels_var = tk.BooleanVar(value=True)
        self.overlay_links_var = tk.BooleanVar(value=True)
        self.overlay_hidden_var = tk.BooleanVar(value=False)

        for spec in OVERLAY_OPTION_SPECS:
            setattr(self, spec.var_name, tk.BooleanVar(value=spec.default))
        first_bank = next(iter(project.graphics.banks.keys()), "AE001:021")
        self.bank_var = tk.StringVar(value=first_bank)
        self.status = tk.StringVar(value="")
        self.tk_image = None
        self.tk_sheet = None
        self.tk_atlas_images = []

        self._build_ui()
        self.redraw_room()
        self.redraw_bank_sheet()
        self.redraw_objects_atlas()

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
        mode = ttk.Combobox(top, textvariable=self.mode_var, state="readonly", width=13, values=["game", "collision", "payload_debug", "codes_hex", "trailing_hex"])
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

        self.status_label = ttk.Label(self, textvariable=self.status, justify=tk.LEFT, anchor="w")
        self.status_label.pack(side=tk.TOP, fill=tk.X, padx=6)
        self.status_label.bind("<Configure>", lambda event: self.status_label.configure(wraplength=max(200, event.width - 12)))

        tabs = ttk.Notebook(self)
        tabs.pack(fill=tk.BOTH, expand=True)

        level_tab = ttk.Frame(tabs)
        graphics_tab = ttk.Frame(tabs)
        objects_tab = ttk.Frame(tabs)
        tabs.add(level_tab, text="Level viewer")
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

    def set_part(self, index: int) -> None:
        self.part_var.set(index)
        self.part_combo.current(index)
        self.refresh_room_labels()
        self.redraw_room()
        self.redraw_objects_atlas()

    def set_level(self, index: int) -> None:
        self.level_var.set(index)
        self.refresh_room_labels()
        self.redraw_room()
        self.redraw_objects_atlas()

    def set_room(self, index: int) -> None:
        self.room_var.set(index)
        self.room_combo.current(index)
        self.redraw_room()
        self.redraw_objects_atlas()

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
        links = transition_links_for_room(part, room.index)
        controls = 0 if directory is None else len(directory.control_records)
        visual_txt = "none" if visual is None else f"@{visual.offset:02X} n={visual.count}"
        crystal_txt = "none" if crystals is None else f"@{crystals.offset:02X} n={crystals.count}"
        platforms = ", ".join(p.label for p in parse_platform_triplets(room)) or "none"
        self.status.set(
            f"level={level.index + 1} difficulty={DIFFICULTY_LABELS[part.index]} room={room.index} theme={part.theme} "
            f"room_quality={room.quality_label} terrain_off=0x{room.terrain_offset:04X} preamble={room.preamble.hex(' ')} "
            f"platforms=[{platforms}] controls={controls} actors={len(actors)} links={links.label if links else 'none'} "
            f"crystals={crystal_txt} visual={visual_txt} "
            f"unique_tiles={unique} footer={part.footer.hex(' ')}"
        )
        if self.mode_var.get() == "codes_hex":
            self.draw_codes_overlay(room)
        elif self.mode_var.get() == "trailing_hex":
            self.draw_trailing_overlay(room)
        elif self.overlay_var.get():
            self.draw_room_overlay(level, part, room)

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
        dynamic sections summarize the currently selected room so the atlas also
        works as a lightweight object inspector.
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
                    ("Diamond / artifact", "AE000", 44, 0, "header room object"),
                    ("Apple", "AE000", 45, 0, "verified collectible, schema still WIP"),
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
                    ("Horizontal platform", "AE000", 47, 0, "platform flags 40/60"),
                    ("Vertical platform", "AE000", 48, 0, "platform flags 80/A0"),
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
        if pickups:
            dynamic.append(("Current room: pickups", pickups))

        return dynamic + static

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

    def redraw_objects_atlas(self) -> None:
        if not hasattr(self, "objects_canvas"):
            return
        self.objects_canvas.delete("all")
        self.tk_atlas_images = []

        x0 = 12
        y = 12
        category_font = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        item_font = tkfont.Font(family="Segoe UI", size=9)
        note_font = tkfont.Font(family="Segoe UI", size=8)

        for title, items in self.atlas_categories():
            self.objects_canvas.create_text(x0, y, anchor="nw", text=title, fill="#ffffff", font=category_font)
            y += 24

            col_w = 170
            row_h = 66
            cols = 4
            for idx, (label, archive, resource_id, sprite_index, note) in enumerate(items):
                col = idx % cols
                row = idx // cols
                x = x0 + col * col_w
                yy = y + row * row_h

                self.objects_canvas.create_rectangle(x, yy, x + col_w - 8, yy + row_h - 8, outline="#555555", fill="#2b2b2b")
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
                self.objects_canvas.create_text(x + 48, yy + 43, anchor="nw", text=note[:24], fill="#c8c8c8", font=note_font)

            rows = (len(items) + cols - 1) // cols
            y += rows * row_h + 14

        self.objects_canvas.config(scrollregion=(0, 0, 12 + 4 * 170, y + 20))

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
