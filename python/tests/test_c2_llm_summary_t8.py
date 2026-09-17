"""T8：C2 LLM 摘要（前缀重放）+ compact checkpoint 落盘。

覆盖：
- c2_llm_bypass：重放前缀、只收纯文本、拒绝 tool_use、拒绝不缩小、异常/无 client 回退。
- apply_c2_messages / force_compact：注入 provider 采用其摘要，否则回退确定性。
- 默认旁路关：行为与 compact.project 字节一致（不回归）。
- compact checkpoint：set → flush → hydrate → projection 一致；anchor 回填。
"""

from __future__ import annotations


import pytest

from engine.abort import AbortController
from engine.compact import project
from memory.runtime import (
	c2_llm_bypass,
	c2_llm_summary_enabled,
	project_for_model,
	apply_c2_messages,
	force_compact,
)
from memory.working import (
	CompactCheckpoint,
	WorkingSnapshot,
	flush,
	hydrate,
	note_compact_checkpoint,
)
from model.chunks import ModelChunk
from msgtypes.message import ToolUse


# ---------- 工具 ----------

def _msg_user(text: str) -> dict:
	return {"role": "user", "content": text}


def _asst_use(uid: str, name: str) -> dict:
	return {
		"role": "assistant",
		"content": [{"type": "tool_use", "id": uid, "name": name, "input": {"q": "x"}}],
	}


def _tool(uid: str, content: str) -> dict:
	return {
		"role": "tool",
		"tool_call_id": uid,
		"name": "Grep",
		"content": [{"type": "tool_result", "tool_use_id": uid, "content": content, "is_error": False}],
	}


class _FakeC2Client:
	"""可配置的假 C2 旁路客户端：按预置 chunks 流式吐出。"""

	def __init__(self, chunks: list[ModelChunk]) -> None:
		self.chunks = list(chunks)
		self.calls: list[tuple[list[dict], list[dict]]] = []
		self.provider = "fake"
		self._model = "fake-model"

	async def stream(self, messages, tools, abort: AbortController):
		self.calls.append((messages, tools))
		abort.raise_if_aborted()
		for ch in self.chunks:
			yield ch


def _client_text(text: str) -> _FakeC2Client:
	return _FakeC2Client([ModelChunk(kind="text_delta", text=text)])


def _client_tool_use() -> _FakeC2Client:
	return _FakeC2Client(
		[
			ModelChunk(kind="text_delta", text="head"),
			ModelChunk(
				kind="tool_use",
				tool_use=ToolUse(id="call_1", name="echo", input={"text": "x"}),
			),
		]
	)


def _long_left(n: int = 6, size: int = 4000) -> list[dict]:
	msgs: list[dict] = [{"role": "user", "content": "start"}]
	for i in range(n):
		uid = f"g{i}"
		msgs.append(_asst_use(uid, "Grep"))
		msgs.append(_tool(uid, "x" * size))
	return msgs


# ---------- 开关 ----------

def test_c2_llm_summary_env_gate_default_off(monkeypatch, mem_switch):
	# 契约（2026-09-06）：开关走 memory_switches（get_value 权威，GUI 面板可切），
	# env 不再参与——测试用 mem_switch（settings）覆盖，与 test_memory_switch_authority 一致。
	monkeypatch.delenv("XEYO_C2_LLM_SUMMARY", raising=False)
	mem_switch.reset("XEYO_C2_LLM_SUMMARY")
	assert not c2_llm_summary_enabled()  # 默认关
	mem_switch(XEYO_C2_LLM_SUMMARY="1")
	assert c2_llm_summary_enabled()
	mem_switch(XEYO_C2_LLM_SUMMARY="0")
	assert not c2_llm_summary_enabled()


def test_default_project_path_unchanged_with_bypass_off(monkeypatch, mem_switch):
	"""旁路默认关：project 投影字节 == compact.project（硬不变量）。"""
	monkeypatch.delenv("XEYO_C2_LLM_SUMMARY", raising=False)
	mem_switch.reset("XEYO_L5")
	mem_switch(XEYO_C2_GATE="0")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	w = WorkingSnapshot()
	msgs = _long_left(4, 200)
	assert project_for_model(msgs, w, include_memory_index=False) == project(msgs)
	assert w.compact_cursor == 0


# ---------- c2_llm_bypass（LLM 路径） ----------

@pytest.mark.asyncio
async def test_c2_llm_bypass_collects_only_text(monkeypatch, mem_switch):
	monkeypatch.delenv("XEYO_C2_LLM_SUMMARY", raising=False)
	client = _client_text("SUMMARY-THAT-SHRINKS")
	msgs = [{"role": "user", "content": "A" * 50}]
	out = await c2_llm_bypass(
		system_prompt="SYS",
		messages=msgs,
		model=client,
		abort=AbortController(),
		region_text=4000,
	)
	assert out == "SUMMARY-THAT-SHRINKS"
	# 重放前缀 = system + 投影消息 + 末尾追加摘要请求参数
	replay, tools = client.calls[0]
	assert replay[0] == {"role": "system", "content": "SYS"}
	assert tools == []
	# 原用户文本作为前缀块保留，末尾追加摘要请求参数
	last = replay[-1]
	joined = "\n".join(str(b.get("text") or "") for b in last["content"]) if isinstance(last["content"], list) else str(last["content"])
	assert "A" * 50 in joined
	assert "C2 摘要请求参数" in joined


@pytest.mark.asyncio
async def test_c2_llm_bypass_rejects_tool_use():
	client = _client_tool_use()
	out = await c2_llm_bypass(
		system_prompt="SYS",
		messages=[{"role": "user", "content": "q"}],
		model=client,
		abort=AbortController(),
		region_text=1000,
	)
	assert out is None


@pytest.mark.asyncio
async def test_c2_llm_bypass_rejects_non_shrink_summary():
	client = _client_text("X" * 500)  # 摘要大于 region_text=50
	out = await c2_llm_bypass(
		system_prompt="SYS",
		messages=[{"role": "user", "content": "A" * 50}],
		model=client,
		abort=AbortController(),
		region_text=50,
	)
	assert out is None


@pytest.mark.asyncio
async def test_c2_llm_bypass_none_on_no_client_or_abort():
	out = await c2_llm_bypass(
		system_prompt="SYS",
		messages=[{"role": "user", "content": "q"}],
		model=None,
		abort=AbortController(),
		region_text=1000,
	)
	assert out is None
	out2 = await c2_llm_bypass(
		system_prompt="SYS",
		messages=[{"role": "user", "content": "q"}],
		model=_client_text("ok"),
		abort=None,
		region_text=1000,
	)
	assert out2 is None


@pytest.mark.asyncio
async def test_c2_llm_bypass_returns_none_on_exception():
	class _Boom:
		async def stream(self, messages, tools, abort):
			raise RuntimeError("boom")
			yield  # unreachable but makes this an async generator

	out = await c2_llm_bypass(
		system_prompt="SYS",
		messages=[{"role": "user", "content": "q"}],
		model=_Boom(),
		abort=AbortController(),
		region_text=1000,
	)
	assert out is None


# ---------- apply_c2_messages / force_compact：provider 回退 ----------

def test_apply_c2_provider_summary_used(monkeypatch, mem_switch):
	mem_switch(XEYO_C2_LLM_SUMMARY="1")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	w = WorkingSnapshot(compact_cursor=3, c1_frozen_until=3)
	msgs = _long_left(4)
	captured = {}
	provider = lambda left, region_chars: captured.update(left=left, rc=region_chars) or "LLM-SUMMARY"
	out = apply_c2_messages(msgs, w, summary_provider=provider)
	assert w.c2_summary_text == "LLM-SUMMARY"
	assert out[0]["role"] == "assistant"
	assert out[0]["name"] == "session_summary"
	assert out[0]["content"] == "LLM-SUMMARY"
	assert "LLM-SUMMARY" not in str(msgs)  # JSONL 不写摘要（投影只在 working）
	assert w.compact_checkpoint is not None
	assert w.compact_checkpoint.anchor_summary == "LLM-SUMMARY"


def test_apply_c2_provider_none_falls_back_to_deterministic(monkeypatch, mem_switch):
	mem_switch(XEYO_C2_LLM_SUMMARY="1")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	w = WorkingSnapshot(compact_cursor=3, c1_frozen_until=3)
	msgs = _long_left(4)
	out = apply_c2_messages(msgs, w, summary_provider=lambda left, rc: None)
	assert w.c2_summary_text.startswith("[C2] compacted")
	assert out[0]["content"] == w.c2_summary_text


def test_apply_c2_provider_non_shrink_rejected(monkeypatch, mem_switch):
	mem_switch(XEYO_C2_LLM_SUMMARY="1")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	w = WorkingSnapshot(compact_cursor=3, c1_frozen_until=3)
	msgs = _long_left(4)
	big = "Z" * 1_000_000  # 一定小于 region_chars 吗？region 约 6*4000=24000 → 1M 不缩小
	out = apply_c2_messages(msgs, w, summary_provider=lambda left, rc: big)
	assert w.c2_summary_text.startswith("[C2] compacted")
	assert "Z" not in w.c2_summary_text


def test_apply_c2_provider_exception_falls_back(monkeypatch, mem_switch):
	mem_switch(XEYO_C2_LLM_SUMMARY="1")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	w = WorkingSnapshot(compact_cursor=3, c1_frozen_until=3)
	msgs = _long_left(4)

	def _boom(left, rc):
		raise RuntimeError("boom")

	out = apply_c2_messages(msgs, w, summary_provider=_boom)
	assert w.c2_summary_text.startswith("[C2] compacted")
	assert out[0]["content"] == w.c2_summary_text


def test_force_compact_uses_provider_or_falls_back(monkeypatch, mem_switch):
	mem_switch(XEYO_C2_LLM_SUMMARY="1")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	msgs = _long_left(10)
	w = WorkingSnapshot()
	out = force_compact(msgs, w, summary_provider=lambda left, rc: "FORCED-SUMMARY")
	assert w.compact_cursor > 0
	assert w.c2_summary_text == "FORCED-SUMMARY"
	assert out[0]["content"] == "FORCED-SUMMARY"
	# provider 抛异常 → 回退确定性且不崩溃、投影正确
	w2 = WorkingSnapshot()
	out2 = force_compact(msgs, w2, summary_provider=lambda left, rc: (_ for _ in ()).throw(RuntimeError("x")))
	assert w2.compact_cursor > 0
	assert w2.c2_summary_text.startswith("[C2] compacted")
	assert out2[0]["content"] == w2.c2_summary_text


def test_project_for_model_c2_uses_provider_when_gate_on(monkeypatch, mem_switch):
	"""v61 开 + 旁路开 + 注入 provider → C2 投影用 provider 摘要。"""
	from types import SimpleNamespace as _SN

	mem_switch(XEYO_L5="v61", XEYO_C2_LLM_SUMMARY="1")
	# 2026-09-06 固化：C2_GATE / Path A 三公式已删——v61 下 decide 自主（公式不参与），
	# 本测试直接验证「decide 返回 C2 → 用 provider 摘要」机制。
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	fake = _SN(a_star="C2", hardtop=True)
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake)
	w = WorkingSnapshot()
	msgs = _long_left(8)
	out = project_for_model(msgs, w, include_memory_index=False, summary_provider=lambda left, rc: "GATE-SUMMARY")
	assert w.compact_cursor > 0
	assert w.c2_summary_text == "GATE-SUMMARY"
	assert out[0]["content"] == "GATE-SUMMARY"


# ---------- compact checkpoint 落盘 / resume ----------

def test_checkpoint_round_trip_projection_identical(tmp_path, monkeypatch, mem_switch):
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	mem_switch(XEYO_C2_LLM_SUMMARY="0")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	msgs = _long_left(8)  # 17 条
	# apply_c2_messages 只换左段摘要、不动 cursor；先给一个已压缩的 cursor 锚点
	w = WorkingSnapshot(session_id="cp1", compact_cursor=11, c1_frozen_until=11)
	proj1 = apply_c2_messages(msgs, w)
	assert w.compact_cursor > 0 and w.c2_summary_text
	assert w.compact_checkpoint is not None
	frozen = w.c2_summary_text
	flush("cp1", w)

	got = hydrate("cp1")
	# 摘要文本冻结、cursor/frozen 对齐锚点
	assert got.compact_cursor == w.compact_cursor
	assert got.c1_frozen_until == w.c1_frozen_until
	assert got.c2_summary_text == frozen
	assert got.compact_checkpoint is not None
	assert got.compact_checkpoint.anchor_summary == frozen
	assert got.compact_checkpoint.window_chain

	# resume 重建投影：字节级一致
	proj2 = apply_c2_messages(msgs, got)
	assert proj1 == proj2
	assert proj2[0]["content"] == frozen


def test_checkpoint_resume_rebuilds_summary_from_anchor(tmp_path, monkeypatch):
	"""sidecar 存了 checkpoint 但 c2_summary_text 缺失 → hydrate 从锚点回填。"""
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	w = WorkingSnapshot(session_id="cp2")
	note_compact_checkpoint(w, cursor=7, frozen_until=7, summary_text="ANCHOR-SUMMARY")
	# 人为清掉 c2_summary_text，模拟旧版本 / 丢失字段
	w.c2_summary_text = ""
	flush("cp2", w)

	got = hydrate("cp2")
	assert got.compact_cursor == 7
	assert got.c2_summary_text == "ANCHOR-SUMMARY"
	assert got.compact_checkpoint is not None


def test_extend_appends_to_window_chain(monkeypatch, mem_switch):
	mem_switch(XEYO_C2_LLM_SUMMARY="0")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	from memory.runtime import try_extend_c2
	from memory.simulator.params import Params

	msgs = [{"role": "user", "content": "x" * 5000} for _ in range(12)]
	w = WorkingSnapshot(compact_cursor=6, c1_frozen_until=6, c2_summary_text="FROZEN")
	w.c2_summary_text = "FROZEN"
	relaxed = Params(
		c2_extend_ratio=0.5,
		c2_extend_min_remaining_turns=2,
		c2_extend_safety_margin=1.0,
		c2_extend_price_ratio=3.0,
	)
	ok = try_extend_c2(w, msgs, 8, relaxed, remaining_turns=10, force=True)
	assert ok
	assert w.compact_checkpoint is not None
	assert len(w.compact_checkpoint.window_chain) >= 1
	assert w.compact_checkpoint.window_chain[-1]["cursor"] == 8


def test_checkpoint_serializes_all_fields(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	w = WorkingSnapshot(session_id="cp3")
	w.compact_checkpoint = CompactCheckpoint(
		version=1,
		anchor_cursor=9,
		anchor_frozen_until=9,
		anchor_summary="S",
		window_chain=[{"cursor": 9, "frozen_until": 9, "summary_fp": 1}],
	)
	flush("cp3", w)
	got = hydrate("cp3")
	assert got.compact_checkpoint.anchor_cursor == 9
	assert got.compact_checkpoint.anchor_summary == "S"
	assert got.compact_checkpoint.window_chain[0]["cursor"] == 9


def test_reset_after_rollback_clears_checkpoint(monkeypatch):
	from memory.working import reset_after_rollback

	w = WorkingSnapshot(session_id="cp4", compact_cursor=5, c1_frozen_until=5, c2_summary_text="STALE")
	w.compact_checkpoint = CompactCheckpoint(anchor_cursor=5, anchor_summary="STALE")
	reset_after_rollback("cp4")
	got = hydrate("cp4")
	assert got.compact_cursor == 0
	assert got.c2_summary_text == ""
	assert got.compact_checkpoint is None
