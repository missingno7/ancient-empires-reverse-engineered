from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ae_editor.gui import LevelEditorApp
from ae_editor.project import AncientEmpiresProject


SCREENSHOTS: list[dict[str, Any]] = [
    {
        "file": "editor-level-viewer.png",
        "tab": "Level viewer",
        "level": 0,
        "part": 0,
        "room": 0,
        "zoom": 2,
        "status": "Level viewer: decoded room bitmap, native overlays and relationship lines.",
    },
    {
        "file": "editor-simulation.png",
        "tab": "Simulation",
        "level": 8,
        "part": 0,
        "room": 0,
        "zoom": 2,
        "steps": 18,
        "status": "Simulation: actor VM preview, clickable controls, green blocks and room links.",
    },
    {
        "file": "editor-editing.png",
        "tab": "Editor",
        "level": 0,
        "part": 0,
        "room": 0,
        "zoom": 2,
        "status": "Editor: terrain painting, object placement palettes and property editing.",
    },
    {
        "file": "editor-script-space.png",
        "tab": "Script space",
        "level": 0,
        "part": 0,
        "room": 0,
        "zoom": 2,
        "status": "Script space: reachable actor bytecode, branches and DSL preview.",
    },
]


def resolve_path(path_text: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = ROOT / path
    return path


def select_tab(app: LevelEditorApp, name: str) -> None:
    for tab_id in app.main_tabs.tabs():
        if app.main_tabs.tab(tab_id, "text") == name:
            app.main_tabs.select(tab_id)
            return
    raise RuntimeError(f"Tab not found: {name}")


def settle(app: LevelEditorApp, delay: float = 0.2) -> None:
    app.update_idletasks()
    app.update()
    time.sleep(delay)
    app.update_idletasks()
    app.update()


def configure_view(app: LevelEditorApp, spec: dict[str, Any]) -> None:
    app.sim_running_var.set(False)
    app.zoom_var.set(int(spec.get("zoom", 2)))
    app.mode_var.set("game")
    app.overlay_var.set(True)
    app.overlay_labels_var.set(True)
    app.overlay_links_var.set(True)
    app.overlay_hidden_var.set(False)
    app.show_collision_var.set(False)
    app.editor_tool_var.set("select")
    app.editor_overlay_var.set(True)
    app.editor_collision_var.set(True)
    app.set_level(int(spec["level"]))
    app.set_part(int(spec["part"]))
    app.set_room(int(spec["room"]))
    select_tab(app, str(spec["tab"]))
    if spec["tab"] == "Simulation":
        app.reset_simulation(announce=False)
        sim = app.ensure_simulation()
        for _ in range(int(spec.get("steps", 0))):
            sim.step()
        app.redraw_simulation()
    elif spec["tab"] == "Script space":
        app.refresh_actor_scripting_tab()
    else:
        app.redraw_room()
    app.status.set(str(spec["status"]))


def capture_window(app: LevelEditorApp, path: Path) -> None:
    settle(app)
    left = app.winfo_rootx()
    top = app.winfo_rooty()
    right = left + app.winfo_width()
    bottom = top + app.winfo_height()
    ImageGrab.grab(bbox=(left, top, right, bottom)).convert("RGB").save(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture editor screenshots for README/docs.")
    parser.add_argument("--exe", default="AEPROG.EXE", help="Path to AEPROG.EXE.")
    parser.add_argument("--dat", nargs="+", default=["AE000.DAT", "AE001.DAT"], help="DAT files to load.")
    parser.add_argument("--out", default="docs/assets", help="Output directory for PNG screenshots.")
    parser.add_argument("--geometry", default="1500x980+40+40", help="Tk window geometry to capture.")
    args = parser.parse_args()

    exe = resolve_path(args.exe)
    dat_paths = [resolve_path(item) for item in args.dat]
    out_dir = resolve_path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    missing = [path for path in [exe, *dat_paths] if not path.exists()]
    if missing:
        names = ", ".join(str(path) for path in missing)
        raise SystemExit(f"Missing game asset(s): {names}")

    project = AncientEmpiresProject(exe, dat_paths)
    app = LevelEditorApp(project)
    app.geometry(args.geometry)
    try:
        settle(app, 0.3)
        for spec in SCREENSHOTS:
            configure_view(app, spec)
            path = out_dir / str(spec["file"])
            capture_window(app, path)
            print(f"captured {path.relative_to(ROOT)}")
    finally:
        app.close_window()


if __name__ == "__main__":
    main()
