# Downloads the official Ollama Windows installer, installs it for the current
# user, starts the local server, and pulls the Studyfolio models.
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\install-ollama.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\install-ollama.ps1 -SkipModels

param(
    [switch]$SkipModels,
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"
$InstallerUrl = "https://ollama.com/download/OllamaSetup.exe"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $ProjectRoot ".env"

function Read-EnvValue {
    param([string]$Key, [string]$Default)
    if (-not (Test-Path $EnvFile)) {
        return $Default
    }
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match "^\s*$([regex]::Escape($Key))=(.*)$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return $Default
}

function Refresh-SessionPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$user;$machine"
}

function Find-Ollama {
    Refresh-SessionPath
    $command = Get-Command ollama -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return $null
}

function Test-OllamaApi {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Wait-OllamaApi {
    param([int]$Seconds = 40)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-OllamaApi) {
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Install-Ollama {
    $installer = Join-Path $env:TEMP "OllamaSetup.exe"
    Write-Host "Downloading Ollama from $InstallerUrl"
    & curl.exe -L --fail --retry 3 -o $installer $InstallerUrl
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $installer)) {
        throw "The Ollama download failed."
    }

    $signature = Get-AuthenticodeSignature -FilePath $installer
    $subject = $signature.SignerCertificate.Subject
    if ($signature.Status -ne "Valid" -or $subject -notmatch "Ollama") {
        Remove-Item $installer -Force -ErrorAction SilentlyContinue
        throw "Refusing to run the installer. Signature status: $($signature.Status). Subject: $subject"
    }
    Write-Host "Installer signature is valid ($subject)."

    $markerDir = Join-Path $env:LOCALAPPDATA "Ollama"
    New-Item -ItemType Directory -Path $markerDir -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $markerDir "upgraded") -Force | Out-Null

    $installerArgs = "/VERYSILENT /NORESTART /SUPPRESSMSGBOXES"
    if ($InstallDir) {
        $installerArgs += " /DIR=`"$InstallDir`""
    }
    Write-Host "Installing Ollama for the current user."
    $process = Start-Process -FilePath $installer -ArgumentList $installerArgs -PassThru
    $process.WaitForExit()
    Remove-Item $installer -Force -ErrorAction SilentlyContinue
    if ($process.ExitCode -ne 0) {
        throw "The installer exited with code $($process.ExitCode)."
    }
}

function Start-OllamaServer {
    param([string]$OllamaExe)
    if (Wait-OllamaApi -Seconds 15) {
        Write-Host "Ollama is already serving http://127.0.0.1:11434"
        return
    }
    Write-Host "Starting the Ollama server."
    Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden | Out-Null
    if (-not (Wait-OllamaApi -Seconds 40)) {
        throw "Ollama installed, but http://127.0.0.1:11434 did not respond."
    }
    Write-Host "Ollama is serving http://127.0.0.1:11434"
}

function Pull-Model {
    param([string]$OllamaExe, [string]$Model)
    Write-Host "Pulling $Model. This download is several gigabytes."
    & $OllamaExe pull $Model
    if ($LASTEXITCODE -ne 0) {
        throw "ollama pull $Model failed."
    }
}

if (-not [Environment]::Is64BitOperatingSystem) {
    throw "Ollama for Windows needs a 64-bit operating system."
}

$ollama = Find-Ollama
if ($ollama) {
    Write-Host "Ollama is already installed: $ollama"
}
else {
    Install-Ollama
    $ollama = Find-Ollama
    if (-not $ollama) {
        throw "The installer finished, but ollama.exe was not found."
    }
    Write-Host "Installed: $ollama"
}

Start-OllamaServer -OllamaExe $ollama

if ($SkipModels) {
    Write-Host "Skipped model downloads. Studyfolio needs llama3.1:8b, and photos also need qwen2.5vl:3b."
    return
}

$textModel = Read-EnvValue -Key "OLLAMA_MODEL" -Default "llama3.1:8b"
$visionModel = Read-EnvValue -Key "OLLAMA_VISION_MODEL" -Default "qwen2.5vl:3b"
Pull-Model -OllamaExe $ollama -Model $textModel
Pull-Model -OllamaExe $ollama -Model $visionModel
Write-Host "Ollama is running locally with $textModel and $visionModel."
