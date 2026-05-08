# Quick Start Guide

This guide gets the editor running and points you at the most useful tabs first.

## 1. Prepare The Game Files

The repository does not include the original game assets. Put your own copies in
the repository root, next to `run_editor.py`:

```text
AEPROG.EXE
AE000.DAT
AE001.DAT
```

`AEPROG.EXE` supplies the game palette and lookup data. `AE000.DAT` and
`AE001.DAT` supply graphics, levels, actors and room payloads.

## 2. Install Dependencies

Use the same Python executable for dependency installation and launching the
editor:

```bash
python -m pip install -r requirements.txt
```

If launch later fails with `ModuleNotFoundError: No module named 'PIL'`, Pillow
was installed into a different Python environment.

## 3. Launch The Editor

```bash
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT
```

After package installation, the console entry point is also available:

```bash
ae-level-editor --exe AEPROG.EXE AE000.DAT AE001.DAT
```

## First Five Minutes

1. Open **Level viewer** to browse rooms, difficulty parts and overlay presets.
2. Open **Simulation** to let actors run, click controls, press wall symbols and
   move through room links.
3. Open **Editor** to paint terrain and select known objects for property edits.
4. Open **Script space** to inspect actor bytecode, branch targets and DSL text.
5. Use **Save as...** while experimenting. The editor can write understood
   structures back into `AE001.DAT`, but it is still a research editor.

## Useful Exports

Export every rendered room preview:

```bash
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT --export-previews previews
```

Export decoded graphics-bank contact sheets:

```bash
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT --export-bank-sheets sheets
```

Export room, tile and payload probe data:

```bash
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT --export-csv ae_room_probe.csv
```

Regenerate the README/documentation screenshots:

```bash
python tools/capture_docs_screenshots.py --exe AEPROG.EXE --dat AE000.DAT AE001.DAT
```

Screenshot capture opens the Tk editor window and grabs the visible window, so
run it on a desktop session rather than a headless terminal.

## Good Smoke Rooms

- Level 1, Explorer, room 0: clean baseline room with actors and overlays.
- Level 2, Explorer, room 0: laser trigger and crystal cases.
- Level 9, Explorer, room 0: green-block sequence and runtime collision tests.
- Level 9, Explorer, room 6: actor-emitted symbol behavior.
- Level 20, both difficulties, room 0: platform and layout divergence.

## Troubleshooting

- **Missing file errors:** check that `AEPROG.EXE`, `AE000.DAT` and `AE001.DAT`
  are in the paths passed on the command line.
- **Wrong colors:** make sure the editor is using `AEPROG.EXE`; the game palette
  is not the standard VGA palette.
- **Edits feel risky:** use **Save as...** and keep the original `AE001.DAT`
  untouched.
- **Unexpected write behavior:** prefer objects that the property panel
  recognizes. Unknown payload bytes are intentionally shown for research instead
  of guessed as editable game objects.
