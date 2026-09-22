"""评测档适配器（`evals/harbor_xeyo_agent.py`）的三条静态守卫。

为什么静态解析而不是 import：适配器依赖 `harbor.*`，那只装在 `TerminalBench/.venv-harbor313`
里，本测试环境导不进来。守卫要的是"配置形状不许漂"，用 AST 就够，而且不需要装 harbor。

三条守卫各挡一次真实事故：
1. **评测档必须带 `XEYO_WSC`**：`live_enabled()` 只认进程 env。它此前不在评测档里 ⇒
   历史全部 TB 跑分（含 26 绿）都是 WSC 关闭状态拿的，而"WSC 在 TB 上有没有用"
   这个问题从头到尾没被测过。
2. **不许写死某台机器的绝对路径**：旧值 `r"D:\\lea\\XenYon code\\python"` 换克隆路径就静默失效。
3. **防做题红线**：适配器不得按题目名分支（instruction 原样透传给引擎）。
"""
from __future__ import annotations

import ast
import io
import re
from pathlib import Path

_PY = Path(__file__).resolve().parents[2]          # → python/
IMPL = _PY / "evals" / "harbor_xeyo_agent.py"
SHIM = _PY.parent / "TerminalBench" / "xeyo_harbor_agent.py"
WIN_ABS = re.compile(r"[A-Za-z]:[\\/]{1,2}(?:Users|lea|Program Files)")


def _src() -> str:
	assert IMPL.exists(), f"适配器实现不在预期位置：{IMPL}"
	return io.open(IMPL, encoding="utf-8").read()


def _const_dict(tree: ast.Module, name: str) -> dict[str, str]:
	for node in tree.body:
		targets = ([node.target] if isinstance(node, ast.AnnAssign) else list(node.targets)) \
			if isinstance(node, (ast.Assign, ast.AnnAssign)) else []
		if any(getattr(t, "id", "") == name for t in targets) and isinstance(node.value, ast.Dict):
			out = {}
			for k, v in zip(node.value.keys, node.value.values):
				if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
					out[str(k.value)] = str(v.value)
			return out
	raise AssertionError(f"找不到常量 {name}")


def test_bench_env_carries_every_wsc_switch():
	"""评测档必须显式带 WSC 主开关；两个子旗标默认即可，但必须**在册可覆盖**。"""
	tree = ast.parse(_src())
	env = _const_dict(tree, "BENCH_ENV_DEFAULTS")
	assert env.get("XEYO_WSC") == "1", (
		"WSC 不在评测档 ⇒ 跑分用的还是 C2，测不到 WSC（历史 26 绿就是这个形状）")
	for key in ("XEYO_BENCH_MINIMAL", "XEYO_TOOL_SURFACE", "XEYO_ACTION_JOURNAL"):
		assert key in env, f"评测档少了 {key}"


def test_no_machine_absolute_path_and_window_not_hardcoded():
	"""不许写死克隆机的绝对路径；也不许把窗口钉成常数（钉窗口是**外层**机制档的事）。"""
	src = _src()
	code = ast.get_source_segment(src, ast.parse(src)) or src
	stripped = "\n".join(l for l in code.splitlines() if not l.lstrip().startswith("#"))
	assert not WIN_ABS.search(stripped), "适配器里出现了机器绑定的绝对路径"
	assert "XEYO_PY_DIR" in stripped, "python/ 路径必须可由 env 覆盖，否则换目录就失效"
	assert '"XEYO_CONTEXT_LIMIT"' not in _const_dict(ast.parse(src), "BENCH_ENV_DEFAULTS"), (
		"窗口不许进评测档默认值：那等于把按型号登记真实窗口这一步再钉回常数。"
		"机制档由外层 export XEYO_CONTEXT_LIMIT 决定，并会写进 trial metadata")


def test_adapter_does_not_branch_on_task_names():
	"""防做题红线：适配器里不许出现题目名或 task_name 分支。"""
	src = _src()
	hits = re.findall(r"(task_name\s*(?:==|in)\s*[\(\[\"'])|(terminal-bench/[a-z0-9\-]+)", src)
	assert not hits, f"适配器按题目分支（等于做题）：{hits[:3]}"
	assert "instruction" in src, "instruction 应当原样透传给引擎"


def test_entry_shim_is_a_dumb_forwarder():
	"""harbor 入口垫片只许转发：不含逻辑 ⇒ 实现漂移不会在两个地方各改一半。"""
	if not SHIM.exists():
		import pytest
		pytest.skip("TerminalBench/ 被 gitignore，本机没有垫片不影响仓库守卫")
	body = SHIM.read_text(encoding="utf-8")
	tree = ast.parse(body)
	funcs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
	assert not funcs, f"垫片里不该有函数（真实现才是权威）：{funcs}"
	assert "harbor_xeyo_agent.py" in body, "垫片必须指向 tracked 实现"
	assert "class XeyoHarborAgent" not in body, "垫片不许自带一份实现"
