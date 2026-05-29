# install_nssm.ps1 — Installe xauusd-backend et xauusd-detector comme services Windows
# Prérequis : NSSM téléchargé depuis https://nssm.cc/download
# Usage (PowerShell admin) : .\scripts\install_nssm.ps1 -NssmPath "C:\tools\nssm.exe"

param(
    [string]$NssmPath = "C:\tools\nssm\win64\nssm.exe",
    [string]$PythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
)

$Root = (Split-Path -Parent $PSScriptRoot)
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (-not (Test-Path $NssmPath)) {
    Write-Error "NSSM introuvable : $NssmPath`nTélécharge depuis https://nssm.cc/download"
    exit 1
}

if (-not $PythonPath) {
    Write-Error "Python introuvable dans le PATH."
    exit 1
}

# ── Service Backend ────────────────────────────────────────────────────────────
$BackendSvc = "xauusd-backend"
& $NssmPath install $BackendSvc $PythonPath "-m uvicorn main:app --host 0.0.0.0 --port 8000 --no-access-log"
& $NssmPath set $BackendSvc AppDirectory (Join-Path $Root "backend")
& $NssmPath set $BackendSvc AppEnvironmentExtra "DOTENV_PATH=$(Join-Path $Root '.env')"
& $NssmPath set $BackendSvc AppStdout (Join-Path $LogDir "backend.log")
& $NssmPath set $BackendSvc AppStderr (Join-Path $LogDir "backend-error.log")
& $NssmPath set $BackendSvc AppRotateFiles 1
& $NssmPath set $BackendSvc AppRotateBytes 10485760   # 10 MB
& $NssmPath set $BackendSvc Start SERVICE_AUTO_START
& $NssmPath set $BackendSvc ObjectName LocalSystem
Write-Host "Service '$BackendSvc' installé."

# ── Service Détecteur ──────────────────────────────────────────────────────────
$DetectorSvc = "xauusd-detector"
& $NssmPath install $DetectorSvc $PythonPath "main.py"
& $NssmPath set $DetectorSvc AppDirectory (Join-Path $Root "detector")
& $NssmPath set $DetectorSvc AppEnvironmentExtra "DOTENV_PATH=$(Join-Path $Root '.env')"
& $NssmPath set $DetectorSvc AppStdout (Join-Path $LogDir "detector.log")
& $NssmPath set $DetectorSvc AppStderr (Join-Path $LogDir "detector-error.log")
& $NssmPath set $DetectorSvc AppRotateFiles 1
& $NssmPath set $DetectorSvc AppRotateBytes 10485760   # 10 MB
& $NssmPath set $DetectorSvc Start SERVICE_AUTO_START
& $NssmPath set $DetectorSvc ObjectName LocalSystem
Write-Host "Service '$DetectorSvc' installé."

Write-Host ""
Write-Host "Démarrage des services..."
Start-Service $BackendSvc
Start-Service $DetectorSvc
Write-Host "Terminé. Vérifier avec : Get-Service xauusd-*"
