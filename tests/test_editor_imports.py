"""Guard the ae_editor.ui.common re-export facade: every consumer must import."""
import importlib
import re
from pathlib import Path

import pytest


def test_editor_app_modules_import():
    # Catches a missing re-export in common.py (e.g. AncientEmpiresProject).
    importlib.import_module("ae_editor.app.main_window")
    importlib.import_module("ae_editor.app.cli")


def test_all_names_imported_from_common_are_exported():
    common = importlib.import_module("ae_editor.ui.common")
    available = set(dir(common))
    pattern = re.compile(
        r"from (?:\.\.ui\.common|\.common|ae_editor\.ui\.common) import \(([^)]*)\)"
    )
    missing = []
    for path in Path("ae_editor").rglob("*.py"):
        if path.name == "common.py":
            continue
        for block in pattern.findall(path.read_text(encoding="utf-8")):
            for name in block.replace("\n", " ").split(","):
                name = name.strip().split(" as ")[0].strip()
                if name and name not in available:
                    missing.append((path.name, name))
    assert not missing, f"common.py is missing re-exports: {missing}"
