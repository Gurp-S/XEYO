"""裁定器的 ``invoke=prod`` 节奏 = 生产语义：一旦压过就一直发「冻结头 + cursor 之后原文」。

为什么值得锁：评测台历史上对**每个用户回合**都尝试折叠，而生产只在过闸时折一次、
其后每轮发同一份冻结头 + 新增原文。两档测的不是同一个工况（回放台 legacy / adopted
两档的差就是这条），数字不可混用。最危险的漂移是"压过之后又回退整段原文"——那等于把
已经折掉的证据重新塞回被测量里，命中率虚高，且报告看不出来。
"""

from __future__ import annotations

import dataclasses

import pytest

from evals.wsc_failure_judge import (  # noqa: E402
	build_arm_contexts,
	hot_stats_from_rows,
	raw_text,
)
from memory.wsc_projection import production_params  # noqa: E402
from synaptic.textutil import node_token_len  # noqa: E402

HOT = "[MAIN] 冻结头（已折掉的区域）"


class _Session:
	def __init__(self, sid: str, messages: list[dict]) -> None:
		self.sid = sid
		self.messages = messages


class _Res:
	def __init__(self, compressed: bool) -> None:
		self.compressed = compressed
		self.rebuilt = False
		self.hot = type("H", (), {"tokens": node_token_len(HOT)})()
		self.base_tokens = 10_000


class _Proj:
	def __init__(self, text: str) -> None:
		self.text = text
		self.state = "state"
		self.cold = "cold"
		self.result = _Res(True)


def _msgs(n_turns: int = 4) -> list[dict]:
	out: list[dict] = []
	for i in range(n_turns):
		out.append({"role": "user", "content": f"任务步骤 {i}：读取 src/app.py 并修复 render 空指针 "
											   f"MARKER_USER_{i} " + ("填充 " * 18)})
		out.append({"role": "assistant", "content": f"第 {i} 步处理完毕 MARKER_ASST_{i} " + ("正文 " * 10)})
	return out


@pytest.fixture
def calls(monkeypatch):
	"""把 ``project`` 换成固定小头，并记录每次调用的 region_end。"""
	import evals.wsc_failure_judge as J

	seen: list[int] = []

	def fake_project(msgs, *, region_end=None, **kw):
		seen.append(int(region_end or 0))
		return _Proj(HOT)

	monkeypatch.setattr(J, "project", fake_project)
	return seen


def _params():
	return dataclasses.replace(production_params(), fold_cadence="always")


def test_every_turn_invocation_tries_every_turn(calls) -> None:
	sess = [_Session("s", _msgs())]
	ends = [0, 2, 4, 6, 8]
	build_arm_contexts(sess, _params(), invoke="every-turn")
	assert calls == ends, "历史口径应当每回合都尝试折叠"


def test_prod_gate_skips_below_water(calls) -> None:
	sess = [_Session("s", _msgs())]
	ctx, _f, rows, _sizes = build_arm_contexts(
		sess, _params(), invoke="prod", trigger_ratio=0.5, context_limit=220)
	assert calls and min(calls) > 0, "prod 档不该在第一回合就折"
	assert any(r.get("trigger_skipped") for r in rows), "水位闸没起作用 ⇒ 测的仍是每回合折叠"
	assert len(calls) < len(rows)


def test_prod_never_regresses_to_full_raw_after_fold(calls) -> None:
	msgs = _msgs()
	sess = [_Session("s", msgs)]
	ctx, _f, rows, _sizes = build_arm_contexts(
		sess, _params(), invoke="prod", trigger_ratio=0.5, context_limit=220)
	per = ctx["wsc"][sess[0].sid]
	folded_turn = min(r["turn"] for r in rows if r["compressed"])
	full = {e: raw_text(msgs[:e]) for e in (6, 8)}
	ends = {0: 0, 1: 2, 2: 4, 3: 6, 4: 8}
	post = [(t, per[t]) for t in sorted(per) if t > folded_turn]
	assert post, "折叠之后至少要有一个回合可查"
	for turn, text in post:
		assert text.startswith(HOT), f"回合 {turn} 的发出去的东西不是冻结头打头"
		assert text != full[ends[turn]], f"回合 {turn} 回退成了整段原文（虚高命中率的形状）"
		assert f"MARKER_USER_{turn - 1}" in text, "cursor 之后的新增原文必须逐字仍在上下文里"


def test_prod_arm_is_strictly_smaller_than_raw(calls) -> None:
	msgs = _msgs()
	sess = [_Session("s", msgs)]
	ctx, _f, rows, _sizes = build_arm_contexts(
		sess, _params(), invoke="prod", trigger_ratio=0.5, context_limit=220)
	per = ctx["wsc"]["s"]
	last = max(per)
	assert node_token_len(per[last]) < node_token_len(raw_text(msgs))
	stats = hot_stats_from_rows(rows, _params())
	assert stats["sessions_ever_folded"] == 1
	assert stats["sessions_total"] == 1
	assert stats["compressed_turns"] < stats["turns"]
