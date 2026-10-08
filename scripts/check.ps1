# Unified local gate: Python pytest + GUI typecheck/vitest + tui typecheck.
# Usage: pwsh -File scripts/check.ps1
param([switch]$Json, [switch]$SkipInstall)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if ($Json) {
    $GateArgs = @("-3.11", (Join-Path $PSScriptRoot "check_gate.py"))
    if ($SkipInstall) { $GateArgs += "--skip-install" }
    & py @GateArgs
    exit $LASTEXITCODE
}

Write-Host "`n== Python ==" -ForegroundColor Cyan
Push-Location (Join-Path $Root "python")
try {
    py -3.11 -m pip install -q -r requirements.txt
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    py -3.11 -m pip install -q -e ".[dev]"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    py -3.11 -m pytest -q --timeout=60 -m "not live"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    py -3.11 -m slash.export_manifest --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    # 变更收益侦测器提交门（L0+L1 字节级确定性 + 应试性 R2/R4 扫描）。
    # 零成本、零假红；L2 统计层不挂门（实跑需 --budget + 真 key）。
    py -3.11 -m evals.changedetect check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}

Write-Host "`n== GUI ==" -ForegroundColor Cyan
Push-Location (Join-Path $Root "gui")
try {
    if (-not (Test-Path "node_modules")) {
        npm ci
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    npm test
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}

Write-Host "`n== tui ==" -ForegroundColor Cyan
Push-Location (Join-Path $Root "tui")
try {
    if (-not (Test-Path "node_modules")) {
        npm ci
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}

Write-Host "`nAll checks passed." -ForegroundColor Green
