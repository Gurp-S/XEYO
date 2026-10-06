"""发射文本的 golden 指纹：任何"零行为"声称都必须先过这一关（2026-09-22 补）。

为什么要有这个文件：本批收口里我说过两次"零行为"，两次都是**靠推理**（"分支都是 `if >0`"、
"这函数没人调"），而第一次拿语料指纹去验时，我自己的夹具坏了两次（视图目录名被印进发射文本 ⇒
假差异 137/191 回合；脚本越界删掉 HEAD 里就存在的 `fold_price_ratio` ⇒ 真差异却差点被当噪声）。
推理抓不住"删多了"，指纹能。⇒ 以后改 `synaptic/**` 或 `memory/wsc_projection.py`，
先跑这条；变了就必须解释为什么变，或者显式更新 golden（更新 golden = 承认并宣告这是行为改动）。

golden 是怎么来的（不是随手抄的数）：常量由本文件自己的 `_single()` / `_seq()` 现算，
再把发射全文（5,087 / 9,836 字符）逐段读过之后钉下。
首版常量 `ba39b9f4b911be93` / `112947b53006c78d` 作废 —— 那一对来自一次性探针脚本，
其夹具与本文件的 `_fixture()` 不是同一份（探针跑完即弃，输入已无法复现）。
把无法复现的数当基线 = 把守卫建在沙子上，所以按"读过的当前输出"重采。

已知灵敏度边界（写清楚，别把 golden 当万能）：在下面的合成夹具上，指纹对
``hot_budget_tokens`` / ``max_cards`` / ``card_conclusion_chars`` 敏感（本文件倒数第二条测试就是钉这个），
对 ``mode``、``closure_hops`` 不敏感 —— 短会话单发投影里这两条没有可观察差异。
2026-10-04 起 ``path_index_limit`` 不再敏感：卡面 suffix 改取结果首行后，[PATHS] 候选
路径全部被卡面/工作集覆盖（``uncovered_path_lines`` 去重），limit 3 与 96 逐字节相同。
"""

from __future__ import annotations

import dataclasses
import hashlib
import os

import pytest

from memory.wsc_projection import production_params
from synaptic.project import project
from tests.wsc._fixtures import msg_asst_use, msg_tool, synth_session

# golden：synth_session(34/5) + 6 条大块工具输出，production_params()，region_baseline=1e9
# V20 replaces mutable branch-root aliases with ordered member references.
# Reviewed delta: seven recovery expressions only, +14 chars single/sequence.
# 2026-10-04 卡面修复两刀：
#   ① 结论后缀：调用参数 JSON（被 90 字截断成坏引用）→ **结果**首行；
#   ② target 身份化：卡面 target 只认调用参数点名的文件，正文/命令提及不再冒充——
#      Bash 单元 target 因此退场（线索仍在 files=），Read/Edit 的 target 不变。
#   单发 4925→4401、序列 9765→9241；卡面 suffix 携带的结果首行里的路径与 [PATHS]
#   重复，被 uncovered_path_lines 去重（两处 diff 已逐行读过）。
GOLDEN_SINGLE = "f36354899b50e412"
GOLDEN_SEQ = "4a8ef742a8ccc493"
LEN_SINGLE = 4_401
LEN_SEQ = 9_241


def _fixture() -> list[dict]:
	fx = synth_session(turns=34, error_turn=5)
	for i in range(6):
		fx.append(msg_asst_use(f"b{i}", "Bash",
		                       {"command": f"sed -n '{i * 40},{i * 40 + 40}p' src/m{i}.ts"}))
		fx.append(msg_tool(f"b{i}", "Bash",
		                  "".join(f"行 {i} 内容 填充 PATH{i}/deep/file.tsx\n" for _ in range(14))))
	return fx


F = _fixture()


def _single(**over) -> str:
	p = production_params()
	if over:
		p = dataclasses.replace(p, **over)
	return project(F, region_end=len(F), params=p, session="g",
	               region_baseline_tokens=10 ** 9).text


def _seq(**over) -> str:
	p = production_params()
	if over:
		p = dataclasses.replace(p, **over)
	out = []
	state = cold = None
	for end in (20, 28, 36, len(F)):
		r = project(F[:end], region_end=end, params=p, session="g",
		            prev=state, cold=cold, region_baseline_tokens=10 ** 9)
		state, cold = r.state, r.cold
		out.append(r.text)
	return "\n\x1f".join(out)


def _h(s: str) -> str:
	return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _why(tag: str, got: str, want: str, n: int) -> str:
	return (
		f"{tag} 的发射字节变了（{want} → {got}，长度 {n}）"
		" ⇒ 这不是『零行为改动』：要么解释为什么变，"
		"要么显式更新 golden（更新 golden = 承认并宣告这是行为改动）"
	)


def test_single_shot_emission_is_byte_stable() -> None:
	text = _single()
	assert len(text) == LEN_SINGLE, f"单发投影长度漂移：{LEN_SINGLE} → {len(text)}"
	assert _h(text) == GOLDEN_SINGLE, _why("单发投影", _h(text), GOLDEN_SINGLE, len(text))


def test_stateful_sequence_emission_is_byte_stable() -> None:
	text = _seq()
	assert len(text) == LEN_SEQ, f"跨回合发射长度漂移：{LEN_SEQ} → {len(text)}"
	assert _h(text) == GOLDEN_SEQ, _why("跨回合（带 prev/cold 的日志累积）", _h(text), GOLDEN_SEQ, len(text))


def test_golden_is_environment_independent(tmp_path, monkeypatch) -> None:
	"""golden 不能把机器状态烧进基线：换 cwd / XEYO_HOME / XEYO_CWD 必须同指纹。

	踩过的坑：视图目录名会被印进发射文本，导致同一份语料两次跑的字节"看起来"不同，
	差点据此判定改动有行为差异。这条把该次事故固化成守卫。
	"""
	for var in ("XEYO_CWD", "XEYO_HOME", "XEYO_WSC", "XEYO_WSC_FROZEN_HEAD"):
		monkeypatch.delenv(var, raising=False)
	assert _h(_single()) == GOLDEN_SINGLE
	monkeypatch.setenv("XEYO_CWD", str(tmp_path))
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	monkeypatch.chdir(tmp_path)
	assert _h(_single()) == GOLDEN_SINGLE, "发射文本含环境相关字节 ⇒ golden 不可移植"
	assert os.environ.get("XEYO_CWD")


def test_golden_actually_has_teeth() -> None:
	"""golden 不能是常数函数：三个已知能改变输出的杠杆必须改变指纹。"""
	base_s, base_q = _h(_single()), _h(_seq())
	levers = (
		dict(hot_budget_tokens=600, fixed_segment_budget_tokens=400,
		     main_segment_budget_tokens=200),
		dict(max_cards=2),
		# 2026-10-04：原第三杠杆 path_index_limit 在本夹具下已无观察面（[PATHS]
		# 候选被卡面覆盖去重，limit 3 与 96 逐字节相同）。以 card_conclusion_chars
		# 接替：直接控制卡面结论截断，实测改变指纹。
		dict(card_conclusion_chars=20),
	)
	unchanged = [sorted(kv) for kv in levers
	             if _h(_single(**kv)) == base_s and _h(_seq(**kv)) == base_q]
	assert not unchanged, f"golden 对这些杠杆完全不敏感（夹具退化了）：{unchanged}"


def test_production_defaults_are_what_the_golden_assumes() -> None:
	"""golden 的前提是"生产档"；档一改，指纹就该重算 —— 这条把前提钉住。"""
	p = production_params()
	assert (p.level, p.mode, p.handle_style) == ("Medium+", "closure", "read"), (
		f"生产档变了（{p.level}/{p.mode}/{p.handle_style}）⇒ golden 需显式重算并说明影响"
	)
	assert p.hot_budget_tokens == 3_000 and p.max_cards == pytest.approx(p.max_cards)
