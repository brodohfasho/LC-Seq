# scripts/build_windows.ps1
# Build LC-Seq Windows executable with PyInstaller.
# Compiles and bundles the Rust lcseq extension - end users do not need Rust installed.

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
$Exe = Join-Path $OutDir "LC-Seq.exe"

if (-not (Test-Path $OutDir)) {
    Write-Error "Expected output folder not found: $OutDir"
}

New-Item -ItemType Directory -Force -Path $TargetConfigDir | Out-Null
Copy-Item -Force $ExampleConfig (Join-Path $TargetConfigDir "default_config.json.example")
$DbDir = Join-Path $OutDir "output\databases"
New-Item -ItemType Directory -Force -Path $DbDir | Out-Null

Write-Host ""
Write-Host "Verifying frozen imports (scipy, networkx, openpyxl, lcseq)..."
$SmokeFile = Join-Path $OutDir "smoke_imports.txt"
if (Test-Path $SmokeFile) {
    Remove-Item -Force $SmokeFile
}
# Windowed exes often do not surface exit codes reliably; rely on the status file
# written next to LC-Seq.exe. Start-Process -Wait keeps argv intact on Windows.
$proc = Start-Process -FilePath $Exe -ArgumentList "--smoke-imports" -WorkingDirectory $OutDir -PassThru -Wait
if (-not (Test-Path $SmokeFile)) {
    Write-Error @"
Frozen smoke test did not write smoke_imports.txt next to LC-Seq.exe.
Exit code from process: $($proc.ExitCode)
Re-run manually:  cd dist\LC-Seq; .\LC-Seq.exe --smoke-imports
"@
}
Get-Content $SmokeFile | ForEach-Object { Write-Host $_ }
$smokeFailed = Select-String -Path $SmokeFile -Pattern "^FAIL" -Quiet
Remove-Item -Force $SmokeFile -ErrorAction SilentlyContinue
if ($smokeFailed) {
    Write-Error "Frozen import smoke test failed (see FAIL lines above)."
}

Write-Host ""
Write-Host "Build complete: $Exe"
Write-Host "lcseq (Rust) is bundled - release zip users do not need Rust or Python."
Write-Host "Create a desktop shortcut to LC-Seq.exe to launch with one click."
