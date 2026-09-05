"""只读预览：渲染 P1 批次落地后的 T_now 形态（验收工具）。

三个合成场景，打印每条注入块的**顺序**与首行，供人工对照验收：
  场景1 模糊轮「帮我修改」（有上文）→ D1 静默：不应出现任何 Nested/index
  场景2 带路径正常轮 → A1 分仓：头部[Nested pkg] → 用户原文 → 尾部[指令]；
        限窗生效：未触碰的 other 目录规则不出现
  场景3 after_tools 轮 → 合同不变：Continue 首位，无 Memory index

只写 %TEMP% 下临时 workspace，不改仓库、不发网络请求。
用法：cd python && py scripts\\preview_t_now.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _read_round(uid: str, path: str) -> list[dict]:
	return [
		{
			"role": "assistant",
			"content": [
				{
					"type": "tool_use",
					"id": uid,
					"name": "Read",
					"input": {"file_path": path},
				}
			],
		},
		{
			"role": "tool",
			"tool_call_id": uid,
			"content": [
				{
					"type": "tool_result",
					"tool_use_id": uid,
					"content": "x=1",
					"is_error": False,
				}
			],
		},
	]


def _blocks(msg: dict) -> list[str]:
	content = msg.get("content")
	if isinstance(content, str):
		return [content]
	if isinstance(content, list):
		return [
			str(b.get("text") or "")
			for b in content
			if isinstance(b, dict) and b.get("type") == "text"
		]
	return []


def main() -> None:
	import shutil

	from permissions.policy import set_agent_mode

	set_agent_mode("agent")

	# 仓库内临时目录（部分环境的系统 %TEMP% 拒绝建子目录）；结束自清理，
	# 设 T_NOW_PREVIEW_KEEP=1 保留以供检查。
	base = Path(__file__).resolve().parents[1] / ".tmp_t_now_preview"
	if base.exists():
		shutil.rmtree(base, ignore_errors=True)
	tmp = base / "ws"
	tmp.mkdir(parents=True)
	keep = bool(os.environ.get("T_NOW_PREVIEW_KEEP"))
	try:
		_run(tmp)
	finally:
		if not keep:
			shutil.rmtree(base, ignore_errors=True)
		else:
			print(f"（已保留临时目录：{base}）")


def _run(tmp: Path) -> None:
	pkg = tmp / "pkg"
	pkg.mkdir()
	(pkg / "XEYO.md").write_text(
		"pkg 目录规则：回复保持简洁，先给结论。", encoding="utf-8"
	)
	(pkg / "foo.py").write_text("x=1\n", encoding="utf-8")
	other = tmp / "other"
	other.mkdir()
	(other / "XEYO.md").write_text(
		"other 目录规则：本规则不应出现在任何场景。", encoding="utf-8"
	)

	from memory.working import WorkingSnapshot
	from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject

	both_loaded = [
		str(pkg / "XEYO.md"),
		str(other / "XEYO.md"),
	]

	scenarios: list[tuple[str, list[dict], dict]] = []

	# 场景1：模糊轮（有上文）→ D1 静默全部 inventory
	snap1 = WorkingSnapshot(
		session_id="p1", loaded_nested_instruction_paths=list(both_loaded)
	)
	scenarios.append(
		(
			"场景1 模糊轮「帮我修改」（有上文）→ 预期：无 Nested / 无 index，"
			"用户原文完好（D1）",
			run_pre_llm_inject(
				[
					{"role": "user", "content": "看看项目结构"},
					{"role": "assistant", "content": "好的。"},
					{"role": "user", "content": "帮我修改"},
				],
				InjectContext(working=snap1, cwd=str(tmp)),
			),
			snap1,
		)
	)

	# 场景2：带路径正常轮 → A1 分仓 + 限窗（other 不在尾窗 → 静默）
	snap2 = WorkingSnapshot(
		session_id="p2", loaded_nested_instruction_paths=list(both_loaded)
	)
	scenarios.append(
		(
			"场景2 尾窗触碰 pkg → 预期：头部[Nested instructions(pkg)] → "
			"用户原文 → 尾部[指令]；other 规则不出现（批次2 限窗）",
			run_pre_llm_inject(
				[
					{"role": "user", "content": "看看 pkg"},
					*_read_round("r1", str(pkg / "foo.py")),
					{"role": "user", "content": "继续改 pkg/foo.py 的校验逻辑"},
				],
				InjectContext(working=snap2, cwd=str(tmp)),
			),
			snap2,
		)
	)

	# 场景3：after_tools 轮 → Continue 首位；批次3：无 Memory index
	scenarios.append(
		(
			"场景3 after_tools 轮 → 预期：首块 # Continue；无 Memory index（批次3）",
			run_pre_llm_inject(
				[
					{"role": "user", "content": "task"},
					*_read_round("r2", str(pkg / "foo.py")),
				],
				InjectContext(working=snap2, cwd=str(tmp)),
			),
			snap2,
		)
	)

	for title, out, _snap in scenarios:
		print("=" * 72)
		print(title)
		print("=" * 72)
		for i, b in enumerate(_blocks(out[-1])):
			head = b.splitlines()[0] if b else "(空块)"
			print(f"  [{i}] {head[:76]}")
		print()


if __name__ == "__main__":
	main()
