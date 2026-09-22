"""默认档放宽面（2026-09-20）：只读管道 / PowerShell 只读 cmdlet / 本地开发工具类。

背景：用户反馈「bash 权限策略太过了，很多没有危险的命令也需要用户权限」。
旧口径只有「单条 + 无管道 + 命中 Unix 味只读白名单」才自动放行 ⇒ Windows 上模型
自然写的 ``Get-ChildItem``/``Get-Content``/``Select-Object`` 管道、构建测试类命令
全部逐条确认。

本文件同时锁死**不放行面**（网络外发 / 内联任意代码 / 结构不可判）与
**不放宽面**（worker 只读沙箱 / 密钥 / DENY 黑名单 / bash=ask 逃生门）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.workspace_context import WorkspaceContext, set_workspace_context
from permissions.bash_policy import (
	bash_auto_allow_reason,
	bash_readonly_allow,
)
from permissions.bash_readonly import analyze, verdict_kind
from permissions.filesystem import PermissionDecision
from permissions.policy import evaluate_policy, set_permission_mode
from permissions.workspace_policy import (
	POLICY_FILENAME,
	clear_policy_cache,
)
from permissions.write_scope import write_scope


@pytest.fixture(autouse=True)
def _clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
	clear_policy_cache()
	set_workspace_context(None)
	set_permission_mode(None)
	monkeypatch.delenv("XEYO_PERMISSION_MODE", raising=False)
	monkeypatch.delenv("XEYO_BASH_UNSAFE_ALLOW", raising=False)
	yield
	clear_policy_cache()
	set_workspace_context(None)
	set_permission_mode(None)


def _write_policy(tmp_path: Path, **fields: object) -> None:
	(tmp_path / POLICY_FILENAME).write_text(json.dumps(fields), encoding="utf-8")
	clear_policy_cache()


def _bash(cmd: str, cwd: str) -> tuple[str, str]:
	r = evaluate_policy("Bash", {"command": cmd}, cwd=cwd, allowed_paths=[cwd])
	return str(r.decision).split(".")[-1], str(r.matched_rule)


# ---------------------------------------------------------------------------
# 只读类
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
	"cmd",
	[
		"Get-ChildItem -Force",
		"Get-Content -Raw package.json",
		"Select-String -Path *.py -Pattern foo",
		"Get-Process",
		"Get-ChildItem -Recurse -Filter *.md | Select-Object Name",
		"tasklist",
		"tree",
		"du -sh .",
		"rg foo | head -20",
		"git status && git diff --stat",
		"git log --oneline -5 | Select-String fix",
		"kubectl get pods | grep Running",
		"find . -name '*.py' | head -5",
		"Get-ChildItem | Where-Object Name -like *.md | Sort-Object Name",
		"ls -la\necho done",
		"git status . | Out-Null",
	],
)
def test_broad_readonly_allows(cmd: str, tmp_path: Path) -> None:
	got, rule = _bash(cmd, str(tmp_path))
	assert got == "ALLOW", cmd
	assert rule == "bash_readonly_broad", cmd


def test_readonly_verdict_kind() -> None:
	assert verdict_kind("Get-ChildItem") == "readonly"
	assert verdict_kind("rg x | head -3") == "readonly"
	assert verdict_kind("2>&1".join(["Get-ChildItem ", " Select-Object -First 1"])) == "readonly"
	assert verdict_kind("npm run build") == "dev"
	assert verdict_kind("npm run build && npm test") == "dev"
	assert verdict_kind("unknown-tool x") == ""


def test_redirect_to_null_and_fd_dup_are_readonly() -> None:
	# `>$null` / `2>&1` 不写盘，不该被判成结构不可判
	assert verdict_kind("Get-ChildItem 2>&1") == "readonly"
	assert verdict_kind("Get-ChildItem 2>$null | Select-Object Name") == "readonly"


# ---------------------------------------------------------------------------
# dev 类（本地构建 / 测试 / 依赖 / 本地 git 变更）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "npm run build",
        "npm test",
        "npm install left-pad",
        "pnpm install",
        "py -3.11 -m pytest tests/test_x.py",
        "python -m pytest -q",
        "npx tsc --noEmit",
        "npx vitest run",
        "dotnet build",
        "cargo build --release",
        "go test ./...",
        "make -j8",
        "ruff check .",
        "python scripts/run.py --flag",
        "node tools/x.js",
        "git add -A",
        "git commit -m x",
        "git switch -c feature",
        "pip install -r requirements.txt",
        "docker build -t x .",
    ],
)
def test_dev_tools_allow(cmd: str, tmp_path: Path) -> None:
	got, rule = _bash(cmd, str(tmp_path))
	assert got == "ALLOW", cmd
	assert rule == "bash_dev_tool_allow", cmd


# ---------------------------------------------------------------------------
# 不放行面：网络外发 / 内联任意代码 / 结构不可判 / 未知程序
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        # 内联任意代码（命令里看不见可审计的脚本来源）
        'python -c "print(1)"',
        "py -3.11 -c \"print(1)\"",
        "node -e 1",
        "pwsh -Command Get-Process",
        "bash -c ls",
        "cmd /c dir",
        # 网络外发 / 通用取回（与 WebFetch / outbound-ask 同轴）
        "curl https://example.com",
        "curl -s https://x | jq .",
        "wget https://x",
        "gh pr list",
        "git push origin main",
        "git remote add origin x",
        # 包装器：把别的程序当参数执行
        "env FOO=1 Get-ChildItem",
        "xargs echo",
        "start-process notepad",
        # 结构不可判
        "echo hi > out.txt",
        "Get-ChildItem > list.txt",
        "npm run build >> log.txt",
        "Get-Content x; Remove-Item y",
        "echo hi & echo bye",
        "Get-ChildItem | ForEach-Object { $_ }",
        "echo hi `whoami`",
        "echo $(whoami)",
        # 写型开关
        "npm install -g evil",
        "npm publish",
        "pip install --target C:\\tmp x",
        "sort -o out.txt in.txt",
        "find . -name x -delete",
        "docker push x",
        "kubectl apply -f x.yaml",
        "Select-Object -OutFile x.txt",
        "uv publish",
        "poetry publish",
        # npx 未知包 / 未知程序
        "npx evil-pkg --x",
        "pnpm dlx evil",
        "unknown-tool x",
        "mimikatz",
    ],
)
def test_not_allowed_auto(cmd: str, tmp_path: Path) -> None:
	"""放宽面之外：分类器必须拒绝（可能落到写目标证明或 ASK，绝不自动放行）。"""
	assert bash_auto_allow_reason(cmd) is None, cmd


@pytest.mark.parametrize(
    "cmd",
    [
        'python -c "print(1)"',
        "node -e 1",
        "pwsh -Command Get-Process",
        "bash -c ls",
        "curl https://example.com",
        "gh pr list",
        "git push origin main",
        "npm install -g evil",
        "npm publish",
        "sort -o out.txt in.txt",
        "find . -name x -delete",
        "npx evil-pkg --x",
        "unknown-tool x",
        "mimikatz",
    ],
)
def test_still_asks_in_default_mode(cmd: str, tmp_path: Path) -> None:
	got, rule = _bash(cmd, str(tmp_path))
	assert (got, rule) == ("ASK", "bash_default_ask"), cmd


def test_workspace_writes_still_allowed_by_write_proof(tmp_path: Path) -> None:
	"""区内写 = 既有放行口径（`cp`/`mkdir` 同档）：重定向与 PSh 写 cmdlet 不算放宽面，
	但仍走「写目标证明」自动放行；区外写仍拦（见下面 PS 写测试）。"""
	cwd = str(tmp_path)
	for cmd in ("echo hi > out.txt", "npm run build >> log.txt"):
		got, rule = _bash(cmd, cwd)
		assert (got, rule) == ("ALLOW", "bash_write_allow"), cmd
	# 区外写 → DENY
	outside = evaluate_policy(
		"Bash",
		{"command": "echo hi > D:\\__xeyo_outside__\\x.txt"},
		cwd=cwd,
		allowed_paths=[cwd],
	)
	assert outside.decision == PermissionDecision.DENY


def test_composite_with_unknown_segment_never_allows() -> None:
	# 每段都要能看清；任一段不可判 → 整条不放行（fail-closed）
	assert verdict_kind("Get-ChildItem | unknown-tool x") == ""
	assert verdict_kind("npm run build && unknown-tool x") == ""
	d = analyze("npm run build && unknown-tool x")
	assert d.reason == "unknown_program"


# ---------------------------------------------------------------------------
# 不放宽面：worker 沙箱 / 密钥 / 黑名单 / bash=ask 逃生门
# ---------------------------------------------------------------------------


def test_worker_sandbox_not_widened(tmp_path: Path) -> None:
	cwd = str(tmp_path)
	with write_scope(["src"]):
		ro, rule = _bash("git status", cwd)
		pipe, pipe_rule = _bash("rg foo | head -3", cwd)
		dev, dev_rule = _bash("npm run build", cwd)
		ps, ps_rule = _bash("Get-ChildItem", cwd)
	assert (ro, rule) == ("ALLOW", "worker_bash_readonly")
	assert pipe == "DENY" and pipe_rule == "worker_bash_deny"
	assert dev == "DENY" and dev_rule == "worker_bash_deny"
	assert ps == "DENY" and ps_rule == "worker_bash_deny"


def test_strict_path_unchanged_for_pipes_and_git_writes() -> None:
	# 严格档（worker 基线）语义不变：单段 + 规则 allow
	assert bash_readonly_allow("git status")
	assert not bash_readonly_allow("git status && git diff")
	assert not bash_readonly_allow("Get-ChildItem")
	assert not bash_readonly_allow("echo hi | cat")
	# 同名子命令的写形态（旧前缀规则挡不住）
	assert bash_readonly_allow("git remote -v")
	assert bash_readonly_allow("git branch")
	assert not bash_readonly_allow("git remote add origin x")
	assert not bash_readonly_allow("git branch -D foo")
	assert not bash_readonly_allow("git tag -d v1")


def test_secret_and_blacklist_unaffected(tmp_path: Path) -> None:
	cwd = str(tmp_path)
	denied, rule = _bash("Get-Content " + "." + "env", cwd)
	assert denied == "DENY" and rule == "bash_secret_deny"
	rm, rm_rule = _bash("rm -rf /", cwd)
	assert rm == "DENY" and rm_rule == "bash_deny"
	# 即便在只读管道 / dev 命令里提及密钥也不放行
	assert bash_auto_allow_reason("Get-ChildItem " + "." + "env") is None


def test_bash_ask_mode_is_escape_hatch(tmp_path: Path) -> None:
	_write_policy(tmp_path, bash="ask")
	cwd = str(tmp_path)
	for cmd in ("ls -la", "Get-ChildItem", "npm run build"):
		got, rule = _bash(cmd, cwd)
		assert got == "ASK", cmd
		assert rule == "bash_policy_ask", cmd


def test_workspace_rules_still_tighten(tmp_path: Path) -> None:
	_write_policy(tmp_path, bash="default")
	(tmp_path / ".xeyo").mkdir(exist_ok=True)
	(tmp_path / ".xeyo" / "bash_rules.json").write_text(
		json.dumps(
			{
				"rules": [
					{"name": "no-gci", "program": "get-childitem", "prefix": [], "decision": "ask"}
				]
			}
		),
		encoding="utf-8",
	)
	from permissions.bash_policy import clear_bash_rules_cache

	clear_bash_rules_cache()
	cwd = str(tmp_path)
	assert _bash("ls -la", cwd)[0] == "ALLOW"
	assert _bash("Get-ChildItem -Force", cwd) == ("ASK", "bash_rule_ask")
	assert _bash("Get-ChildItem | Select-Object Name", cwd) == ("ASK", "bash_rule_ask")


def test_always_mode_keeps_dev_asking(tmp_path: Path) -> None:
	"""「逐条确认」档：跑代码类（dev）仍逐条点头；只读类照常放行（旧口径一致）。"""
	set_permission_mode("always")
	cwd = str(tmp_path)
	assert _bash("Get-ChildItem | Select-Object Name", cwd)[0] == "ALLOW"
	assert _bash("npm run build", cwd) == ("ASK", "bash_default_ask")


def test_remote_allows_readonly_only(tmp_path: Path) -> None:
	set_workspace_context(WorkspaceContext(session_id="ilink:user1", cwd=str(tmp_path)))
	cwd = str(tmp_path)
	assert _bash("rg foo | head -3", cwd) == ("ALLOW", "bash_remote_readonly_allow")
	assert _bash("npm run build", cwd) == ("ASK", "bash_remote_ask")
	# 远程不吃 grant：remote_bash=deny 仍硬拦
	_write_policy(tmp_path, remote_bash="deny")
	assert _bash("Get-ChildItem", cwd)[1] == "policy_bash_deny"


def test_ps_write_cmdlets_use_workspace_write_proof(tmp_path: Path) -> None:
	"""PowerShell 写 cmdlet 与 `mkdir`/`cp` 同档：区内证明 → ALLOW，区外 → DENY。"""
	cwd = str(tmp_path)
	inside, inside_rule = _bash("New-Item -ItemType Directory foo", cwd)
	assert inside == "ALLOW" and inside_rule == "bash_write_allow"
	outside = evaluate_policy(
		"Bash",
		{"command": "Set-Content -Path C:\\Windows\\Temp\\x.txt -Value hi"},
		cwd=cwd,
		allowed_paths=[cwd],
	)
	assert outside.decision in (PermissionDecision.DENY, PermissionDecision.ASK)
