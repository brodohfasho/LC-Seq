# scripts/build_windows.ps1
# Build LC-Seq Windows executable with PyInstaller.
# Compiles and bundles the Rust lcseq extension — end users do not need Rust installed.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not $env:VIRTUAL_ENV) {
    Write-Warning "No virtual environment detected. Activate venv first: .\venv\Scripts\activate"
}

Write-Host "Installing dependencies..."
python -m pip install -q -r requirements.txt
python -m pip install -q -r requirements-build.txt

$EngineDir = Join-Path $Root "LC-Seq-New-master"
Write-Host ""
Write-Host "Building lcseq Rust extension (bundled into release zip)..."
if (-not (Get-Command rustc -ErrorAction SilentlyContinue)) {
    Write-Error @"
rustc is not on PATH. Maintainers need Rust to build the release package.
Install from https://rustup.rs/ then reopen this terminal.

End users who download LC-Seq-v*-windows.zip from GitHub Releases do NOT need Rust.
"@
}
Push-Location $EngineDir
try {
    maturin develop --release
} finally {
    Pop-Location
}

Write-Host "Verifying lcseq extension..."
python -c "import lcseq; from lcseq import find_peaks, evaluate_library; print('lcseq extension OK')"

Write-Host "Running peak-picker parity check..."
python -m pytest tests/test_lcseq_backend_parity.py -q
if ($LASTEXITCODE -ne 0) {
    Write-Error "lcseq parity test failed. Rebuild LC-Seq-New-master before packaging."
}

Write-Host ""
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
    Write-Host "lcseq (Rust) is bundled — release zip users do not need Rust or Python."
    Write-Host "Create a desktop shortcut to LC-Seq.exe to launch with one click."
} else {
    Write-Error "Expected output folder not found: $OutDir"
}
