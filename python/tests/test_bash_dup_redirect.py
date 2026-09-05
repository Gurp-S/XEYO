"""Bash 重复能力重定向/路由：纯文件读命令 → Read/Glob/Grep；复合命令不拦。

Phase 0 观测（路由 off，默认）：registry 命中即记 tool.routed_observed，仍报 L2 错误。
Phase 1 路由（bash_routing=auto）：区内透明路由（数据+[routed] 提示），区外直行 bash。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController
from tools.bash_tool.dup_redirect import plan_bash_route, redirect_hint


def _hint(cmd: str) -> str | None:
	return redirect_hint(cmd)


def test_cat_to_read() -> None:
	h = _hint("cat src/main.py")
	assert h and "Read" in h and 'file_path="src/main.py"' in h


def test_cat_n_to_read() -> None:
	h = _hint("cat -n README")
	assert h and "Read" in h and 'file_path="README"' in h


def test_type_getcontent_gc_to_read() -> None:
	for cmd in ("type notes.txt", "gc notes.txt", 'Get-Content "my file.txt"'):
		h = _hint(cmd)
		assert h and "Read" in h and "file_path=" in h, cmd


def test_ls_dir_ll_la_find_not_routed() -> None:
	# 实测：Glob 对宽匹配 * 只回目录摘要（文件数）不列文件名，无法满足"列目录"；
	# find 不在 bash 只读白名单（bash=default 下先 ASK）。故 ls/dir/ll/la/find 一律不纳入路由。
	for cmd in (
		"ls", "ls src", "dir", "dir src", "dir /b", "ll", "la",
		"find . -name '*.py'", "find src -iname '*.py'",
	):
		assert _hint(cmd) is None, cmd
		assert plan_bash_route(cmd) is None, cmd


def test_search_to_grep() -> None:
	h = _hint("rg TODO src")
	assert h and "Grep" in h and 'pattern="TODO"' in h and 'path="src"' in h
	assert "Grep" in _hint("grep -rn foo src")
	assert "Grep" in _hint("findstr foo src")
	assert "Grep" in _hint("rg -i 'FIX ME' .")
	assert "case_insensitive=true" in _hint("rg -i foo")


def test_no_redirect_composite_or_unmappable() -> None:
	for cmd in (
		"cat a.txt | wc -l",
		"cat a.txt > out.txt",
		"cat a.txt && git status",
		"ls -la",
		"ls /s",
		"rg -l TODO src",
		"rg -c TODO src",
		"find src -type f -name '*.py'",
		"find src -name '*.py' -print",
		"cat a.txt b.txt",
		"cat src/*.py",
		"type nul",
		"cat --version",
		"echo hi",
		"git status",
		"head -5 x.txt",
		"tail -5 x.txt",
		"wc -l x.txt",
		"npm run build",
		"pip list",
		"python -V",
		"grep -A3 foo src",
		"findstr /c:foo src",
	):
		assert _hint(cmd) is None, cmd


def test_execute_redirects_before_shell() -> None:
	"""L2 已上移 registry（bash_routing=off 默认）。直接 execute 不再重定向，
	改为由 registry 层决策——此处验证 execute 本身不再拦截（命令会真实执行）。"""
	from tools.bash_tool.bash_tool import BashTool

	tool = BashTool(cwd=".")
	result = asyncio.run(
		tool.execute({"command": "echo hi"}, AbortController())
	)
	# 非文件读命令：直接执行，无 [routed] 提示
	assert not result.is_error
	assert "hi" in result.content


# ---- 路由（Phase 1）端到端 ------------------------------------------------


def _enable_routing(tmp_path: Path) -> None:
	from permissions.workspace_policy import clear_policy_cache

	pol = tmp_path / ".xeyo-policy.json"
	pol.write_text('{"bash":"default","bash_routing":"auto"}', encoding="utf-8")
	clear_policy_cache()


def test_plan_tiers_and_inputs() -> None:
	p = plan_bash_route("cat a.py")
	assert p and p.tier == "T1" and p.tool_name == "Read"
	assert p.tool_input == {"file_path": "a.py"}
	assert p.brief == "cat a.py"
	assert "Read" in p.hint

	p = plan_bash_route("rg -i TODO src")
	assert p and p.tier == "T2" and p.tool_name == "Grep"
	assert p.tool_input["output_mode"] == "content"
	assert p.tool_input["case_insensitive"] is True
	assert p.tool_input["pattern"] == "TODO" and p.tool_input["path"] == "src"

	# ls/dir/find 不路由（Glob 列不出文件名 / find 不在白名单先 ASK）
	assert plan_bash_route("ls src") is None
	assert plan_bash_route("find . -name '*.py'") is None

	# ~ 原样保留（Phase 1 由 registry 侧 expanduser+abs），此处只验证解析
	assert plan_bash_route("echo hi") is None
	assert plan_bash_route("cat a | wc") is None


def test_registry_phase0_observes_only(tmp_path: Path) -> None:
	"""Phase 0 契约：行为不变（仍是 L2 错误提示），但命中已记 tool.routed_observed。"""
	import audit.log as audit_mod
	from audit.log import AuditLog, reset_default_audit_log
	from msgtypes.message import ToolUse
	from tools.catalog import build_default_registry

	reset_default_audit_log()
	log = AuditLog(tmp_path / "audit.jsonl")
	audit_mod._default = log
	try:
		reg = build_default_registry(cwd=str(tmp_path))
		result = asyncio.run(
			reg.run(
				ToolUse(id="t1", name="Bash", input={"command": "cat a.py"}),
				AbortController(),
			)
		)
		# 行为不变：模型仍收到 L2 错误提示（未透明路由、未真正执行）
		assert result.is_error and "Read" in result.content
		obs = [r for r in log.read_all() if r["kind"] == "tool.routed_observed"]
		assert len(obs) == 1
		assert obs[0]["tier"] == "T1" and obs[0]["routed_to"] == "Read"
		assert obs[0]["tool_name"] == "Bash" and obs[0]["command"] == "cat a.py"

		# 无对应工具的命令：不观测，照常执行
		result2 = asyncio.run(
			reg.run(
				ToolUse(id="t2", name="Bash", input={"command": "echo hi"}),
				AbortController(),
			)
		)
		assert not result2.is_error
		observed_after = [r for r in log.read_all() if r["kind"] == "tool.routed_observed"]
		assert len(observed_after) == 1
	finally:
		reset_default_audit_log()


def test_routing_auto_routes_cat_to_read(tmp_path: Path) -> None:
	"""bash_routing=auto：区内 cat → 透明路由 Read，返回内容 + [routed] 提示。"""
	import audit.log as audit_mod
	from audit.log import AuditLog, reset_default_audit_log
	from msgtypes.message import ToolUse
	from tools.catalog import build_default_registry

	_enable_routing(tmp_path)
	f = tmp_path / "a.py"
	f.write_text("hello\nworld\n", encoding="utf-8")
	reset_default_audit_log()
	log = AuditLog(tmp_path / "audit.jsonl")
	audit_mod._default = log
	try:
		reg = build_default_registry(cwd=str(tmp_path))
		result = asyncio.run(
			reg.run(
				ToolUse(id="t1", name="Bash", input={"command": "cat a.py"}),
				AbortController(),
			)
		)
		# 透明路由：数据即时到手（0 往返），非 is_error，带 [routed] 标记
		assert not result.is_error
		assert "hello" in result.content and "world" in result.content
		assert "[routed" in result.content and "Read" in result.content
		assert result.metadata.get("routed_from_bash") is True
		assert result.metadata.get("routed_tool") == "Read"
		kinds = [r["kind"] for r in log.read_all()]
		assert "tool.routed" in kinds and "tool.routed_observed" in kinds
	finally:
		reset_default_audit_log()


def test_routing_auto_routes_rg_to_grep(tmp_path: Path) -> None:
	"""bash_routing=auto：区内 rg（T2）→ 透明路由 Grep（output_mode=content）。"""
	from msgtypes.message import ToolUse
	from tools.catalog import build_default_registry

	_enable_routing(tmp_path)
	f = tmp_path / "b.py"
	f.write_text("one\nFIXME two\nthree\n", encoding="utf-8")
	reg = build_default_registry(cwd=str(tmp_path))
	result = asyncio.run(
		reg.run(
			ToolUse(id="t1", name="Bash", input={"command": "rg FIXME b.py"}),
			AbortController(),
		)
	)
	assert not result.is_error
	assert "FIXME" in result.content and "[routed" in result.content and "Grep" in result.content
	assert result.metadata.get("routed_from_bash") is True
	assert result.metadata.get("routed_tool") == "Grep"


def test_routing_auto_outside_workspace_not_routed(tmp_path: Path) -> None:
	"""bash_routing=auto：工作区外路径不路由，直行 bash（无 [routed]、无 tool.routed）。"""
	import audit.log as audit_mod
	from audit.log import AuditLog, reset_default_audit_log
	from msgtypes.message import ToolUse
	from tools.catalog import build_default_registry

	_enable_routing(tmp_path)
	outside = os.path.abspath(os.path.join(os.path.dirname(tmp_path), "zz_outside_route_test.txt"))
	reset_default_audit_log()
	log = AuditLog(tmp_path / "audit.jsonl")
	audit_mod._default = log
	try:
		reg = build_default_registry(cwd=str(tmp_path))
		result = asyncio.run(
			reg.run(
				ToolUse(id="t1", name="Bash", input={"command": f"type {outside}"}),
				AbortController(),
			)
		)
		# 未路由：不出现 [routed] 标记，审计也只有 observed 无 routed
		assert "[routed" not in result.content
		assert not (result.metadata or {}).get("routed_from_bash")
		kinds = [r["kind"] for r in log.read_all()]
		assert "tool.routed" not in kinds
		assert any(r.get("kind") == "tool.routed_observed" for r in log.read_all())
	finally:
		reset_default_audit_log()


def test_routing_off_keeps_l2_error(tmp_path: Path) -> None:
	"""bash_routing 默认 off：仍保留 L2 错误提示（现行为）。"""
	from msgtypes.message import ToolUse
	from tools.catalog import build_default_registry

	# 不写策略文件 → bash_routing=off
	reg = build_default_registry(cwd=str(tmp_path))
	result = asyncio.run(
		reg.run(
			ToolUse(id="t1", name="Bash", input={"command": "cat a.py"}),
			AbortController(),
		)
	)
	assert result.is_error and "Read" in result.content
	assert not (result.metadata or {}).get("routed_from_bash")


# ---- Phase 2 渐进强制（默认 0=关；>0 同形状重复 N 次后放行 bash） ------------


def _write_policy(tmp_path: Path, content: str) -> None:
	from permissions.workspace_policy import clear_policy_cache

	(tmp_path / ".xeyo-policy.json").write_text(content, encoding="utf-8")
	clear_policy_cache()


def test_escalate_default_off_keeps_l2_forever(tmp_path: Path) -> None:
	"""bash_escalate 默认 0（关）：即使同形状重复多次，仍每次 L2 报错。"""
	from msgtypes.message import ToolUse
	from tools.catalog import build_default_registry

	_reg = build_default_registry(cwd=str(tmp_path))
	for _ in range(4):
		r = asyncio.run(
			_reg.run(
				ToolUse(id="t1", name="Bash", input={"command": "cat a.py"}),
				AbortController(),
			)
		)
		assert r.is_error and "Read" in r.content


def test_escalate_concedes_after_n(tmp_path: Path) -> None:
	"""bash_escalate=3（off）：同命令形状第 1/2 次 L2 报错，第 3 次起放行 bash 执行。"""
	from msgtypes.message import ToolUse
	from tools.catalog import build_default_registry

	(tmp_path / "a.py").write_text("hello-phase2\n", encoding="utf-8")
	_write_policy(tmp_path, '{"bash":"default","bash_escalate":3}')
	reg = build_default_registry(cwd=str(tmp_path))
	results = []
	for _ in range(4):
		results.append(
			asyncio.run(
				reg.run(
					ToolUse(id="t1", name="Bash", input={"command": "type a.py"}),
					AbortController(),
				)
			)
		)
	# 前两次 L2（type 是 cmd 内建，T1→Read）
	assert results[0].is_error and "Read" in results[0].content
	assert results[1].is_error and "Read" in results[1].content
	# 第 3 次及以后：放行 bash 执行（返回文件内容，不再报"Use Read"）
	assert "Use Read instead" not in (results[2].content or "")
	assert "hello-phase2" in results[2].content
	assert "Use Read instead" not in (results[3].content or "")
	assert "hello-phase2" in results[3].content


def test_escalate_not_applied_in_auto_route(tmp_path: Path) -> None:
	"""auto 路由给数据、无循环，渐进强制不适用：同形状重复仍每次透明路由。"""
	from msgtypes.message import ToolUse
	from tools.catalog import build_default_registry

	(tmp_path / "a.py").write_text("hello\n", encoding="utf-8")
	_write_policy(tmp_path, '{"bash":"default","bash_routing":"auto","bash_escalate":2}')
	reg = build_default_registry(cwd=str(tmp_path))
	for _ in range(3):
		r = asyncio.run(
			reg.run(
				ToolUse(id="t1", name="Bash", input={"command": "cat a.py"}),
				AbortController(),
			)
		)
		# 每次仍透明路由（Read 第 2/3 次会因"file unchanged"返回缓存 stub，属正常）
		assert not r.is_error
		assert "[routed" in r.content
		assert (r.metadata or {}).get("routed_from_bash") is True


def test_write_bash_policy_merge_and_clamp(tmp_path: Path) -> None:
	"""write_bash_policy：夹取上限、保留其它字段、非法值忽略。"""
	from permissions.workspace_policy import (
		BASH_ESCALATE_MAX,
		clear_policy_cache,
		load_workspace_policy,
		write_bash_policy,
	)

	# 无文件 → 默认；bash_escalate=99 被夹到上限
	pol = write_bash_policy(str(tmp_path), bash_escalate=99)
	assert pol.bash_escalate == BASH_ESCALATE_MAX

	# 含其它字段：更新 escalate 时保留 write
	(tmp_path / ".xeyo-policy.json").write_text(
		'{"bash":"default","write":"ask","bash_escalate":1}', encoding="utf-8"
	)
	clear_policy_cache()
	pol2 = write_bash_policy(str(tmp_path), bash_escalate=2)
	assert pol2.bash_escalate == 2 and pol2.write == "ask"
	assert pol2.source_path is not None

	# 更新 bash_routing 时保留 escalate；非法 routing 忽略
	pol3 = write_bash_policy(str(tmp_path), bash_routing="auto")
	assert pol3.bash_routing == "auto" and pol3.bash_escalate == 2
	pol4 = write_bash_policy(str(tmp_path), bash_routing="bogus")
	assert pol4.bash_routing == "auto"

	# 重载缓存应一致
	clear_policy_cache()
	assert load_workspace_policy(str(tmp_path)).bash_escalate == 2
