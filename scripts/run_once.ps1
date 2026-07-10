$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & "$PSScriptRoot\install.ps1"
} else {
    # đảm bảo package đã cài (sửa ModuleNotFoundError)
    & .\.venv\Scripts\python.exe -m pip install -e . -q
}
& .\.venv\Scripts\python.exe -m crypto_edge.cli once
