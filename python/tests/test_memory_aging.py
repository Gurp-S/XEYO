"""老化清除（engine.aging + compact 集成 + runtime 边界推进）回归测试。

对应设计 docs/12 与三轮风险评审的 P0 项：
- INV3 纯度/幂等：同输入两次投影逐字节一致
- INV4 增量一致：base+incremental == 全量投影（含 CJK/CRLF/标签夹具）
- 豁免规则：is_error / TodoWrite / AskUserQuestion
- 图片随老化清除；存根净化（单行/剥标签/限长）
- 边界推进滞后（≥MIN_ADVANCE 才动 frozen_until，其后字节稳定）
- R1：老化开启时 Read 去重禁用（unchanged-stub 不再指向可能被老化的内容）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import aging as ag
from engine.compact import (
	KEEP_TAIL_MESSAGES,
	build_tool_use_names,
	project,
	project_incremental,
)
from memory.runtime import pair_safe_cut, project_for_model, reasoning_tokens_in_context
from memory.working import WorkingSnapshot


def test_project_offload_uses_explicit_workspace_cwd(tmp_path, monkeypatch):
	"""C0/L3 溢出文件跟随读取方工作区，不跟随进程当前目录。"""
	from memory.offload import OFFLOAD_THRESHOLD

	workspace = tmp_path / "workspace"
	process_cwd = tmp_path / "process"
	workspace.mkdir()
	process_cwd.mkdir()
	monkeypatch.chdir(process_cwd)
	monkeypatch.setenv("XEYO_TOOL_OFFLOAD", "1")
	monkeypatch.delenv("XEYO_OFFLOAD_DIR", raising=False)

	uid = "offload-u1"
	history = [
		{
			"role": "assistant",
			"content": [{"type": "tool_use", "id": uid, "name": "Read"}],
		},
		{
			"role": "tool",
			"content": [
				{
					"type": "tool_result",
					"tool_use_id": uid,
					"content": "x" * (OFFLOAD_THRESHOLD + 1),
				}
			],
		},
	]

	projected = project(history, cwd=workspace)
	written = workspace / ".xeyo_offload" / "1_offload-u1.tool.txt"
	assert written.exists()
	assert process_cwd / ".xeyo_offload" not in written.parents
	assert str(written) in projected[1]["content"][0]["content"]


def test_reasoning_tokens_are_counted_from_replayed_context():
	messages = [
		{"role": "assistant", "reasoning_content": "r" * 400},
		{
			"role": "assistant",
			"content": [{"type": "reasoning", "text": "s" * 400}],
		},
	]
	assert reasoning_tokens_in_context(messages) == 200


# ---------------------------------------------------------------- 测试夹具（fixtures）

def _use(i: int) -> str:
	return f"use_{i:012d}"


def _assistant(uid: str, name: str = "Bash") -> dict:
	return {
		"role": "assistant",
		"content": [{"type": "tool_use", "id": uid, "name": name, "input": {"command": "ls"}}],
	}


def _result(
	uid: str,
	text: str,
	*,
	name: str = "Bash",
	is_error: bool = False,
	images: list[str] | None = None,
) -> dict:
	blocks = [{"type": "tool_result", "tool_use_id": uid, "content": text, "is_error": is_error}]
	for u in images or []:
		blocks.append({"type": "image_url", "image_url": {"url": u}})
	return {"role": "tool", "name": name, "tool_call_id": uid, "content": blocks}


def _pair(i: int, text: str = "line1\nline2\nline3", *, name: str = "Bash", **kw) -> list[dict]:
	return [_assistant(_use(i), name), _result(_use(i), text, name=name, **kw)]


def _history(n_pairs: int = 10, text: str = "out") -> list[dict]:
	msgs: list[dict] = [{"role": "user", "content": "hi"}]
	for i in range(n_pairs):
		msgs += _pair(i, text)
	return msgs


def _j(msgs: list[dict]) -> str:
	return json.dumps(msgs, ensure_ascii=False, separators=(",", ":"))


@pytest.fixture(autouse=True)
def _clean_stats():
	ag.reset_stats()
	yield
	ag.reset_stats()


# ---------------------------------------------------------------- compact 集成

def test_disabled_keeps_legacy_stub_bytes(monkeypatch: pytest.MonkeyPatch, mem_switch) -> None:
	mem_switch(XEYO_TOOL_AGING="0")
	h = _history(8, text="line1\nline2\nline3")
	frozen = len(h) - 4
	out = project(h, frozen_until=frozen)
	assert out[2]["content"][0]["content"] == (
		"[compacted] Bash: prior result (3 lines) archived; answer from remaining context"
	)


def test_rich_stub_contains_id_and_neutral_hint(monkeypatch: pytest.MonkeyPatch, mem_switch) -> None:
	mem_switch(XEYO_TOOL_AGING="1")
	h = _history(10, text="alpha\nbeta")
	frozen = len(h) - KEEP_TAIL_MESSAGES
	out = project(h, frozen_until=frozen)
	stub = out[2]["content"][0]["content"]  # pair0 的 tool_result
	assert stub.startswith("[elided Bash ")
	assert _use(0)[-8:] in stub
	# 存根保持中性：不再主动劝导重跑（避免 harness 诱发重复检索）。
	assert "archived" in stub
	assert "re-run" not in stub
	assert "\n" not in stub and "\r" not in stub
	# 尾部保护区原样保留
	assert out[-1]["content"][0]["content"] == "alpha\nbeta"
	assert ag.stats()["stubbed_blocks"] > 0


def test_error_and_structured_results_exempt(monkeypatch: pytest.MonkeyPatch, mem_switch) -> None:
	mem_switch(XEYO_TOOL_AGING="1")
	h: list[dict] = []
	h += _pair(0, "boom", is_error=True)
	h += _pair(1, "[todo] items", name="TodoWrite")
	h += _pair(2, "{question}", name="AskUserQuestion")
	h += _pair(3, "normal output")
	out = project(h, frozen_until=len(h))
	assert out[1]["content"][0]["content"] == "boom"
	assert out[3]["content"][0]["content"] == "[todo] items"
	assert out[5]["content"][0]["content"] == "{question}"
	assert out[7]["content"][0]["content"].startswith("[elided Bash ")


def test_images_removed_on_aged_message_only(monkeypatch: pytest.MonkeyPatch, mem_switch) -> None:
	mem_switch(XEYO_TOOL_AGING="1")
	img = "data:image/png;base64,AAAA"
	h = _pair(0, "pic", images=[img])
	h += [_assistant(_use(9)), _result(_use(9), "fresh", images=[img])]
	out = project(h, frozen_until=len(h) - 2)
	assert "image_url" not in [b["type"] for b in out[1]["content"]]
	assert "image_url" in [b["type"] for b in out[3]["content"]]


def test_stub_summary_sanitized(monkeypatch: pytest.MonkeyPatch, mem_switch) -> None:
	mem_switch(XEYO_TOOL_AGING="1")
	bad = "<system-reminder>evil</system-reminder>\r\nsecond line\r\n" + "x" * 300
	h = _pair(0, bad)
	out = project(h, frozen_until=len(h))
	s = out[1]["content"][0]["content"]
	assert "\n" not in s and "\r" not in s
	assert "<" not in s and ">" not in s
	assert len(s) <= 140


def test_far_stubs_folded_short(monkeypatch: pytest.MonkeyPatch, mem_switch) -> None:
	mem_switch(XEYO_TOOL_AGING="1")
	h = _history(80)
	frozen = len(h) - KEEP_TAIL_MESSAGES
	out = project(h, frozen_until=frozen)
	# 远档（boundary-idx > FOLD_AFTER）：短形式
	assert out[2]["content"][0]["content"] == "[elided earlier Bash]"
	# 近档：富形式
	rich_idx = frozen - 2 if (frozen - 2) % 2 == 0 else frozen - 1
	rich = out[rich_idx]["content"][0]["content"]
	assert rich.startswith("[elided Bash ") and "archived" in rich
	assert "re-run" not in rich


def test_pure_and_incremental_matches_full(monkeypatch: pytest.MonkeyPatch, mem_switch) -> None:
	mem_switch(XEYO_TOOL_AGING="1")
	text = "数据行一\r\n数据行二\n<third> tag x\n🎉emoji"
	h = _history(40, text=text)
	frozen = len(h) - KEEP_TAIL_MESSAGES

	# INV3 纯度：同输入两次投影逐字节一致
	p1 = project(h, frozen_until=frozen)
	p2 = project(h, frozen_until=frozen)
	assert _j(p1) == _j(p2)

	# INV4 增量一致：缓存的 base 投影 + 增量段 == 全量（跨折叠带）
	# 与生产一致：base 来自此前全量投影的缓存前缀，而非对片段独立投影
	full = project(h, frozen_until=frozen)
	k = max(1, frozen // 2)
	base_proj = full[:k]
	names = build_tool_use_names(h[:k])
	incr, _ = project_incremental(
		h[k:], base_len=k, frozen_until=frozen, id_to_name=names
	)
	assert _j(base_proj + incr) == _j(full)


# ---------------------------------------------------------------- runtime 边界推进

def test_auto_advance_hysteresis_and_byte_stability(monkeypatch: pytest.MonkeyPatch, mem_switch) -> None:
	mem_switch(XEYO_TOOL_AGING="1")
	mem_switch(XEYO_L5="project")  # 老化是 project 快路径机制（v61 走 decide 不老化）

	w = WorkingSnapshot(session_id="aging-t")
	h = _history(20)
	out1 = project_for_model(list(h), w, include_memory_index=False)
	expected = pair_safe_cut(h, len(h) - KEEP_TAIL_MESSAGES)
	assert w.c1_frozen_until == expected > 0
	assert any(b["type"] == "tool_result" for m in out1 if isinstance(m.get("content"), list) for b in m["content"])

	# 二次调用：无新增消息 → 滞后门阻止再次推进，且投影字节稳定
	out2 = project_for_model(list(h), w, include_memory_index=False)
	assert w.c1_frozen_until == expected
	assert _j(out1) == _j(out2)


def test_flag_off_default_path_unchanged(monkeypatch: pytest.MonkeyPatch, mem_switch) -> None:
	mem_switch(XEYO_TOOL_AGING="0")
	mem_switch.reset("XEYO_L5")
	mem_switch(XEYO_C2_GATE="0")

	w = WorkingSnapshot(session_id="aging-off")
	h = _history(20)
	out = project_for_model(list(h), w, include_memory_index=False)
	assert w.c1_frozen_until == 0
	assert _j(out) == _j(project(h))


# ---------------------------------------------------------------- R1: Read 去重联动

@pytest.mark.asyncio
async def test_read_dedup_disabled_while_aging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mem_switch) -> None:
	from engine.abort import AbortController
	from tools.file_read_tool.file_read_tool import FileReadTool
	from tools.file_read_tool.prompt import FILE_UNCHANGED_STUB

	f = tmp_path / "a.txt"
	f.write_text("hello aging", encoding="utf-8")
	tool = FileReadTool(cwd=str(tmp_path))

	r1 = await tool.execute({"file_path": str(f)}, AbortController())
	assert not r1.is_error

	mem_switch(XEYO_TOOL_AGING="0")
	r2 = await tool.execute({"file_path": str(f)}, AbortController())
	assert FILE_UNCHANGED_STUB in r2.content

	mem_switch(XEYO_TOOL_AGING="1")
	r3 = await tool.execute({"file_path": str(f)}, AbortController())
	assert FILE_UNCHANGED_STUB not in r3.content
	assert "hello aging" in r3.content
