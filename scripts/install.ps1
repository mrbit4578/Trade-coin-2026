# Cài package vào venv — sửa lỗi: No module named 'crypto_edge'
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> Project: $Root"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "==> Creating .venv on E: drive..."
    python -m venv .venv
}

$py = ".\.venv\Scripts\python.exe"
& $py -m pip install -U pip
& $py -m pip install -r requirements.txt
& $py -m pip install -e .

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "==> Created .env from .env.example"
}

Write-Host "==> Verify import..."
& $py -m crypto_edge.cli install-check
Write-Host ""
Write-Host "Xong. Chạy thử:"
Write-Host "  .\.venv\Scripts\activate"
Write-Host "  python -m crypto_edge.cli once"
Write-Host "  python -m crypto_edge.cli checklist"
