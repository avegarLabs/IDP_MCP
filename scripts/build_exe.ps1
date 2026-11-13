# Build a self-contained paper-analyzer-mcp executable (Windows).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
#
# Requires: uv (https://docs.astral.sh/uv/)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot

try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv is not installed. Install it with: winget install --id=astral-sh.uv -e"
    }

    Write-Host "==> Syncing Python environment (uv sync)" -ForegroundColor Cyan
    uv sync
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed (exit $LASTEXITCODE)" }

    Write-Host "==> Running test suite" -ForegroundColor Cyan
    uv run pytest -q
    if ($LASTEXITCODE -ne 0) { throw "pytest failed (exit $LASTEXITCODE)" }

    Write-Host "==> Building executable (PyInstaller)" -ForegroundColor Cyan
    uv run pyinstaller --noconfirm --clean paper_analyzer_mcp.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

    Write-Host "==> Verifying binary over MCP stdio" -ForegroundColor Cyan
    uv run python scripts/verify_binary.py
    if ($LASTEXITCODE -ne 0) { throw "Binary verification failed (exit $LASTEXITCODE)" }

    $exe = Join-Path $projectRoot "dist\paper-analyzer-mcp.exe"
    $sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host ""
    Write-Host "Build OK: $exe ($sizeMb MB)" -ForegroundColor Green
    Write-Host "Next: uv run python scripts/setup_integrations.py --apply"
}
finally {
    Pop-Location
}
