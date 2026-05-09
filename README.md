# Ancient Empires Research Editor

A visual level editor, renderer and simulation workbench for *Super Solvers:
Challenge of the Ancient Empires*.

![Simulation mode showing a live room preview](docs/assets/editor-simulation.png)

This project is for people who want to inspect, understand and safely experiment
with the original DOS game's level data. It can decode the game archives, render
rooms with overlays, edit known room structures, inspect actor bytecode and run a
room-local Simulation tab where actors, switches, platforms, green blocks and
room links can be tested before writing anything back.

The repository does not ship original game assets. To run the editor, provide
your own copies of:

- `AEPROG.EXE`
- `AE000.DAT`
- `AE001.DAT`

## Start Here

- [Quick Start Guide](docs/quick_start.md): install, launch and first five
  minutes in the editor.
- [Screenshot Tour](docs/screenshots.md): visual overview of the main editor
  tabs.
- [Simulation Mode](docs/simulation_mode.md): how the runtime preview models
  controls, actors, platforms, room links and green blocks.
- [AI Maintainer Context](docs/ai_context.md): compact technical map for future
  coding agents and maintainers.
- [Handoff Notes](docs/handoff.md): current state, smoke rooms and good next
  tasks.

## Quick Launch

```bash
python -m pip install -r requirements.txt
python run_editor.py --exe AEPROG.EXE AE000.DAT AE001.DAT
```

Use the same Python executable for installation and for `run_editor.py`. If you
see `ModuleNotFoundError: No module named 'PIL'`, Pillow was installed into a
different Python environment.

The package entry point is also available after installation:

```bash
ae-level-editor --exe AEPROG.EXE AE000.DAT AE001.DAT
```

## What You Can Do

![Level viewer with native overlays](docs/assets/editor-level-viewer.png)

- Browse all 20 levels across Explorer and Expert difficulty parts.
- Render pixel-art room previews at multiple zoom levels using the palette from
  `AEPROG.EXE`.
- Toggle overlays for terrain, controls, actors, hidden objects, room exits,
  moving platforms, puzzle data and relationship lines.
- Use the Editor tab to paint terrain, place known objects, drag supported
  structures and edit properties for understood payload records.
- Use Simulation to run room-local actor VM stepping, click controls, emit wall
  symbols, move the player position with right click and navigate through room
  links.
- Select actors in Simulation to inspect their live script state and highlighted
  current VM instruction while stepping.
- Inspect object atlases, graphics-bank sheets and audio resources.
- Decode actor script space into instruction rows, branch references and a DSL
  preview.
- Export PNG previews, graphics sheets and CSV probe data for regression checks.

## Editing Surface

![Editor tab with object palette and properties](docs/assets/editor-editing.png)

The editor is conservative by design. Confirmed structures get real UI and
write helpers; uncertain bytes stay visible through overlays, debug views and
probe exports instead of being guessed into fake objects. Use **Save as...** for
experiments and keep your original `AE001.DAT` untouched.

Currently understood write paths include terrain, known header object slots,
room links, controls, symbol markers, green blocks, visual decor, animated
decor, reflectors, actors, moving-platform triplets and composite conveyor
belts.

## Script Research

![Script space with actor bytecode and DSL preview](docs/assets/editor-script-space.png)

The Script space tab keeps actor behavior close to the room view. It decodes
reachable bytecode, shows branch targets and provides focused instruction
editing for contiguous writable regions. The goal is to make behavior research
visible and repeatable without hiding the raw model.

## Useful Commands

Export all room previews:

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

Regenerate documentation screenshots:

```bash
python tools/capture_docs_screenshots.py --exe AEPROG.EXE --dat AE000.DAT AE001.DAT
```

Probe one room payload:

```bash
python tools/probe_exe_payload.py --exe AEPROG.EXE --level 6 --difficulty Explorer --room 5 AE000.DAT AE001.DAT
```

## Technical References

- [Level Format](docs/level_format.md): current canonical parser model.
- [File Format Summary](docs/file_format_summary.md): compact archive and level
  structure notes.
- [Reverse Engineering Notes](docs/reverse_engineering_notes.md): recovered
  behavior and open questions.
- [Actor Script Space](docs/actor_script_space.md): shared bytecode region and
  safe editing model.
- [Actor DSL](docs/actor_dsl.md): editable script syntax.
- [Editor Overhaul Notes](docs/editor_overhaul_notes.md): historical design and
  cleanup context.

## Current Data Model

`AE000.DAT` and `AE001.DAT` are resource archives with a 32-bit little-endian
offset table. `AE000.DAT` contains global gameplay/UI graphics, actors, pickups,
switches, projectiles, ropes and moving-platform sprites. `AE001.DAT` contains
the 20 level resources plus terrain and theme-decoration banks.

`AE001.DAT` resources `0..19` are levels. Each level resource contains two
difficulty parts:

```text
part 0 = Explorer
part 1 = Expert
```

Each difficulty part currently parses as:

```text
0x40-byte part header
10 room records * 1000 bytes
  +0x000..0x001  room preamble / metadata
  +0x002..0x2AD  terrain: 38 * 18 bytes, row-major
  +0x2AE..0x3E7  room payload: platforms, controls, compact3 sections
0x04 separator
0x0BB8 actor block
```

The old 13-room interpretation was a parser artifact: the 3000-byte actor block
is the same size as three room records, so it used to appear as garbage rooms
10..12. The editor now exposes only rooms 0..9 and treats the actor block as its
own section. See [docs/level_format.md](docs/level_format.md) for the canonical
format notes.

## Project Layout

```text
ae_editor/
  cli.py             command-line entry point
  compression.py     DAT decompression
  dat_archive.py     DAT archive reader
  palette.py         AEPROG.EXE VGA palette extraction
  type47.py          type 0x47 image decoder
  level_format.py    level / difficulty / room parser
  room_payload.py    room payload and actor-table parser
  tile_mapping.py    current terrain code mapping
  coordinates.py     coordinate transforms
  object_mapping.py  compact3 visual code mapping
  renderer.py        static room renderer
  simulation.py      in-memory simulation runtime
  overlay.py         editor overlay model
  gui.py             Tkinter editor UI
  exporters.py       PNG/CSV export helpers

docs/
  assets/            README and documentation screenshots
  quick_start.md
  screenshots.md
  simulation_mode.md
  ai_context.md
  level_format.md
  file_format_summary.md
  reverse_engineering_notes.md
  editor_overhaul_notes.md
  actor_script_space.md
  actor_dsl.md
  handoff.md
```

## Still Unsolved

- exact EXE lookup table for all terrain and visual object codes;
- exact gameplay semantics for every trigger/control byte and every VM event id;
- complete actor/enemy behavior scripts and exact call-stack/runtime timing;
- collectible schemas beyond confirmed rendered cases.

The renderer and editor prefer evidence over invention: confirmed structures are
drawn and edited normally, while uncertain data remains inspectable through
overlay/debug tooling.


## Developer notes

- Current module layout is documented in [`docs/project_structure.md`](docs/project_structure.md).
