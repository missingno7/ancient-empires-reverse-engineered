# Project structure

The editor is split into small packages with one-way dependencies. Import paths now
point directly at the package that owns the logic; there are no old top-level
redirect modules.

```text
ae_editor/
  app/          CLI entry point and Tk main window shell.
  game_data/    Low-level decoders/parsers for original game data.
  rendering/    Room rendering, visual mapping, overlays, coordinates.
  audio/        Audio atlas, PC speaker / sound-card decode, MIDI/WAV export.
  simulation/   Runtime-oriented room simulation helpers.
  ui/           Tkinter tabs, widgets, palette panels, and editor actions.
  exporters/    CLI/export helpers for previews, CSV probes, bank sheets.
```

Recommended dependency direction:

```text
game_data
   ↓
rendering / audio / simulation
   ↓
ui
   ↓
app
```


## app

- `app/cli.py` — command line parsing and startup.
- `app/main_window.py` — `LevelEditorApp`, the small Tk shell that combines UI mixins.

## game_data

- `dat_archive.py` — DAT archive offsets and resource access.
- `compression.py` — original resource compression helpers.
- `graphics.py` — graphics resource decoding and `GraphicsSet`.
- `palette.py` — EGA/VGA palette helpers.
- `game_graphics_records.py` — game graphics bitmap records marked by byte `0x47`.
- `level_format.py` — level/part/room binary format.
- `room_payload.py` — room payload tables, object/control/platform records.
- `actor_dsl.py` — lossless actor VM DSL / assembler-like IR.
- `actor_scripts.py` — actor bytecode disassembly and path summaries.
- `conveyors.py` — conveyor record decoding/composition.

## rendering

- `room_renderer.py` — final room rendering from decoded game data.
- `overlay.py` — diagnostic/editor overlays.
- `coordinates.py` — runtime/editor coordinate conversions.
- `object_mapping.py` — visual object-to-sprite mapping.
- `tile_mapping.py` — terrain and collision tile mappings.

## audio

- `core.py` — audio atlas, stream parsing, MIDI/WAV/VGM export.
- `playback.py` — realtime PC-speaker/YM3812 callback playback, shared preview
  workers, cached WAV fallback and subprocess playback lifecycle.
- `gm.py` — General MIDI names/default mapping.

## simulation

- `room_simulation.py` — room simulation and actor/control stepping helpers.

## ui

- `ui/audio_tab.py` — Audio Atlas controls, preview, WAV/RAW/MIDI export.
- `ui/simulation_tab.py` — simulation tab, runtime stepping, actor/control debugging.
- `ui/actor_scripting_tab.py` — actor script viewer/editor and DSL preview.
- `ui/editor_tab.py` — main editor tab construction and shared editor state helpers.
- `ui/editor_tools.py` — editing tools, parsing, footprint rewriting, property panel logic.
- `ui/editor_canvas.py` — room canvas drawing, handles, painting, placement, movement, deletion.
- `ui/palettes.py` — tile/object/decor/actor palettes and graphics bank preview.
- `ui/navigation.py` — level/room/part switching and redraw orchestration.
- `ui/file_actions.py` — save/export/close actions.
- `ui/common.py` — shared imports, small UI dataclasses, constants, and palette specs.

## exporters

- `exporters/core.py` — room preview, bank sheet, and probe CSV exports.
