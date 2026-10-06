"""在册缺口：晋升（foreground→job 的救援）必须严格早于编排层的工具截止。

两个预算各自独立、却在同一时刻相撞：

- 编排层 `tools/orchestration.py::_tool_timeout_s()` 默认 300s，把所有工具调用
  包在 `asyncio.wait_for(..., timeout=300)` 里；
- Bash 自己的分级超时（`tools/bash_tool/timeout_map.py`，cargo 420s）与
  显式 timeout（`MAX_TIMEOUT_MS=600s`）可以超过它，而晋升阈值是
  `min(BASH_PROMOTE_DEFAULT_MS=300s, 0.8×命令预算)` ⇒ **永远不会早于 300s**。

后果（实测 `_wsc_out/_probe_tool_timeout_vs_promote.py`，同比例缩小到外层 2s）：
模型拿到 `tool timed out after 2s: Bash`（error_kind=TIMEOUT），
`job_registry` 里**一个 job 都没有** ⇒ 产品设计的"长命令转后台、进程不重启、
已累积输出随晋升返回"这条救援在该档上根本没跑到，进程被留在外面。

`bash_tool.py:132-136` 自己写着：把晋升从 45s 抬到 300s 就是"为了 timeout_map 给
make/pip/apt 的 300s、cargo 的 420s 在前台真用得到"——抬到与外层截止相同的那一格，
只是把"永远进不了后台"换成了"永远赶不上外层"。

这里只钉不变量，不改常数（修法 A/B/C/D 待用户裁定）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _deadline_ms() -> float:
	from tools.orchestration import _tool_timeout_s

	value = _tool_timeout_s()
	return math.inf if value is None else float(value) * 1000.0


def _promote_ms(command: str, timeout_ms: int) -> int:
	from tools.bash_tool.bash_tool import promote_threshold_for

	return int(promote_threshold_for(command, timeout_ms))


def test_promotion_rescue_is_live_for_the_default_and_mid_families(monkeypatch) -> None:
	"""正向：≤360s 的档确实赶得上下外层截止（救援活着）。"""
	monkeypatch.delenv("XEYO_TOOL_TIMEOUT_S", raising=False)
	monkeypatch.delenv("XEYO_BASH_PROMOTE_MS", raising=False)
	deadline = _deadline_ms()
	assert deadline == 300_000.0, f"外层默认截止被改了：{deadline}"
	for timeout_ms in (120_000, 240_000, 300_000, 360_000):
		promote = _promote_ms("make", timeout_ms)
		assert 0 < promote < deadline, (timeout_ms, promote, deadline)


@pytest.mark.xfail(
	strict=True,
	reason="待拍：晋升上限 300s 与外层截止 300s 同格，等于没有先后",
)
def test_promote_ceiling_is_itself_below_the_deadline(monkeypatch) -> None:
	"""晋升上限（BASH_PROMOTE_DEFAULT_MS）必须严格小于外层截止。

	等于截止 ⇒ 同刻相撞，外层 wait_for 先取消工具协程，晋升永远来不及返回 job_id。
	"""
	monkeypatch.delenv("XEYO_TOOL_TIMEOUT_S", raising=False)
	monkeypatch.delenv("XEYO_BASH_PROMOTE_MS", raising=False)
	from tools.bash_tool import bash_tool as bt

	assert bt.promote_threshold_ms() == bt.BASH_PROMOTE_DEFAULT_MS
	assert bt.BASH_PROMOTE_DEFAULT_MS < _deadline_ms(), (
		f"晋升上限 {bt.BASH_PROMOTE_DEFAULT_MS}ms 不低于外层截止 "
		f"{_deadline_ms()}ms ⇒ 任何超过该预算的命令都拿不到 job"
	)


@pytest.mark.xfail(
	strict=True,
	reason="待拍：cargo 等 >375s 的族值与显式 timeout（可达 600s）都撞上外层 300s 截止",
)
def test_every_family_budget_and_the_explicit_max_precede_the_deadline(monkeypatch) -> None:
	monkeypatch.delenv("XEYO_TOOL_TIMEOUT_S", raising=False)
	monkeypatch.delenv("XEYO_BASH_PROMOTE_MS", raising=False)
	from tools.bash_tool import bash_tool as bt
	from tools.bash_tool.timeout_map import _FAMILY_TIMEOUTS_MS

	deadline = _deadline_ms()
	candidates = sorted(set(_FAMILY_TIMEOUTS_MS.values()) | {bt.MAX_TIMEOUT_MS})
	bad = [
		ms for ms in candidates if not (0 < _promote_ms("cargo", ms) < deadline)
	]
	assert not bad, f"这些预算档位赶不在外层截止之前（ms）：{bad}"
	assert max(candidates) <= deadline, (
		f"命令族/显式超时的最大值 {max(candidates)}ms 超过外层截止 {deadline}ms"
		" ⇒ 该档在结构上不可能生效"
	)


@pytest.mark.xfail(
	reason="待拍：外层 kill 时应把仍在运行的进程交还成 job（修法 B/D），今天既无 job 也无 bash 专属回执",
	strict=True,
)
def test_abandoned_long_command_still_hands_back_a_job(tmp_path, monkeypatch) -> None:
	"""行为面：晋升阈值晚于外层截止时，长命令至少要把活留下来的 job 交还给模型。"""
	import asyncio
	import time

	monkeypatch.setenv("XEYO_TOOL_TIMEOUT_S", "1")
	monkeypatch.setenv("XEYO_BASH_PROMOTE_MS", "1200")
	monkeypatch.setenv("XEYO_PERMISSION_MODE", "never")
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))

	from engine.abort import AbortController
	from msgtypes.message import ToolUse
	from tools.catalog import build_default_registry
	from tools.orchestration import _run_one_tool

	deadline = _deadline_ms()
	promote = _promote_ms("cargo", 2000)
	assert promote > deadline, "夹具没走到目标形状（晋升必须晚于外层截止）"

	reg = build_default_registry(cwd=str(tmp_path))
	tu = ToolUse(
		id="t-slow",
		name="Bash",
		input={
			"command": f'{sys.executable} -c "import time; time.sleep(8)"',
			"timeout": 2000,
		},
	)
	t0 = time.monotonic()
	res = asyncio.run(_run_one_tool(reg, tu, AbortController(), None))
	assert res.error_kind == "TIMEOUT", res.error_kind
	assert time.monotonic() - t0 < 7.0, "外层截止没起作用（用例走到的是另一条路）"

	from server.job_registry import get_job_registry

	jobs = get_job_registry().snapshot_list("")
	assert jobs, "被外层掐断的长命令必须留下可领取的 job（否则工作成果与进程一起丢）"
