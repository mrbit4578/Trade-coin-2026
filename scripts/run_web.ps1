$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & "$PSScriptRoot\install.ps1"
} else {
    & .\.venv\Scripts\python.exe -m pip install -e . -q
}
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
Write-Host "Dashboard: http://127.0.0.1:8080"
& .\.venv\Scripts\python.exe -m crypto_edge.cli web
