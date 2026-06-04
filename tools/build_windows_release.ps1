param(
    [switch]$IncludeGameData,
    [switch]$RunGameDataTests,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

if (-not [Environment]::Is64BitProcess) {
    throw "The release must be built with a 64-bit Python interpreter."
}

Invoke-Checked { python -c "import tkinter; import tkinter.ttk" } "Tkinter availability check"
Invoke-Checked {
    python -c "import pathlib, sys; base = pathlib.Path(sys.base_prefix); tcl = base / 'tcl'; assert 'codex-runtimes' not in str(base).lower(), f'use a normal Python.org/winget Python, not Codex runtime: {base}'; assert tcl.exists(), f'Tcl/Tk runtime folder is missing: {tcl}'"
} "Python desktop runtime check"

$VersionLine = Select-String -Path "pyproject.toml" -Pattern '^version = "([^"]+)"$'
if (-not $VersionLine) {
    throw "Could not read the project version from pyproject.toml."
}
$Version = $VersionLine.Matches[0].Groups[1].Value
$ReleaseName = "ancient-empires-$Version-windows-x64"
$ReleaseDir = Join-Path $RepoRoot "dist\$ReleaseName"
$ZipPath = Join-Path $RepoRoot "dist\$ReleaseName.zip"

Write-Host "Building Nuked-OPL3 native extension..."
Invoke-Checked { python -m nuked_opl3._ffi_build } "Nuked-OPL3 build"

if (-not $SkipTests) {
    Write-Host "Running tests..."
    $PytestTemp = Join-Path $RepoRoot "build\pytest-tmp"
    if (Test-Path $PytestTemp) {
        Remove-Item -LiteralPath $PytestTemp -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $PytestTemp | Out-Null
    $PytestArgs = @("--basetemp", $PytestTemp)
    if (-not $RunGameDataTests) {
        $PytestArgs += @("-m", "not game_data")
    }
    Invoke-Checked { python -m pytest @PytestArgs } "Test suite"
}

Write-Host "Building game executable..."
Invoke-Checked {
    python -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name AncientEmpires `
        --hidden-import nuked_opl3._opl3_cffi `
        run_game.py
} "Game executable build"

Write-Host "Building editor executable..."
Invoke-Checked {
    python -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name AncientEmpiresEditor `
        --hidden-import nuked_opl3._opl3_cffi `
        run_editor.py
} "Editor executable build"

Write-Host "Smoke-testing frozen executables..."
Invoke-Checked { & "dist\AncientEmpires.exe" --help } "Game executable smoke test"
Invoke-Checked { & "dist\AncientEmpiresEditor.exe" --help } "Editor executable smoke test"

if (Test-Path $ReleaseDir) {
    Remove-Item -LiteralPath $ReleaseDir -Recurse
}
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ReleaseDir "game_data") | Out-Null
Copy-Item "docs\windows_game_data_readme.txt" (Join-Path $ReleaseDir "game_data\README.txt")
Copy-Item "dist\AncientEmpires.exe" $ReleaseDir
Copy-Item "dist\AncientEmpiresEditor.exe" $ReleaseDir
Copy-Item "LICENSE" $ReleaseDir
Copy-Item "docs\windows_release_readme.txt" (Join-Path $ReleaseDir "README.txt")

if ($IncludeGameData) {
    $RequiredAssets = @("AEPROG.EXE", "AE000.DAT", "AE001.DAT")
    foreach ($Asset in $RequiredAssets) {
        $Source = Join-Path $RepoRoot "game_data\$Asset"
        if (-not (Test-Path $Source)) {
            throw "Missing required game asset: $Source"
        }
        Copy-Item $Source (Join-Path $ReleaseDir "game_data")
    }
}

if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath
}
Compress-Archive -Path "$ReleaseDir\*" -DestinationPath $ZipPath

Write-Host ""
Write-Host "Release created:"
Write-Host "  $ReleaseDir"
Write-Host "  $ZipPath"
