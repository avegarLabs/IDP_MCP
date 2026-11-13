# Chat with a local Ollama model while exposing paper-analyzer-mcp as tools.
#
# Ollama has no native MCP host, so this launcher uses `ollmcp`
# (https://github.com/jonigl/mcp-client-for-ollama) as the bridge.
# Run it from a normal PowerShell window (the TUI needs a real console).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\run_ollama_mcp.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\run_ollama_mcp.ps1 -Model qwen3-coder:latest

param(
    [string]$Model = "qwen3-coder:latest",
    [string]$PapersDir = "",
    [string]$ExportsDir = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$config = Join-Path $projectRoot "dist\configs\ollmcp-servers.json"

if (-not (Test-Path $config)) {
    throw "Missing $config. Run: uv run python scripts/setup_integrations.py"
}

if ($PapersDir) { $env:PAPERS_DIR = $PapersDir }
if ($ExportsDir) { $env:EXPORTS_DIR = $ExportsDir }

Write-Host "Ollama MCP host: model=$Model" -ForegroundColor Cyan
Write-Host "MCP config    : $config" -ForegroundColor Cyan
Write-Host "Tip: /tools lists tools, /prompts lists MCP prompts, /help shows commands." -ForegroundColor DarkGray

# Prefer an installed ollmcp (fast); fall back to uvx on a fresh machine.
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is not installed. Install it with: winget install --id=astral-sh.uv -e"
}

$toolBin = $null
try { $toolBin = uv tool dir --bin 2>$null } catch { }
$ollmcpExe = if ($toolBin) { Join-Path $toolBin "ollmcp.exe" } else { $null }

if ($ollmcpExe -and (Test-Path $ollmcpExe)) {
    $registered = & $ollmcpExe mcp list 2>$null | Select-String -SimpleMatch "paper-analyzer"
    if ($registered) {
        & $ollmcpExe --model $Model
    }
    else {
        & $ollmcpExe --servers-json $config --model $Model
    }
}
else {
    Write-Host "ollmcp is not installed; using uvx (the first run may take a while)." -ForegroundColor Yellow
    uvx ollmcp --servers-json $config --model $Model
}
