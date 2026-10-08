#!/usr/bin/env pwsh
<#
.SYNOPSIS
    在某个提交的临时 worktree 里跑选定测试（判归因用）。

.DESCRIPTION
    回答"这条红是不是**这一段**改动造成的"：

      ref 绿 + 工作树红 ⇒ 红来自这段改动；
      ref 也红          ⇒ 红早于这段改动，别归因给它。

    为什么不用 stash / checkout：工作树常年带 200+ 未提交文件，stash 会把别人的在制品
    一起卷走。worktree 只新增临时目录 + .git/worktrees 元数据，**不动当前工作树**。

    为什么基线默认不是 HEAD：本仓有活跃的**外部自动提交**（实测：agent 的编辑被逐批
    commit，偶发 merge 别人的分支）。HEAD 随时可能已经包含你正在归因的改动。所以：
      - 默认 `-Ref auto` = 台账（.xeyo/baseline_stamp.json）里记的最早一次 HEAD；
        没有台账就退回 HEAD；
      - 每次运行都把「当前 HEAD / 用的 ref / 用的 sha / reflog 尾三行」打出来；
      - 结果落进台账，供报告引用（"我用的哪个基线"不再靠记忆）。

.EXAMPLE
    pwsh -File scripts/baseline_run.ps1 -PytestArgs "tests/test_context_limit_inject_g67.py -q"
.EXAMPLE
    pwsh -File scripts/baseline_run.ps1 -Ref f7544d8 -PytestArgs "tests/wsc/test_request_timing_loop.py -q"
#>
[CmdletBinding()]
param(
    [string]$PytestArgs = '-m "not live"',
    [string]$PythonExe = "py",
    [string]$PythonFlags = "-3.11",
    [string]$Ref = "auto",
    [switch]$Keep
)

$ErrorActionPreference = "Stop"

function Say([string]$Message) { Write-Host "[baseline] $Message" }

$root = (& git rev-parse --show-toplevel).Trim()
if (-not $root) { throw "不是 git 仓库（或 git 不可用）" }
$headNow = (& git -C $root rev-parse --short HEAD).Trim()
$stampPath = Join-Path $root ".xeyo/baseline_stamp.json"

$stamp = $null
if (Test-Path $stampPath) {
    try { $stamp = Get-Content $stampPath -Raw | ConvertFrom-Json } catch { $stamp = $null }
}

if ($Ref -eq "auto") {
    if ($stamp -and $stamp.first_head) { $Ref = [string]$stamp.first_head }
    else { $Ref = $headNow }
}
$sha = (& git -C $root rev-parse --short $Ref).Trim()
if (-not $sha) { throw "无法解析基线提交：$Ref" }

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("xeyo-baseline-" + [guid]::NewGuid().ToString("N").Substring(0, 8))

Say "Head 现值：$headNow（本次基线 ref：$Ref = $sha）"
Say "reflog 尾三行（HEAD 在你干活期间是否移动，看这里）："
& git -C $root reflog -3 | ForEach-Object { Say "    $_" }
Say "不改当前工作树（未提交改动原样留着）；下列动作只读该提交："
Say "  1) git worktree add --detach $tmp $sha"
Say "  2) 在 $tmp\python 跑 $PythonExe $PythonFlags -m pytest -q -p no:cacheprovider $PytestArgs"
if ($Keep) { Say "  3) -Keep：跑完保留临时树（自行清理：git worktree remove --force $tmp）" }
else { Say "  3) git worktree remove --force $tmp" }

& git -C $root worktree add --detach $tmp $sha | Out-Null
if ($LASTEXITCODE -ne 0) { throw "worktree add 失败" }

$code = 1
$missing = $false
try {
    Push-Location (Join-Path $tmp "python")
    try {
        $argv = @()
        if ($PythonFlags) { $argv += $PythonFlags.Split(" ") }
        $argv += @("-m", "pytest", "-q", "-p", "no:cacheprovider")
        if ($PytestArgs) { $argv += $PytestArgs.Split(" ") }
        $out = & $PythonExe @argv 2>&1
        $out | ForEach-Object { $_ }
        $code = $LASTEXITCODE
        # 基线里根本没有这个文件（新增测试）⇒ 红不是"产品回归"，结论不成立。
        if ($out -match "no tests ran" -or $out -match "file or directory not found") { $missing = $true }
    }
    finally { Pop-Location }
}
finally {
    if ($Keep) { Say "保留临时树：$tmp" }
    else {
        & git -C $root worktree remove --force $tmp | Out-Null
        Say "已移除临时树"
    }
}

# 台账：first_head 只记一次（= 这套工作开始前的那一版），供下次 -Ref auto 使用。
$firstHead = if ($stamp -and $stamp.first_head) { [string]$stamp.first_head } else { $headNow }
$payload = [ordered]@{
    first_head = $firstHead
    head_now   = $headNow
    used_ref   = $Ref
    used_sha   = $sha
    exit_code  = $code
    args       = $PytestArgs
    ts         = (Get-Date).ToString("s")
}
try {
    $dir = Split-Path $stampPath -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    ($payload | ConvertTo-Json) | Set-Content -Path $stampPath -Encoding utf8
    Say "台账已更新：$stampPath（first_head=$firstHead）"
}
catch { Say "台账写入失败（不影响结论）：$_" }

if ($missing) { Say "基线里没有这个测试文件/无用例（新增文件）⇒ 本次不构成归因结论：请用 -Ref 指到包含它的提交" }
elseif ($code -eq 0) { Say "基线（$sha）绿 ⇒ 这次红来自未提交改动" }
else { Say "基线（$sha）同样红（退出码 $code）⇒ 红早于未提交改动，别归因给本次改动" }
if ($missing) { exit 2 }
exit $code
