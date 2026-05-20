# scripts/build_windows.ps1
# Build LC-Seq Windows executable with PyInstaller.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not $env:VIRTUAL_ENV) {
    Write-Warning "No virtual environment detected. Activate venv first: .\venv\Scripts\activate"
}

Write-Host "Installing dependencies..."
python -m pip install -q -r requirements.txt
python -m pip install -q -r requirements-build.txt

Write-Host "Running PyInstaller..."
python -m PyInstaller lc_seq.spec --noconfirm

$OutDir = Join-Path $Root "dist\LC-Seq"
$ExampleConfig = Join-Path $Root "config\default_config.json.example"
$TargetConfigDir = Join-Path $OutDir "config"

if (Test-Path $OutDir) {
    New-Item -ItemType Directory -Force -Path $TargetConfigDir | Out-Null
    Copy-Item -Force $ExampleConfig (Join-Path $TargetConfigDir "default_config.json.example")
    $DbDir = Join-Path $OutDir "output\databases"
    New-Item -ItemType Directory -Force -Path $DbDir | Out-Null
    Write-Host ""
    Write-Host "Build complete: $OutDir\LC-Seq.exe"
    Write-Host "Create a desktop shortcut to LC-Seq.exe to launch with one click."
} else {
    Write-Error "Expected output folder not found: $OutDir"
}
