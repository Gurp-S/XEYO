"""评测台的 WSC 臂必须等于**生产实际发出的那个投影**（防配置与状态再分叉）。

事故形态（2026-09-21 实测）：``evals/wsc_failure_judge.py`` 自己抄了一份
``default_params("Medium+", "closure")``，于是它评的是
``fold_cadence=always`` + ``handle_style=expand`` + **每回合无状态重投**的投影，
而 ``memory/wsc_projection.py`` 生产跑的是 ``econ`` + ``read`` + 跨回合携带
``prev``/``cold``。两者热层中位数 2,467 vs 10,234 tok —— 差 4 倍，差的就是没被测到的那个东西。
另一个同源缺陷：未过收益门/触发闸时生产根本不发投影（直接回退 C2 发原文），
旧臂却仍拿 ``hot.text`` 判可见性 = 给一个从未发送的投影记分。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

JUDGE = Path(__file__).resolve().parents[2] / "python" / "evals" / "wsc_failure_judge.py"


def test_judge_does_not_redeclare_production_config() -> None:
	"""静态防漂移：裁定器里不许再出现自造参数的调用。"""
	src = JUDGE.read_text(encoding="utf-8")
	assert "default_params(" not in src, (
		"裁定器又自己抄了一份 WscParams 构造 ⇒ 与生产配置分叉；"
		"改用 memory.wsc_projection.production_params()"
	)
	assert "production_params()" in src


def test_judge_params_are_exactly_production_params() -> None:
	from evals.wsc_failure_judge import production_params as judge_pp
	from memory.wsc_projection import production_params

	p1, p2 = judge_pp(), production_params()
	diff = {
		f.name: (getattr(p1, f.name), getattr(p2, f.name))
		for f in dataclasses.fields(p1)
		if getattr(p1, f.name) != getattr(p2, f.name)
	}
	assert not diff, f"评测台与生产配置分叉：{diff}"


def test_arm_carries_state_across_turns() -> None:
	"""有状态：第二次投影必须看到第一次的 ``prev``（日志累积/换头才进被测量）。"""
	import evals.wsc_failure_judge as J

	seen: list[bool] = []

	def fake_project(msgs, *, region_end, params, session, prev=None, cold=None, **kw):
		seen.append(prev is not None)
		raise AssertionError("stop-after-capture")

	real = J.project
	J.project = fake_project
	try:
		msgs = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
		try:
			J._project_prefix(msgs, 2, "s1", None, prev=object())
		except AssertionError:
			pass
	finally:
		J.project = real
	assert seen == [True], "裁定器没把上一轮状态传给投影 ⇒ 又在量无状态单发"


def test_skipped_turn_arm_is_the_uncompressed_prefix() -> None:
	"""未过闸的回合：生产发原文 ⇒ 臂也必须是原文，不许拿未发送的投影记分。"""
	import evals.wsc_failure_judge as J

	class _Res:
		compressed = False
		rebuilt = False
		hot = type("H", (), {"tokens": 123})()
		base_tokens = 999

	class _Proj:
		text = "[CONSTRAINTS] 这是一份从未发送给模型的诊断投影"
		state = cold = None
		result = _Res()

	captured = {}

	def fake_project(msgs, **kw):
		captured["kw"] = kw
		return _Proj()

	real = J.project
	J.project = fake_project
	try:
		msgs = [{"role": "user", "content": "原文前缀"}] * 4
		text, _proj = J._project_prefix(msgs, 4, "s", None)
	finally:
		J.project = real
	assert text == J.raw_text(msgs), "未压缩回合的臂仍在用 hot.text"
	assert captured["kw"]["region_baseline_tokens"] >= 0
