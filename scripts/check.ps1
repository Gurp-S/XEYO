# Unified local gate: Python pytest + GUI typecheck/vitest + cli-ts typecheck.
# Usage: pwsh -File scripts/check.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

Write-Host "`n== Python ==" -ForegroundColor Cyan
Push-Location (Join-Path $Root "python")
try {
    py -3.11 -m pip install -q -r requirements.txt
    py -3.11 -m pip install -q -e ".[dev]"
    py -3.11 -m pytest -q --timeout=60 -m "not live"
    py -3.11 -m slash.export_manifest --check
} finally {
    Pop-Location
}

Write-Host "`n== GUI ==" -ForegroundColor Cyan
Push-Location (Join-Path $Root "gui")
try {
    if (-not (Test-Path "node_modules")) { npm ci }
    npm run typecheck
    npm test
} finally {
    Pop-Location
}

Write-Host "`n== cli-ts ==" -ForegroundColor Cyan
Push-Location (Join-Path $Root "cli-ts")
try {
    if (-not (Test-Path "node_modules")) { npm ci }
    npm run typecheck
} finally {
    Pop-Location
}

Write-Host "`nAll checks passed." -ForegroundColor Green
