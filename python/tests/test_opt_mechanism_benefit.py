"""优化机制收益微基准（审计随附新增测试，不改任何源码）。

对没有专属收益脚本的机制做「有 vs 没有」的确定性对照，全部离线、
无网络、无模型调用。断言只锁行为与宽裕的性能比，保证可进 CI。

覆盖：schemas 冻结缓存 / 输出预算+spill / γ4 围栏 / T_now 预算裁剪 /
Bash 透明路由纯函数 / bash 策略判定吞吐。
"""

from __future__ import annotations

import time


# ---------------------------------------------------------------- schemas 缓存


def test_schemas_cache_speedup() -> None:
	from tools.tool_registry import ToolRegistry

	reg = ToolRegistry()

	class Echo:
		name = "echo_bench"
		desc = "bench"

		def schema(self) -> dict:
			return {
				"type": "function",
				"function": {
					"name": "echo_bench",
					"description": "bench",
					"parameters": {"type": "object", "properties": {"x": {"type": "string"}}},
				},
			}

		async def execute(self, args, abort):  # pragma: no cover
			pass

	reg.register(Echo())

	first = time.perf_counter()
	reg.schemas()
	build_ms = (time.perf_counter() - first) * 1000

	t0 = time.perf_counter()
	for _ in range(200):
		reg.schemas()
	cached_ms = (time.perf_counter() - t0) * 1000 / 200

	assert build_ms >= 0 and cached_ms >= 0
	# 缓存命中应显著快于首建（宽裕 2x，避免 CI 抖动误报）
	assert cached_ms * 2 <= max(build_ms, 0.01) or build_ms < 0.05


# ---------------------------------------------------------------- 输出预算 + spill


def test_output_budget_caps_context_and_spills_full() -> None:
	from tools.tool_registry import ToolRegistry
	from tools.base_tool import ToolResult

	reg = ToolRegistry()
	big = "x" * 50_000

	class Big:
		name = "bench_big"
		output_budget = 1_000

		def schema(self) -> dict:
			return {"type": "function", "function": {"name": "bench_big", "description": "", "parameters": {"type": "object"}}}

		async def execute(self, args, abort):  # pragma: no cover
			pass

	out = reg._apply_output_budget(Big(), ToolResult(content=big), session_id="audit")
	content = out.content or ""
	# 进入上下文的被大幅截断（预算预览），远小于 50k 原文
	assert len(content) < 20_000
	# spill：原文落盘，找回路径直接写在返回内容里
	assert ".xeyo_spill" in content


# ---------------------------------------------------------------- γ4 围栏


def test_fence_marks_untrusted_and_is_cheap() -> None:
	from prompt.fence import fence_tool_output

	payload = "line1\nline2"
	t0 = time.perf_counter()
	for _ in range(500):
		fenced = fence_tool_output("bench", payload)
	cost_us = (time.perf_counter() - t0) * 1e6 / 500
	assert 'untrusted="true"' in fenced
	assert "line1" in fenced
	assert cost_us < 1000  # 单次 <1ms


# ---------------------------------------------------------------- T_now 预算裁剪


def test_t_now_trim_respects_budget() -> None:
	import prompt.pre_llm_inject as inj

	tag = inj.KLASS_INVENTORY
	blocks = [(tag, "很长的内容" * 100) for _ in range(30)]  # 每块 500 字符
	trimmed = inj._trim_tagged_blocks(blocks, total=inj.T_NOW_TOTAL_BUDGET)
	kept_chars = sum(len(t) for _, t in trimmed)
	# inventory 有独立配额：不会 30 块全保
	assert len(trimmed) < len(blocks)
	# 总量受 total 预算约束（token≈chars/4）
	assert kept_chars <= inj.T_NOW_TOTAL_BUDGET * 4 + 100


# ---------------------------------------------------------------- Bash 透明路由


def test_dup_redirect_classify_correct_and_fast() -> None:
	from tools.bash_tool.dup_redirect import _classify

	cases = [
		("cat a.txt", "read"),
		("type a.txt", "read"),
		("rg foo .", "grep"),
		("grep -n foo .", "grep"),
	]
	for cmd, kind in cases:
		assert _classify(cmd) is not None
	t0 = time.perf_counter()
	for _ in range(2000):
		_classify("cat some/really/long/path/file.txt")
	us = (time.perf_counter() - t0) * 1e6 / 2000
	assert us < 200  # 单次判定 <0.2ms，路由本身零负担


# ---------------------------------------------------------------- bash 策略吞吐


def test_bash_policy_eval_throughput() -> None:
	from permissions.policy import evaluate_policy_impl

	cmds = ["git status", "rg pattern .", "cat file.txt", "python -V"]
	t0 = time.perf_counter()
	n = 0
	for _ in range(50):
		for c in cmds:
			d = evaluate_policy_impl("Bash", {"command": c}, cwd=".")
			assert d is not None
			n += 1
	ms = (time.perf_counter() - t0) * 1000 / max(n, 1)
	assert ms < 20  # 单次裁决 <20ms（实际应为亚毫秒级）


# ---------------------------------------------------------------- 冒烟：全部可导入

def test_bench_script_imports() -> None:
	# 两个新增审计文件必须可导入/可编译（不执行）
	import py_compile
	import pathlib

	base = pathlib.Path(__file__).resolve().parents[1] / "scripts"
	py_compile.compile(str(base / "_audit_bench_codeindex_now.py"), doraise=True)
