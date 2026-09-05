"""Bash 专用工具路由 Phase 0/1 自检（无模型，纯 registry 驱动）。

在临时工作区里用真实 ``registry.run`` 跑一遍全部决策路径，打印 PASS/FAIL：

- routing off（默认）：``cat`` 命中 → L2 错误提示 + 审计 tool.routed_observed（无 routed）。
- routing on + 区内：``cat`` → Read 透明路由（数据 + [routed]）；``rg`` → Grep；``dir`` → Glob。
- routing on + 区外：``type <区外路径>`` → **直行 bash**（无 [routed]、无 tool.routed）。
- 复合（``cat a | wc``）→ 原样执行，不路由不提示。

用法：py -3.11 scripts/selfcheck_bash_routing.py
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

from engine.abort import AbortController
from msgtypes.message import ToolUse
from tools.catalog import build_default_registry


_CASE_ID = 0


def _fresh_audit(path: Path) -> Any:
	import audit.log as audit_mod
	from audit.log import AuditLog, reset_default_audit_log

	reset_default_audit_log()
	log = AuditLog(path)
	audit_mod._default = log
	return log


def _enable_routing(ws: Path) -> None:
	from permissions.workspace_policy import clear_policy_cache

	(ws / ".xeyo-policy.json").write_text(
		'{"bash":"default","bash_routing":"auto"}', encoding="utf-8"
	)
	clear_policy_cache()


def _case(
	ws: Path,
	command: str,
	*,
	routing: "off" | "auto",
) -> tuple[Any, list[dict[str, Any]]]:
	if routing == "auto":
		_enable_routing(ws)
	else:
		from permissions.workspace_policy import clear_policy_cache

		clear_policy_cache()
	global _CASE_ID
	_CASE_ID += 1
	log = _fresh_audit(ws / "_audits" / f"case{_CASE_ID}.jsonl")
	reg = build_default_registry(cwd=str(ws))
	result = asyncio.run(
		reg.run(
			ToolUse(id="c", name="Bash", input={"command": command}),
			AbortController(),
		)
	)
	events = log.read_all()
	return result, events


def _check(name: str, result: Any, events: list[dict[str, Any]], **want: Any) -> None:
	problems: list[str] = []
	content = result.content or ""
	meta = result.metadata or {}
	for key, val in want.items():
		if key == "is_error":
			if bool(result.is_error) != bool(val):
				problems.append(f"is_error={result.is_error} != {val}")
		elif key == "content_has":
			for token in val:
				if token not in content:
					problems.append(f"content 缺少 {token!r}")
		elif key == "content_not_has":
			for token in val:
				if token in content:
					problems.append(f"content 不应含 {token!r}")
		elif key == "has_events":
			if isinstance(val, str):
				val = [val]
			for v in val:
				if v not in {e.get("kind") for e in events}:
					problems.append(f"审计缺事件 {v!r}")
		elif key == "no_events":
			if isinstance(val, str):
				val = [val]
			for v in val:
				if v in {e.get("kind") for e in events}:
					problems.append(f"审计不应有事件 {v!r}")
		elif key == "routed_from_bash":
			if bool(meta.get("routed_from_bash")) != bool(val):
				problems.append(f"routed_from_bash={meta.get('routed_from_bash')} != {val}")
		elif key == "routed_tool":
			if meta.get("routed_tool") != val:
				problems.append(f"routed_tool={meta.get('routed_tool')!r} != {val!r}")
	status = "PASS" if not problems else "FAIL " + "; ".join(problems)
	print(f"[{status}] {name}")


def main() -> int:
	with tempfile.TemporaryDirectory(prefix="xeyo-bash-route-") as td:
		ws = Path(td)
		# 工作区内容
		(ws / "a.py").write_text("hello\nworld\n", encoding="utf-8")
		(ws / "b.py").write_text("one\nFIXME two\nthree\n", encoding="utf-8")
		sub = ws / "sub"
		sub.mkdir()
		(sub / "d.txt").write_text("x", encoding="utf-8")

		# 1) routing off（默认）：L2 错误提示 + 仅 observed
		r, ev = _case(ws, "cat a.py", routing="off")
		_check(
			"off → cat 命中即 L2 错误提示（未路由）",
			r, ev,
			is_error=True, content_has=["Read"], content_not_has=["[routed"],
			has_events="tool.routed_observed", no_events="tool.routed",
		)

		# 2) on + 区内 cat → Read 透明路由
		r, ev = _case(ws, "cat a.py", routing="auto")
		_check(
			"auto 区内 → cat 路由 Read（数据 + [routed]）",
			r, ev,
			is_error=False, content_has=["hello", "world", "[routed", "Read"],
			routed_from_bash=True, routed_tool="Read",
			has_events=["tool.routed", "tool.routed_observed"],
		)

		# 3) on + 区内 rg → Grep（T2）
		r, ev = _case(ws, "rg FIXME b.py", routing="auto")
		_check(
			"auto 区内 → rg 路由 Grep（T2）",
			r, ev,
			is_error=False, content_has=["FIXME", "[routed", "Grep"],
			routed_tool="Grep",
		)

		# 4) on + 区内 find：不在 bash 只读白名单 → bash=default 先 ASK（需批准），不自动路由
		r, ev = _case(ws, "find . -name '*.py'", routing="auto")
		_check(
			"auto 区内 → find（不在白名单）先 ASK，不自动路由",
			r, ev,
			is_error=True, content_not_has=["[routed"], routed_from_bash=False, no_events="tool.routed",
		)

		# 4b) on + 区内 dir → 不路由（Glob 列不出文件名），直行 bash 真实列目录
		r, ev = _case(ws, "dir sub", routing="auto")
		_check(
			"auto 区内 → dir 不路由（bash 直行列目录）",
			r, ev,
			content_not_has=["[routed"], routed_from_bash=False, no_events="tool.routed",
		)

		# 5) on + 区外 → 直行 bash（无 [routed]、无 tool.routed）
		outside = os.path.abspath(os.path.join(Path(td).parent, "zz_xeyo_outside.txt"))
		r, ev = _case(ws, f"type {outside}", routing="auto")
		_check(
			"auto 区外 → 不路由直行 bash",
			r, ev,
			content_not_has=["[routed"], routed_from_bash=False,
			no_events="tool.routed", has_events="tool.routed_observed",
		)

		# 6) 复合命令 → 不路由（宁放勿拦）
		r, ev = _case(ws, "cat a.py | wc -l", routing="auto")
		_check(
			"复合（管道）→ 不路由不提示",
			r, ev,
			content_not_has=["[routed"], routed_from_bash=False, no_events="tool.routed",
		)

	print("\n完成")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
