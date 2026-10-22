# Builds dist\Studyfolio\Studyfolio.exe and zips it for a GitHub release.
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\build-release.ps1 -Version 1.0.0

param(
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Creating .venv"
    python -m venv .venv
}

function Invoke-Step {
    param([string]$Label, [scriptblock]$Command)
    Write-Host "== $Label"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed (exit code $LASTEXITCODE)."
    }
}

Invoke-Step "Installing requirements" { & $python -m pip install --disable-pip-version-check -q -r requirements-build.txt }
Invoke-Step "Running unit tests" { & $python -W ignore -m unittest discover -s tests }
Invoke-Step "Building Studyfolio.exe" { & $python -m PyInstaller --noconfirm --clean studyfolio.spec }

$app = Join-Path $Root "dist\Studyfolio"
Copy-Item (Join-Path $Root "docs\START-HERE.txt") (Join-Path $app "START-HERE.txt") -Force

$release = Join-Path $Root "release"
New-Item -ItemType Directory -Path $release -Force | Out-Null
$zip = Join-Path $release "Studyfolio-$Version-windows-x64.zip"
Remove-Item $zip -Force -ErrorAction SilentlyContinue
Write-Host "== Zipping $zip"
Compress-Archive -Path $app -DestinationPath $zip -CompressionLevel Optimal

$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
"$hash  $(Split-Path -Leaf $zip)" | Set-Content -Encoding ascii "$zip.sha256"
$size = "{0:N0} MB" -f ((Get-Item $zip).Length / 1MB)
Write-Host "Done: $zip ($size)"
Write-Host "SHA-256: $hash"
