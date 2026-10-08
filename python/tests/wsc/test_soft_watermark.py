"""软水位与停止规则（`memory/wsc_watermark.py`）的契约测试。

钉的是顾问 2026-09-30 那五条停止规则，逐条一测；外加一条"默认关 ⇒ 不改现行为"。
"""

from __future__ import annotations

import pytest

from memory import wsc_watermark as wm

pytest.importorskip("memory.wsc_watermark")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
	wm._STATE.clear()
	yield
	wm._STATE.clear()


def test_gate_off_by_default_returns_gate_off() -> None:
	"""旋钮退场后：水位恒 0 ⇒ 本模块不按绝对水位放行折叠（安全侧默认）。"""
	assert wm.soft_watermark_tokens() == 0
	assert wm.admit_assessment("s", input_tokens=10**9, identity="x|1|a") == wm.REASON_DISABLED


def test_retired_env_key_has_no_effect() -> None:
	"""``XEYO_WSC_SOFT_WATERMARK`` 已退场（2026-10-08 用户裁定）：设了也不再生效。

	新机制的判据明令"绝对 token 水位不得放行自动折叠"，唯一自动通路是
	``memory/wsc_timing`` 的容量压力（≥ 声明容量的 85%）。
	"""
	import os
	os.environ["XEYO_WSC_SOFT_WATERMARK"] = "48000"
	try:
		assert wm.soft_watermark_tokens() == 0
		assert wm.admit_assessment("s", input_tokens=10**9, identity="x|1|a") == wm.REASON_DISABLED
	finally:
		os.environ.pop("XEYO_WSC_SOFT_WATERMARK", None)


def test_below_watermark_is_refused_and_not_counted_as_an_assessment() -> None:
	assert wm.admit_assessment("s", input_tokens=47_999, identity="h|1|r", watermark=48_000) \
		== wm.REASON_BELOW
	# 被水位挡下不算一次精算 ⇒ 不登记身份，之后越线仍可评估
	assert wm.admit_assessment("s", input_tokens=52_000, identity="h|1|r", watermark=48_000) \
		== wm.REASON_OK


def test_same_candidate_is_not_priced_twice() -> None:
	assert wm.admit_assessment("s", input_tokens=52_000, identity="h|1|r", watermark=48_000) == wm.REASON_OK
	assert wm.admit_assessment("s", input_tokens=53_000, identity="h|1|r", watermark=48_000) \
		== wm.REASON_SAME_CANDIDATE


def test_candidate_identity_changes_on_in_place_revision_without_changing_count() -> None:
	"""消息条数不变、但被原地改写 ⇒ 必须是新候选（顾问明令不能只比条数）。"""
	a = wm.candidate_identity(head_version="h1", region_end=10, revision_state="rev-1")
	b = wm.candidate_identity(head_version="h1", region_end=10, revision_state="rev-2")
	assert a != b
	assert wm.admit_assessment("s", input_tokens=52_000, identity=a, watermark=48_000) == wm.REASON_OK
	assert wm.admit_assessment("s", input_tokens=52_000, identity=b, watermark=48_000) == wm.REASON_COOLDOWN


def test_admitted_assessment_starts_the_cooldown_even_if_theta_then_rejects() -> None:
	"""规则 4：冷却从"最近一次精算"起算，**包括被 θ 拒掉的那次**。

	本模块在"准予精算"时就登记枪号；θ 门随后拒不拒都在这次登记之后 ⇒ 不需要额外 API，
	也不会出现"被拒就立刻再精算同一个候选"的抖动。
	"""
	assert wm.admit_assessment("s", input_tokens=52_000, identity="h|1|r", watermark=48_000) == wm.REASON_OK
	for shot in range(2, 5):
		assert wm.admit_assessment("s", input_tokens=52_000 + shot, identity=f"h|{shot}|r",
		                           watermark=48_000) == wm.REASON_COOLDOWN, shot
	assert wm.admit_assessment("s", input_tokens=60_000, identity="h|5|r", watermark=48_000) == wm.REASON_OK


def test_assessment_shots_are_recorded_separately_from_folds() -> None:
	"""评估枪号与成功折叠枪号分开：本模块不许读写 ``turns_since_c2`` / ``compact_cursor``。"""
	for i in range(6):
		wm.admit_assessment("s", input_tokens=52_000, identity=f"h|{i}|r", watermark=48_000)
	st = wm.stats("s")
	assert st["shots"] == 6
	assert st["counts"][wm.REASON_OK] == 2, st["counts"]
	assert st["counts"][wm.REASON_COOLDOWN] == 4, st["counts"]


def test_module_never_touchs_fold_side_counters() -> None:
	"""规则 5 的源码级门：评估侧不许引用折叠侧状态。

	用 AST 而不是文本匹配——上一版拿 `inspect.getsource` 找标识符，结果被本模块
	docstring 里"绝不读写 turns_since_c2"这句**说明文字**自己触发，是假红。
	"""
	import ast
	import inspect

	tree = ast.parse(inspect.getsource(wm))
	referenced = {
		n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
	} | {
		n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
	}
	for forbidden in ("turns_since_c2", "compact_cursor", "note_c2", "c2_gap_shots"):
		assert forbidden not in referenced, f"评估侧偷偷引用了折叠侧状态：{forbidden}"
	# 反向自校：门不是空的——它确实看得见本模块真实引用的名字
	assert "soft_watermark_tokens" in referenced, "自校失败：AST 里一个引用都没抓到 ⇒ 这条门是空的"


def test_state_evicts_instead_of_growing_unbounded() -> None:
	wm._MAX_STATE = 3
	for i in range(6):
		wm.admit_assessment(f"s{i}", input_tokens=52_000, identity="h|1|r", watermark=48_000)
	assert len(wm._STATE) <= 3
