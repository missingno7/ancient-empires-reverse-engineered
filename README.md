# Ancient Empires Reverse Engineered

A reverse-engineered source port and visual research editor for *Super Solvers:
Challenge of the Ancient Empires*.

![Simulation mode showing a live room preview](docs/assets/editor-simulation.png)

The shared `ancient_empires` package decodes the original assets and contains the
runtime rules recovered so far. `ae_editor` is the Tk research/editor
application. `ae_game` is the player-facing source-port application. For
v0.1.0 it provides the first room-local gameplay slice with recovered rendering,
HUD, player movement, collision and audio playback; the full original game loop
is still being reconstructed from the disassembly in `Decompile notes/`.

The repository and public release ZIPs do not ship original game assets. To run
the editor or game, drop your own legally obtained copies into the `game_data/`
folder:

- `AEPROG.EXE`
- `AE000.DAT`
- `AE001.DAT`

Both applications look in `game_data/` by default. You can also point them at
another folder, or override the executable path with `--exe`.

## Start Here

- [Quick Start Guide](docs/quick_start.md): install, launch and first five
  minutes in the editor.
- [Screenshot Tour](docs/screenshots.md): visual overview of the main editor
  tabs.
- [Simulation Mode](docs/simulation_mode.md): how the runtime preview models
  controls, actors, platforms, room links and green blocks.
- [Shared Engine Architecture](docs/engine_architecture.md): planned boundary
  between the editor, shared gameplay rules and the future real game.
- [Gameplay Reverse Engineering](docs/gameplay_reverse_engineering.md): missing
  systems that must be recovered before the source port is playable.
- [AI Maintainer Context](docs/ai_context.md): compact technical map for future
  coding agents and maintainers.
- [Handoff Notes](docs/handoff.md): current state, smoke rooms and good next
  tasks.

## Editor Launch

```bash
python -m pip install -r requirements.txt
python run_editor.py
```

With no arguments the editor loads the game files from `game_data/`. To use a
different location, pass the folder:

```bash
python run_editor.py path/to/game_files
```

`--exe PATH` overrides just the executable if it lives somewhere else. Use the
same Python executable for installation and for `run_editor.py`. If you see
`ModuleNotFoundError: No module named 'PIL'`, Pillow was installed into a
different Python environment.

The package entry point is also available after installation:

```bash
ae-level-editor              # uses ./game_data
ae-level-editor path/to/game_files
```

## Windows Release

Download `ancient-empires-0.1.0-windows-x64.zip`, extract it, and place your own
game files here:

```text
game_data/AEPROG.EXE
game_data/AE000.DAT
game_data/AE001.DAT
```

Then run:

```text
AncientEmpires.exe
AncientEmpiresEditor.exe
```

The executables include Python and third-party runtime libraries, so users do
not need to install Python.

## Game Launch

```bash
python run_game.py
```

`run_game.py` displays level 1, Explorer, room 0 with the recovered HUD and
player movement. Use the arrow keys to walk and jump. This is the first
room-local gameplay slice; ladders, conveyors, hazards, pickups and room
transitions are still being reconstructed from the original executable.

## Windows Release Build

To create a self-contained Windows x64 release containing both the game and
editor executables, use normal Python 3.12 x64 with Tkinter and MSVC Build
Tools. From a Developer PowerShell:

```powershell
py -3.12 -m venv .venv-release
$env:Path = "$PWD\.venv-release\Scripts;$env:Path"
python -m pip install -r requirements-build.txt
powershell -ExecutionPolicy Bypass -File tools/build_windows_release.ps1
```

The script builds the native Nuked-OPL3 audio extension, runs the asset-free
test suite with `-m "not game_data"`, smoke-tests both frozen executables with `--help`,
and creates `dist/ancient-empires-0.1.0-windows-x64.zip`. The public release
does not include original game assets; users place their legally obtained
`AEPROG.EXE`, `AE000.DAT`, and `AE001.DAT` files in the bundled `game_data`
folder.

For a local/private bundle that includes files already present in
`game_data/` and runs the asset-backed tests too, pass
`-IncludeGameData -RunGameDataTests`.

Pushing a version tag such as `v0.1.0` runs the Windows release workflow,
creates the matching GitHub release if needed, and attaches the generated ZIP.
The workflow can also be run manually to download its artifact without making
a release.

See [docs/release.md](docs/release.md) for the maintainer release checklist.

## What You Can Do

![Level viewer with native overlays](docs/assets/editor-level-viewer.png)

- Browse all 20 levels across Explorer and Expert difficulty parts.
- Render pixel-art room previews at multiple zoom levels using the palette from
  `AEPROG.EXE`. Terrain, objects, actors and pickups are placed with the same
  sprite-blitter math recovered from the EXE, so previews match the game's
  layering and pixel positions rather than screenshot guesses.
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

Export all room previews (reads `game_data/`; add a folder argument to use a
different location):

```bash
python run_editor.py --export-previews previews
```

Export decoded graphics-bank contact sheets:

```bash
python run_editor.py --export-bank-sheets sheets
```

Export room, tile and payload probe data:

```bash
python run_editor.py --export-csv ae_room_probe.csv
```

Regenerate documentation screenshots:

```bash
python tools/capture_docs_screenshots.py --exe game_data/AEPROG.EXE --dat game_data/AE000.DAT game_data/AE001.DAT
```

Probe one room payload:

```bash
python tools/probe_exe_payload.py --exe game_data/AEPROG.EXE --level 6 --difficulty Explorer --room 5 game_data/AE000.DAT game_data/AE001.DAT
```

Run the test suite using a repository-local pytest temp folder:

```bash
python -m pytest --basetemp build/pytest-tmp
```

Run only tests that do not require original game assets:

```bash
python -m pytest --basetemp build/pytest-tmp -m "not game_data"
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
- [Release Checklist](docs/release.md): v0.1.0 Windows build and publish steps.

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

The 3000-byte actor block follows the ten room records and is parsed as its own
section. See [docs/level_format.md](docs/level_format.md) for the canonical
format notes.

## Project Layout

```text
ancient_empires/
  project.py                  shared loaded asset bundle
  constants.py                shared recovered constants
  game_data/                  DAT/EXE decoders and editable binary models
  engine/                     shared deterministic runtime rules
  rendering/                  shared visual interpretation and room rendering
  audio/                      shared audio decode, playback and export
  exporters/                  shared PNG/CSV export helpers

ae_editor/
  app/
    cli.py                    command-line entry point and argument parsing
    main_window.py            Tkinter editor window and tab wiring
  ui/                         Tkinter tabs (editor, simulation, script, audio)

ae_game/
  app/cli.py                  player-facing source-port entry point

run_editor.py
run_game.py

docs/
  assets/            README and documentation screenshots
  quick_start.md
  screenshots.md
  simulation_mode.md
  ai_context.md
  level_format.md
  file_format_summary.md
  reverse_engineering_notes.md
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
