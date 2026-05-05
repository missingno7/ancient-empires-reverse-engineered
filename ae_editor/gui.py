from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from PIL import ImageTk

from .constants import CELL_SIZE, LEVEL_PART_COUNT, ROOM_COLUMNS, ROOM_COUNT, ROOM_ROWS
from .exporters import export_bank_sheets, export_probe_csv, export_room_previews
from .project import AncientEmpiresProject
from .renderer import RenderOptions
from .room_payload import parse_room_payload


class LevelEditorApp(tk.Tk):
    def __init__(self, project: AncientEmpiresProject):
        super().__init__()
        self.project = project
        self.title("Ancient Empires Level Editor - v25 tile-anchor research build")
        self.geometry("1220x840")

        self.level_var = tk.IntVar(value=0)
        self.room_var = tk.IntVar(value=0)
        self.part_var = tk.IntVar(value=0)
        self.zoom_var = tk.IntVar(value=2)
        self.mode_var = tk.StringVar(value="terrain_objects")
        self.grid_var = tk.BooleanVar(value=False)
        self.crop_var = tk.BooleanVar(value=False)
        self.probe_var = tk.BooleanVar(value=False)
        self.align_var = tk.BooleanVar(value=False)
        self.tile_anchor_var = tk.BooleanVar(value=True)
        first_bank = next(iter(project.graphics.banks.keys()), "AE001:021")
        self.bank_var = tk.StringVar(value=first_bank)
        self.status = tk.StringVar(value="")
        self.tk_image = None
        self.tk_sheet = None

        self._build_ui()
        self.redraw_room()
        self.redraw_bank_sheet()

    def _build_ui(self) -> None:
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=5, pady=4)

        ttk.Label(top, text="Level").pack(side=tk.LEFT)
        self.level_combo = ttk.Combobox(
            top,
            state="readonly",
            width=16,
            values=[f"{i + 1:02d} theme {level.theme}" for i, level in enumerate(self.project.levels)],
        )
        self.level_combo.current(0)
        self.level_combo.pack(side=tk.LEFT)
        self.level_combo.bind("<<ComboboxSelected>>", lambda _event: self.set_level(self.level_combo.current()))

        ttk.Label(top, text="Page").pack(side=tk.LEFT, padx=(10, 0))
        self.part_combo = ttk.Combobox(top, state="readonly", width=7, values=["A", "B"])
        self.part_combo.current(0)
        self.part_combo.pack(side=tk.LEFT)
        self.part_combo.bind("<<ComboboxSelected>>", lambda _event: self.set_part(self.part_combo.current()))

        ttk.Label(top, text="Room").pack(side=tk.LEFT, padx=(10, 0))
        self.room_combo = ttk.Combobox(top, state="readonly", width=5, values=[f"{i:02d}" for i in range(ROOM_COUNT)])
        self.room_combo.current(0)
        self.room_combo.pack(side=tk.LEFT)
        self.room_combo.bind("<<ComboboxSelected>>", lambda _event: self.set_room(self.room_combo.current()))
        ttk.Button(top, text="Prev", command=lambda: self.set_room((self.room_var.get() - 1) % ROOM_COUNT)).pack(side=tk.LEFT)
        ttk.Button(top, text="Next", command=lambda: self.set_room((self.room_var.get() + 1) % ROOM_COUNT)).pack(side=tk.LEFT)

        ttk.Label(top, text="Mode").pack(side=tk.LEFT, padx=(10, 0))
        mode = ttk.Combobox(top, textvariable=self.mode_var, state="readonly", width=14, values=["terrain", "terrain_objects", "object_anchors", "exe_sections", "collision_debug", "object_table", "terrain_payload", "payload_probe", "codes_hex", "codes_dec", "trailing_hex"])
        mode.pack(side=tk.LEFT)
        mode.bind("<<ComboboxSelected>>", lambda _event: self.redraw_room())

        ttk.Checkbutton(top, text="legacy crop left 2", variable=self.crop_var, command=self.redraw_room).pack(side=tk.LEFT, padx=6)
        ttk.Checkbutton(top, text="test +4,+4 align", variable=self.align_var, command=self.redraw_room).pack(side=tk.LEFT)
        ttk.Checkbutton(top, text="tile anchor -4,-4", variable=self.tile_anchor_var, command=self.redraw_room).pack(side=tk.LEFT, padx=6)
        ttk.Checkbutton(top, text="grid", variable=self.grid_var, command=self.redraw_room).pack(side=tk.LEFT)
        ttk.Checkbutton(top, text="header probe", variable=self.probe_var, command=self.redraw_room).pack(side=tk.LEFT, padx=6)

        ttk.Label(top, text="Zoom").pack(side=tk.LEFT)
        zoom = ttk.Combobox(top, textvariable=self.zoom_var, state="readonly", width=3, values=[1, 2, 3, 4])
        zoom.pack(side=tk.LEFT)
        zoom.bind("<<ComboboxSelected>>", lambda _event: self.redraw_room())

        ttk.Button(top, text="Export current", command=self.export_current).pack(side=tk.LEFT, padx=8)
        ttk.Button(top, text="Export all rooms", command=self.export_all_rooms).pack(side=tk.LEFT)
        ttk.Button(top, text="Export CSV", command=self.export_csv).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Export bank sheets", command=self.export_sheets).pack(side=tk.LEFT)

        ttk.Label(self, textvariable=self.status).pack(side=tk.TOP, fill=tk.X, padx=6)

        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left, weight=4)
        main.add(right, weight=1)

        self.canvas = tk.Canvas(left, bg="black")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self.click_room)

        bank_top = ttk.Frame(right)
        bank_top.pack(fill=tk.X)
        ttk.Label(bank_top, text="Bank").pack(side=tk.LEFT)
        self.bank_combo = ttk.Combobox(
            bank_top,
            state="readonly",
            width=11,
            values=list(self.project.graphics.banks.keys()),
            textvariable=self.bank_var,
        )
        self.bank_combo.pack(side=tk.LEFT)
        self.bank_combo.bind("<<ComboboxSelected>>", lambda _event: self.redraw_bank_sheet())
        self.bank_canvas = tk.Canvas(right, bg="white")
        self.bank_canvas.pack(fill=tk.BOTH, expand=True)

    def options(self, zoom: int | None = None) -> RenderOptions:
        return RenderOptions(
            mode=self.mode_var.get(),
            zoom=self.zoom_var.get() if zoom is None else zoom,
            grid=self.grid_var.get(),
            crop_left_columns=2 if self.crop_var.get() else 0,
            header_probe=self.probe_var.get(),
            part_index=self.part_var.get(),
            origin_x=4 if self.align_var.get() else 0,
            origin_y=4 if self.align_var.get() else 0,
            terrain_anchor_x=-4 if self.tile_anchor_var.get() else 0,
            terrain_anchor_y=-4 if self.tile_anchor_var.get() else 0,
        )

    def current_level(self):
        return self.project.levels[self.level_var.get()]

    def current_image(self, zoom: int | None = None):
        return self.project.renderer.render_room(self.current_level(), self.room_var.get(), self.options(zoom))

    def set_part(self, index: int) -> None:
        self.part_var.set(index)
        self.part_combo.current(index)
        self.redraw_room()

    def set_level(self, index: int) -> None:
        self.level_var.set(index)
        self.redraw_room()

    def set_room(self, index: int) -> None:
        self.room_var.set(index)
        self.room_combo.current(index)
        self.redraw_room()

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
        payload = parse_room_payload(room)
        best = payload.best_table
        best_txt = "none" if best is None else f"off=0x{best.offset:02X} {best.schema} n={best.count} score={best.score}"
        lead_txt = "; ".join(p.label for p in payload.leading_triplets) or "none"
        self.status.set(
            f"level={level.index + 1} page={chr(65 + part.index)} room={room.index} theme={part.theme} "
            f"terrain_off=0x{room.terrain_offset:04X} preamble={room.preamble.hex(' ')} "
            f"payload_nonzero={sum(1 for b in room.trailing if b)} lead=[{lead_txt}] best_payload={best_txt} "
            f"unique_tiles={unique} header[0..1f]={part.header[:32].hex(' ')} footer={part.footer.hex(' ')}"
        )

    def redraw_bank_sheet(self) -> None:
        rid = self.bank_var.get() or next(iter(self.project.graphics.banks.keys()), "AE001:021")
        sheet = self.project.graphics.make_bank_sheet(rid, self.project.graphics.banks.get(rid, []))
        self.tk_sheet = ImageTk.PhotoImage(sheet)
        self.bank_canvas.delete("all")
        self.bank_canvas.create_image(0, 0, anchor="nw", image=self.tk_sheet)
        self.bank_canvas.config(scrollregion=(0, 0, sheet.width, sheet.height))

    def click_room(self, event) -> None:
        zoom = self.zoom_var.get()
        x = int(self.canvas.canvasx(event.x) // (CELL_SIZE * zoom))
        y = int(self.canvas.canvasy(event.y) // (CELL_SIZE * zoom))
        if self.crop_var.get():
            x += 2
        if 0 <= x < ROOM_COLUMNS and 0 <= y < ROOM_ROWS:
            value = self.current_level().room(self.room_var.get(), self.part_var.get()).get(x, y)
            self.status.set(self.status.get() + f" | click x={x} y={y} tile={value:02X}/{value}")

    def export_current(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".png", initialfile=f"level_{self.level_var.get()+1:02d}_page_{chr(65+self.part_var.get())}_room_{self.room_var.get():02d}.png")
        if path:
            self.current_image(zoom=1).save(path)

    def export_all_rooms(self) -> None:
        directory = filedialog.askdirectory(title="Export room previews")
        if directory:
            export_room_previews(self.project, Path(directory), crop_left=2 if self.crop_var.get() else 0)

    def export_csv(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="ae_level_probe.csv")
        if path:
            export_probe_csv(self.project, Path(path))

    def export_sheets(self) -> None:
        directory = filedialog.askdirectory(title="Export bank sheets")
        if directory:
            export_bank_sheets(self.project, Path(directory))
