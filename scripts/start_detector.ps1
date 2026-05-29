# start_detector.ps1 — Lance le détecteur XAUUSD (MT5 requis)
# Usage: .\scripts\start_detector.ps1
# Pour un service Windows, utiliser install_nssm.ps1

$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root ".env"
$DetectorDir = Join-Path $Root "detector"

# Charger les variables d'environnement depuis .env racine
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "^\s*([^#][^=]+)=(.*)$") {
            [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
}

Set-Location $DetectorDir
python main.py
