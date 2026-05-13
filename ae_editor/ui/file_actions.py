from __future__ import annotations

from .common import (
    DIFFICULTY_LABELS,
    Path,
    export_bank_sheets,
    export_probe_csv,
    export_room_previews,
    filedialog,
    messagebox,
    tk,
)


class FileActionsMixin:
    def _after_save(self, path: Path) -> None:
        if hasattr(self, "undo_level_bytes"):
            self.undo_level_bytes = {level.index: level.to_bytes() for level in self.project.levels}
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
        if self.sim_after_id is not None:
            try:
                self.after_cancel(self.sim_after_id)
            except tk.TclError:
                pass
            self.sim_after_id = None
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
