"""旁路形态的不变量：算法层对生产链零依赖、包内无 LLM/网络依赖、token 口径同源。"""

from __future__ import annotations

from pathlib import Path

from synaptic.metrics import (
	ALGORITHM_MODULES,
	HARNESS_MODULES,
	assert_algorithm_isolation,
	assert_no_llm_dependency,
)

# tests/wsc/test_isolation.py -> parents[2] == python/
PKG = Path(__file__).resolve().parents[2] / "synaptic"


def test_algorithm_layer_has_zero_production_imports():
	"""算法层不得 import engine/memory/server/...——旁路必须可整目录删除。"""
	violations = assert_algorithm_isolation(PKG)
	assert violations == [], f"算法层混入生产依赖: {violations}"


def test_package_has_no_llm_or_network_imports():
	"""零 LLM 调用的静态执法：包内任何文件都不得 import 模型/网络库。"""
	violations = assert_no_llm_dependency(PKG)
	assert violations == [], f"包内出现 LLM/网络依赖: {violations}"


def test_algorithm_and_harness_module_lists_are_disjoint_and_complete():
	pkg_files = {p.name for p in PKG.glob("*.py")}
	assert set(ALGORITHM_MODULES) | set(HARNESS_MODULES) == pkg_files, (
		f"新增模块未归类：{sorted(pkg_files - set(ALGORITHM_MODULES) - set(HARNESS_MODULES))}"
	)


def test_harness_may_borrow_production_but_algorithm_may_not():
	"""反向断言：把 harness 也纳入检查时必须出现违规（证明检查真的在看）。"""
	violations = assert_algorithm_isolation(PKG)
	for name in HARNESS_MODULES:
		assert not any(v.startswith(name) for v in violations)


def test_token_estimator_matches_production_caliber():
	"""WSC 内联的 token 估参必须与生产链 memory.token 数值一致。"""
	from memory.token import token_len

	from synaptic.textutil import node_token_len

	for s in ("", "a", "中文测试", "x" * 1000, "混合 mixed 内容\n换行"):
		assert node_token_len(s) == token_len(s), f"token 口径漂移: {s!r}"
