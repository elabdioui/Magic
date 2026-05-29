# start_backend.ps1 — Lance le backend FastAPI (uvicorn)
# Usage: .\scripts\start_backend.ps1
# Pour un service Windows, utiliser install_nssm.ps1

$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root ".env"
$BackendDir = Join-Path $Root "backend"

# Charger les variables d'environnement depuis .env racine
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "^\s*([^#][^=]+)=(.*)$") {
            [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
}

Set-Location $BackendDir
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --no-access-log
