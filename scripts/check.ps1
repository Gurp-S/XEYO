# Unified local gate: Python pytest + GUI typecheck/vitest + tui typecheck.
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
    # 变更收益侦测器提交门（L0+L1 字节级确定性 + 应试性 R2/R4 扫描）。
    # 零成本、零假红；L2 统计层不挂门（实跑需 --budget + 真 key）。
    py -3.11 -m evals.changedetect check
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

Write-Host "`n== tui ==" -ForegroundColor Cyan
Push-Location (Join-Path $Root "tui")
try {
    if (-not (Test-Path "node_modules")) { npm ci }
    npm run typecheck
} finally {
    Pop-Location
}

Write-Host "`nAll checks passed." -ForegroundColor Green
