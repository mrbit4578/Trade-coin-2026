# Run Crypto Edge Agent in paper mode (all data on E: drive)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & "$PSScriptRoot\install.ps1"
} else {
    & .\.venv\Scripts\python.exe -m pip install -e . -q
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from example (MODE=paper)"
}

& .\.venv\Scripts\python.exe -m crypto_edge.cli run --cycles 0
