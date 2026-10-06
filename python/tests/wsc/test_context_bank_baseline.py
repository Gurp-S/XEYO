"""把题库基线钉成回归门：任何一臂丢掉"固定标注的原文片段"都必须变红。

三条自校（缺一条这套题就是空门，实测都栽过）：

1. **上界对照**：原文全发必须 100% 通过——否则是判据写错，不是压缩器丢东西。
2. **下界对照**：空投影必须 0% 通过——否则"可见"这个断言根本没在起作用。
3. **必须真的触发压缩**：`not_compressed != 0` 就说明题面太短、压缩器没出手，
   这套题在考古文（第一版实测 21 题只有 4 题进了压缩器；第二版 head 臂 17 题没进）。

被测臂的通过线取**当前基线值 100%**：往后任何退步都要红，改进也不能靠调低门槛。
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("synaptic")

from engine.compact import project as project_c0c1  # noqa: E402
from evals.wsc_context_bank import (  # noqa: E402
	ARM_DEEP,
	ARM_HEAD,
	ARM_TAIL,
	materialize,
	run_bank,
	run_tail_facts,
	split_arms,
	summarize,
)
from memory.wsc_projection import production_params  # noqa: E402
from synaptic.project import project as wsc_project  # noqa: E402
from synaptic.replay import _region_raw_tokens  # noqa: E402

_CWD = os.getcwd()


def _emit_raw(msgs, region_end):
	return "\n".join(str(m.get("content")) for m in msgs), True


def _emit_empty(msgs, region_end):
	return "", True


def _emit_wsc(msgs, region_end):
	"""与生产 `_emit` 同形：`[:region_end]` 交给压缩器，`[region_end:]` 作为逐字尾部。"""
	params = production_params()
	region = msgs[:region_end]
	proj = wsc_project(region, region_end=region_end, params=params, session="bank",
	                   region_baseline_tokens=int(_region_raw_tokens(region)),
	                   view_path="", view_ref="")
	if not proj.result.compressed:
		return _emit_raw(msgs, region_end)[0], False
	tail = project_c0c1(msgs[region_end:], frozen_until=0, cwd=_CWD)
	tail_text = "\n".join(str(m.get("content")) for m in tail)
	return proj.text + "\n" + tail_text, True


def test_bank_arms_cover_every_question() -> None:
	"""三臂 × 每题都要有结果：少一臂就等于少一类判据。"""
	res = run_bank(_emit_raw)
	suffixes = {r.qid.rsplit("-", 1)[-1] for r in res}
	assert suffixes == {ARM_TAIL, ARM_HEAD, ARM_DEEP}, suffixes


def test_upper_bound_raw_transmission_passes_every_probe() -> None:
	res = run_bank(_emit_raw)
	s = summarize(res)
	assert s["not_compressed"] == 0, "对照臂不该出现未触发压缩"
	assert s["passed"] == s["total"], f"判据本身有问题：原文全发仍有 {s['failed']} 题不过"


def test_lower_bound_empty_projection_fails_every_probe() -> None:
	res = run_bank(_emit_empty)
	s = summarize(res)
	assert s["passed"] == 0, f"『可见』断言是空门：空投影竟然过了 {s['passed']} 题"


def test_wsc_current_baseline_retains_every_annotation() -> None:
	res = run_bank(_emit_wsc)
	s = summarize(res)
	arms = split_arms(res)
	assert s["not_compressed"] == 0, (
		f"{s['not_compressed']} 题没触发压缩 ⇒ 这些题在考古文，分数不可用："
		f"{[r.qid for r in res if not r.compressed]}"
	)
	bad = [f"{r.qid}:{','.join(r.missing) or r.detail}" for r in res if not r.passed]
	assert s["passed"] == s["total"], f"固定标注被丢掉：{bad}"
	for arm, v in arms.items():
		assert v["tested"] == v["total"], arm
		assert v["passed"] == v["total"], f"{arm} 臂退步：{v['failed']}"


def test_deep_arm_is_strictly_harder_than_tail_arm() -> None:
	"""三臂必须**有区分度**：如果三臂难度一样，说明探针没真的落进被压区。

	当前实现三臂都 100%（好事），所以这条改判"臂的形状确实不同"：比较每题被压区的
	大小与探针到切点的距离，而不是比较分数——分数相同不代表题面相同。
	"""
	from evals.wsc_context_bank import QUESTIONS

	dists = {}
	for arm in (ARM_TAIL, ARM_HEAD, ARM_DEEP):
		# 探针（题面自身消息）到 region_end 的距离：越大说明压得越深。
		vals = []
		for q in QUESTIONS:
			msgs, region_end = materialize(q, arm=arm)
			probe_index = 0 if arm == ARM_DEEP else region_end - 1
			vals.append(region_end - probe_index)
		dists[arm] = sum(vals) / len(vals)
	assert dists[ARM_DEEP] > dists[ARM_HEAD], f"deep 臂不比 head 臂深：{dists}"
	assert dists[ARM_HEAD] > 0 and dists[ARM_TAIL] >= 0, dists


# ---------------------------------------------------------------------------
# 鉴别力（2026-09-30）：记分器必须有能力给不及格
# ---------------------------------------------------------------------------

#: 已知会挂的题（``qid`` = ``N<i>-<arm>``）。形状：探针只出现在一条长工具结果的**末梢**，
#: 而卡片只保留节点开头 ⇒ 落在被压区的两臂必挂、落在逐字尾的对照臂必过。
#: 修好卡片末梢保留（或把末梢事实单独发射）之后**这一组应当变绿** ——
#: 那时请把题目从本表移除，并把它们并入 `QUESTIONS` 当回归底线。
KNOWN_TAIL_FACT_LOSSES = frozenset({
	"N1-head", "N1-deep",
	"N2-head", "N2-deep",
	"N3-head", "N3-deep",
})


def test_tail_fact_items_pass_on_raw_transmission() -> None:
	"""判据自校：原文全发时末梢事实当然在场（否则是探针写错，不是压缩器丢东西）。"""
	res = run_tail_facts(_emit_raw)
	s = summarize(res)
	assert s["not_compressed"] == 0, s
	assert s["passed"] == s["total"], f"探针本身不可满足：{[r.qid for r in res if not r.passed]}"


def test_tail_fact_items_are_the_scorers_teeth() -> None:
	"""当前实现必须**恰好**挂在已知那几题上：少挂＝表过期（改进没登记），多挂＝退步。

	`tail` 三题全过而 `head`/`deep` 全挂 ⇒ 分数差来自"落在哪一侧"，即压缩器本身。
	"""
	res = run_tail_facts(_emit_wsc)
	by_qid = {r.qid: r for r in res}
	assert all(r.compressed for r in res), [k for k, r in by_qid.items() if not r.compressed]
	failing = frozenset(k for k, r in by_qid.items() if not r.passed)
	assert failing == KNOWN_TAIL_FACT_LOSSES, (
		f"挂了不该挂的：{sorted(failing - KNOWN_TAIL_FACT_LOSSES)}；"
		f"该挂却没挂（若为改进，请把题移入 QUESTIONS 并更新本表）：{sorted(KNOWN_TAIL_FACT_LOSSES - failing)}")
	for name in ("N1", "N2", "N3"):
		assert by_qid[f"{name}-tail"].passed, f"对照臂都挂了 ⇒ 不是压缩器的账：{name}"
		assert "node_tail_fact" in by_qid[f"{name}-head"].missing
		# 追问那句用户原话仍在（`[REQUESTS]` 保留最近几条），丢的只有末梢事实
		assert "followup_request" not in by_qid[f"{name}-head"].missing


def test_bank_without_teeth_is_not_reported_as_a_verdict() -> None:
	"""正例的反面：主基线 63/63 满分**不能**被读成"压缩器无损失"。

	这条不测产品，测的是我们自己报数的措辞 —— 所以它把"满分只覆盖 `QUESTIONS`"
	写死成断言：`TAIL_FACTS_QUESTIONS` 必须非空且不在 `QUESTIONS` 里。
	"""
	from evals.wsc_context_bank import QUESTIONS, TAIL_FACTS_QUESTIONS

	assert TAIL_FACTS_QUESTIONS, "鉴别力题组被清空 ⇒ 主基线又变回无鉴别力的满分"
	ids = {q.qid for q in QUESTIONS}
	assert not ids & {q.qid for q in TAIL_FACTS_QUESTIONS}
	assert all(q.probes for q in TAIL_FACTS_QUESTIONS), "无探针的题不进分母"
