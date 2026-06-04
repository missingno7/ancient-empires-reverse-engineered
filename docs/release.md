# Release Checklist

This project ships source code and self-contained Windows executables, but not
the original commercial game assets. Public release bundles must leave
`game_data/` present and empty except for instructions.

## v0.1.0 Scope

Version 0.1.0 is the first public Windows x64 release:

- `AncientEmpires.exe`: player-facing source-port slice for level 1, Explorer,
  room 0 with recovered room rendering, HUD, movement, collision and audio.
- `AncientEmpiresEditor.exe`: Tk research/editor application for browsing,
  rendering, simulation, script inspection and conservative edits to understood
  `AE001.DAT` structures.
- Original assets are required at runtime and are supplied by the user:
  `AEPROG.EXE`, `AE000.DAT`, `AE001.DAT`.

The game is not yet a complete recreation of the original. Ladders, conveyors,
hazards, pickups, room transitions and many actor/enemy behaviors remain active
reverse-engineering work.

## Local Build

Use a normal Python.org/winget Python 3.12 x64 installation with Tkinter and
Microsoft C++ Build Tools. The Codex bundled Python runtime must not be used for
release builds because it does not package Tk correctly.

From a Developer PowerShell for Visual Studio:

```powershell
py -3.12 -m venv .venv-release
$env:Path = "$PWD\.venv-release\Scripts;$env:Path"
python -m pip install -r requirements-build.txt
powershell -ExecutionPolicy Bypass -File tools\build_windows_release.ps1
```

For private testing only, include local `game_data/` assets and run the
asset-backed tests:

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_windows_release.ps1 -IncludeGameData -RunGameDataTests
```

The script runs the asset-free test suite with
`--basetemp build\pytest-tmp -m "not game_data"`, builds both executables,
smoke-tests their frozen imports with `--help`, and writes:

```text
dist\ancient-empires-0.1.0-windows-x64.zip
```

## Publish

Before tagging, inspect the archive and confirm it does not contain original
game assets. The release ZIP should contain the two executables, `LICENSE`,
`README.txt`, and `game_data/README.txt`.

Commit the release work, tag it, and push the branch and tag:

```powershell
git status --short
git add .gitignore README.md ae_editor/app/cli.py ae_game/app/cli.py nuked_opl3/_ffi_build.py requirements-build.txt tools/build_windows_release.ps1 docs/windows_release_readme.txt docs/release.md .github/workflows/windows-release.yml
git commit -m "Prepare v0.1.0 Windows release"
git tag -a v0.1.0 -m "v0.1.0"
git push origin HEAD
git push origin v0.1.0
```

Pushing the tag starts the Windows release workflow. The workflow creates the
GitHub release if needed and uploads the public ZIP.
