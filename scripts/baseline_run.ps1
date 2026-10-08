#!/usr/bin/env pwsh
<#
.SYNOPSIS
    在 HEAD 提交的临时 worktree 里跑选定测试（判归因用）。

.DESCRIPTION
    回答"这条红是不是**未提交改动**造成的"。做法：从 HEAD 拉一棵干净的临时树，
    在里面跑同一批测试：

      HEAD 绿 + 工作树红  ⇒ 红来自未提交改动（本次改动清单里逐条对）；
      HEAD 也红           ⇒ 红在这条改动之前就存在（别再归因给本次改动）。

    为什么不用 stash / checkout：本仓工作树常年带 200+ 未提交文件，stash 会把别人的
    在制品一起卷走（且失败恢复昂贵）。worktree 只新增一个临时目录 + .git/worktrees
    元数据，**不动当前工作树**，跑完 remove。

    纪律（XEYO.md 禁区）：动手前先把要执行的 git 命令打出来（本脚本第一步就做），
    别把"改工作树"和"判归因"混成一件事。

.PARAMETER PytestArgs
    pytest 参数串（空格分隔），如 "tests/test_x.py -q" 或 "tests/wsc -k fold"。
    缺省 = 全量离线集（-m "not live"）。

.PARAMETER Keep
    跑完保留临时树（排查用）；缺省自动 remove。

.EXAMPLE
    pwsh -File scripts/baseline_run.ps1 -PytestArgs "tests/test_context_limit_inject_g67.py -q"
#>
[CmdletBinding()]
param(
    [string]$PytestArgs = '-m "not live"',
    [string]$PythonExe = "py",
    [string]$PythonFlags = "-3.11",
    [switch]$Keep
)

$ErrorActionPreference = "Stop"

function Say([string]$Message) { Write-Host "[baseline] $Message" }

$root = (& git rev-parse --show-toplevel).Trim()
if (-not $root) { throw "不是 git 仓库（或 git 不可用）" }
$head = (& git -C $root rev-parse --short HEAD).Trim()
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("xeyo-baseline-" + [guid]::NewGuid().ToString("N").Substring(0, 8))

Say "不改当前工作树（未提交改动原样留着）；下列动作只读 HEAD 提交："
Say "  1) git worktree add --detach $tmp $head"
Say "  2) 在 $tmp\python 跑 $PythonExe $PythonFlags -m pytest -q -p no:cacheprovider $PytestArgs"
if ($Keep) { Say "  3) -Keep：跑完保留临时树（自行清理：git worktree remove --force $tmp）" }
else { Say "  3) git worktree remove --force $tmp" }

& git -C $root worktree add --detach $tmp HEAD | Out-Null
if ($LASTEXITCODE -ne 0) { throw "worktree add 失败" }

$code = 1
try {
    Push-Location (Join-Path $tmp "python")
    try {
        $argv = @()
        if ($PythonFlags) { $argv += $PythonFlags.Split(" ") }
        $argv += @("-m", "pytest", "-q", "-p", "no:cacheprovider")
        if ($PytestArgs) { $argv += $PytestArgs.Split(" ") }
        & $PythonExe @argv
        $code = $LASTEXITCODE
    }
    finally { Pop-Location }
}
finally {
    if ($Keep) {
        Say "保留临时树：$tmp"
    }
    else {
        & git -C $root worktree remove --force $tmp | Out-Null
        Say "已移除临时树"
    }
}

if ($code -eq 0) { Say "基线（HEAD $head）绿 ⇒ 这次红来自未提交改动" }
else { Say "基线（HEAD $head）同样红（退出码 $code）⇒ 红早于未提交改动，别归因给本次改动" }
exit $code
