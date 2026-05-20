# scripts/package_release.ps1
# Zip dist/LC-Seq for GitHub Releases (run after build_windows.ps1).

param(
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not $Version) {
    $initPy = Join-Path $Root "src\__init__.py"
    $initText = Get-Content -Raw -Path $initPy
    if ($initText -notmatch '__version__\s*=\s*"([^"]+)"') {
        Write-Error "Could not read __version__ from src/__init__.py. Pass -Version 1.0.0"
    }
    $Version = $Matches[1]
}

$DistDir = Join-Path $Root "dist\LC-Seq"
$Exe = Join-Path $DistDir "LC-Seq.exe"
if (-not (Test-Path $Exe)) {
    Write-Error "Missing $Exe - run .\scripts\build_windows.ps1 first."
}

$ReleaseDir = Join-Path $Root "release"
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

$ZipName = "LC-Seq-v$Version-windows.zip"
$ZipPath = Join-Path $ReleaseDir $ZipName

if (Test-Path $ZipPath) {
    Remove-Item -Force $ZipPath
}

Write-Host "Packaging $DistDir -> $ZipPath"
Compress-Archive -Path $DistDir -DestinationPath $ZipPath -CompressionLevel Optimal

$SizeMb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
Write-Host ""
Write-Host ('Created: {0} ({1} MB)' -f $ZipPath, $SizeMb)
Write-Host "Upload this file to GitHub Releases for tag v$Version"
