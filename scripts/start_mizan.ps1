param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$EnvironmentRoot = if ($env:LOCALAPPDATA) {
    Join-Path $env:LOCALAPPDATA "Mizan\venv"
}
else {
    Join-Path $env:TEMP "Mizan\venv"
}
$VenvPython = Join-Path $EnvironmentRoot "Scripts\python.exe"
$Requirements = Join-Path $ProjectRoot "requirements.txt"
$ReadyMarker = Join-Path $EnvironmentRoot ".mizan_ready"

Set-Location -LiteralPath $ProjectRoot

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "[Mizan] Creating the Python environment..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Path (Split-Path $EnvironmentRoot -Parent) -Force | Out-Null
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        & py.exe -3 -m venv $EnvironmentRoot
    }
    elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
        & python.exe -m venv $EnvironmentRoot
    }
    else {
        throw "Python 3 is required. Install it from https://www.python.org/downloads/"
    }
}

$NeedsInstall = -not (Test-Path -LiteralPath $ReadyMarker)
if (-not $NeedsInstall) {
    $NeedsInstall = (Get-Item -LiteralPath $Requirements).LastWriteTimeUtc -gt (Get-Item -LiteralPath $ReadyMarker).LastWriteTimeUtc
}

if ($NeedsInstall) {
    Write-Host "[Mizan] Installing required libraries (first launch only)..." -ForegroundColor Cyan
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r $Requirements
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    New-Item -ItemType File -Path $ReadyMarker -Force | Out-Null
}

$EnvFile = Join-Path $ProjectRoot ".env"
$EnvExample = Join-Path $ProjectRoot ".env.example"
if (-not (Test-Path -LiteralPath $EnvFile) -and (Test-Path -LiteralPath $EnvExample)) {
    Copy-Item -LiteralPath $EnvExample -Destination $EnvFile
    Write-Host "[Mizan] Created .env. Add the client's GROQ_API_KEY for full AI mode." -ForegroundColor Yellow
}

& $VenvPython -c "import streamlit, pandas, groq; print('[Mizan] Environment check passed.')"
if ($LASTEXITCODE -ne 0) { throw "The Python environment check failed." }

if ($CheckOnly) {
    exit 0
}

$OpenBrowser = "Start-Sleep -Seconds 3; Start-Process 'http://localhost:8501'"
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @("-NoProfile", "-WindowStyle", "Hidden", "-Command", $OpenBrowser)

Write-Host "[Mizan] Starting at http://localhost:8501" -ForegroundColor Green
Write-Host "Keep this window open. Press Ctrl+C to stop the application." -ForegroundColor DarkGray
& $VenvPython -m streamlit run (Join-Path $ProjectRoot "streamlit_app.py") --server.headless=true --server.port=8501
