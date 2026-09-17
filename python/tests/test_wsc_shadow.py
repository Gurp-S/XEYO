"""WSC 影子档（阶段 B）契约测试。

影子档的三条红线必须机器锁死，否则它一旦越界就是**生产事故**而不是实验：
1. **默认关**：不设 `XEYO_WSC` 时一行都不写（否则等于悄悄在生产上跑 WSC）；
2. **不改发送**：`maybe_observe` 无返回值、不修改入参消息（它拿不到任何能影响发送的东西）；
3. **fail-open**：内部任何异常都不得外泄（影子档绝不能挡住主链）。

另有两条成本闸：每会话采样上限、短会话不算（影子要算一次 O(区域) 的投影）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory import wsc_shadow
from model.chunks import ModelChunk
from msgtypes.message import ToolUse
from wsc._fixtures import synth_session


@pytest.fixture()
def shadow_home(tmp_path, monkeypatch):
	tmp_path.mkdir(parents=True, exist_ok=True)
	monkeypatch.setenv("XEYO_HOME", str(tmp_path))
	monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "1")
	monkeypatch.setenv("XEYO_WSC_MIN_MESSAGES", "8")
	monkeypatch.setenv("XEYO_WSC_SAMPLE", "2")
	wsc_shadow.reset_for_tests()
	yield tmp_path
	wsc_shadow.reset_for_tests()


def _msgs(turns: int = 12):
	return synth_session(turns=turns, error_turn=3, user_every=4)


def test_disabled_by_default_writes_nothing(shadow_home, monkeypatch):
	monkeypatch.delenv("XEYO_WSC", raising=False)
	monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "0")  # 全局回退也必须关
	assert wsc_shadow.enabled() is False
	wsc_shadow.maybe_observe(_msgs(), session_id="s1", projected=_msgs())
	assert not wsc_shadow.log_path().exists(), "影子档默认关时不得落盘"


def test_shadow_does_not_ride_the_global_promote_default(shadow_home, monkeypatch):
	"""**实测踩过的坑**：走 `side_enabled` 时，未注册键会回退到 `sidemod_promote()`
	（全局升格默认 **开**）⇒ 影子档在用户毫不知情时开始花 CPU（本机实测 enabled()=True）。
	strict_env 语义下必须只认自己的 env。"""
	monkeypatch.delenv("XEYO_WSC", raising=False)
	monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "1")
	assert wsc_shadow.enabled() is False, "全局升格默认开不得带起影子档"
	monkeypatch.setenv("XEYO_WSC", "1")
	assert wsc_shadow.enabled() is True, "显式 env 必须仍然有效（env 是唯一开关）"


def test_enabled_records_one_row_with_expected_fields(shadow_home, monkeypatch):
	monkeypatch.setenv("XEYO_WSC", "1")
	assert wsc_shadow.enabled() is True
	wsc_shadow.maybe_observe(_msgs(), session_id="s1", projected=_msgs(), context_limit=131072)
	path = wsc_shadow.log_path()
	assert path.exists()
	rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
	assert len(rows) == 1
	r = rows[0]
	assert r["session"] == "s1"
	# 口径：三个 token 数必须由影子档用**同一把尺**算（`message_text + node_token_len`）。
	# 早期版本让调用方传 `Σ token_len(str(content))`，与 `wsc_tokens` 不可比
	# （列表型 content 带 Python repr，实测膨胀 1.31–3.40 倍）。
	assert r["actual_tokens"] > 0 and r["raw_tokens"] > 0
	assert r["raw_tokens"] >= r["actual_tokens"], "原文口径不应小于实际投影（同口径下）"
	assert r["context_limit"] == 131072
	for key in (
		"wsc_hot_tokens",
		"wsc_tokens",
		"region_raw_tokens",
		"fold",
		"saved",
		"transition",
		"remaining",
		"reason",
		"latency_ms",
		"n_messages",
		# 取回面（2026-09-16 用户裁定加入）：暴露量必须与真实使用量配对
		"handles_exposed",
		"retrieval_calls",
		"retrieval_turns",
		"nodes_pruned",
		"nodes_kept",
		"cards",
	):
		assert key in r, f"影子账目缺字段 {key}"
	assert r["handles_exposed"] >= 0
	assert r["retrieval_calls"] == 0 and r["retrieval_turns"] == 0
	assert r["nodes_pruned"] >= 0
	assert r["wsc_hot_tokens"] > 0
	assert r["reason"], "判据必须留下理由（否则无法归因）"


def test_shadow_uses_production_handle_form_with_externalized_view(
	shadow_home, monkeypatch, tmp_path
):
	"""影子必须量**生产形态**：句柄渲染成 `Read(...)`，取回视图落在 offload 根下。

	三个约束缺一即废：
	① 形态 = `read`（形态改变热层 token，跨形态的数字不可混用）；
	② 视图落在 `<ws>/.xeyo_offload/` 下（否则 `is_externalized_path` 判不出来 ⇒
	   `Read` 的 read-state 豁免失效，取回会挤掉真文件快照）；
	③ 视图路径**不能**与生产视图同路径（影子切点与生产不同，覆盖会让生产头部那些
	   `Read(offset=…)` 静默指向错内容）。
	"""
	from memory.offload import is_externalized_path

	monkeypatch.setenv("XEYO_WSC", "1")
	monkeypatch.delenv("XEYO_OFFLOAD_DIR", raising=False)
	ws = tmp_path / "ws"
	ws.mkdir(parents=True, exist_ok=True)
	wsc_shadow.maybe_observe(_msgs(), session_id="s1", projected=_msgs(), cwd=str(ws))
	rows = [
		json.loads(x)
		for x in wsc_shadow.log_path().read_text(encoding="utf-8").splitlines()
		if x.strip()
	]
	assert rows, "影子没有落账"
	r = rows[0]
	assert r["handle_style"] == "read", "影子量的是非生产形态（跨形态数字不可混用）"
	view = Path(r["view_path"])
	assert view.exists(), "取回视图没有落盘（模型取不回 ⇒ 引用的信息全丢）"
	assert ws / ".xeyo_offload" in view.parents, f"视图不在 offload 根下：{view}"
	assert r["view_externalized"] is True, "视图不被判为外部化 ⇒ read-state 豁免失效"
	assert is_externalized_path(view, ws) is True
	assert "#node " in view.read_text(encoding="utf-8"), "视图不是按行可寻址的取回视图"
	# ③ 与生产路径隔离：影子切点（region_end 未 pair-safe）与生产不同 ⇒ 同路径会互相覆盖
	assert "wsc-shadow" in view.parts, f"影子视图与生产视图同路径，会覆盖生产引用：{view}"


def test_shadow_view_follows_offload_dir_override(shadow_home, monkeypatch, tmp_path):
	"""offload 根被 `XEYO_OFFLOAD_DIR` 覆盖时视图必须跟着走（否则豁免判定失配）。"""
	from memory.offload import is_externalized_path

	root = tmp_path / "od"
	monkeypatch.setenv("XEYO_WSC", "1")
	monkeypatch.setenv("XEYO_OFFLOAD_DIR", str(root))
	wsc_shadow.maybe_observe(_msgs(), session_id="s1", projected=_msgs(), cwd=str(tmp_path))
	r = json.loads(wsc_shadow.log_path().read_text(encoding="utf-8").splitlines()[0])
	view = Path(r["view_path"])
	assert root in view.parents, f"没跟着 offload 根覆盖走：{view}"
	assert is_externalized_path(view, tmp_path) is True


def test_wsc_read_calls_match_relative_view_path(tmp_path):
	ws = tmp_path / "ws"
	view = ws / ".xeyo_offload" / "wsc-shadow" / "s1.txt"
	msgs = [
		{
			"role": "assistant",
			"content": [
				{
					"type": "tool_use",
					"name": "Read",
					"input": {"file_path": ".xeyo_offload/wsc-shadow/s1.txt"},
				},
			],
		}
	]
	assert wsc_shadow._wsc_read_calls(msgs, view, str(ws)) == (1, 1)


def test_returns_nothing_and_does_not_mutate_messages(shadow_home, monkeypatch):
	"""红线 1：影子档不得拥有任何能影响发送的输出。"""
	monkeypatch.setenv("XEYO_WSC", "1")
	msgs = _msgs()
	before = json.dumps(msgs, ensure_ascii=False, sort_keys=True)
	out = wsc_shadow.maybe_observe(msgs, session_id="s1", projected=_msgs())
	assert out is None
	assert json.dumps(msgs, ensure_ascii=False, sort_keys=True) == before, "入参消息被改写了"


def test_fail_open_on_internal_error(shadow_home, monkeypatch):
	"""红线 3：内部炸了也不能外泄（用 monkeypatch 制造真实异常）。"""
	monkeypatch.setenv("XEYO_WSC", "1")

	import importlib

	# 注意：`import synaptic.project as sp` 拿到的是**函数**（包 __init__ 重导出同名
	# 符号会遮蔽子模块），必须走 importlib 才拿到模块对象。
	sp = importlib.import_module("synaptic.project")

	def boom(*a, **kw):
		raise RuntimeError("simulated WSC failure")

	monkeypatch.setattr(sp, "project", boom)
	wsc_shadow.maybe_observe(_msgs(), session_id="s1", projected=_msgs())  # 不得抛
	assert not wsc_shadow.log_path().exists(), "失败轮不得落半条账"


def test_sample_cap_per_session(shadow_home, monkeypatch):
	"""成本闸：每会话最多记 `XEYO_WSC_SAMPLE` 轮（影子要算 O(区域) 的投影）。"""
	monkeypatch.setenv("XEYO_WSC", "1")
	monkeypatch.setenv("XEYO_WSC_SAMPLE", "2")
	running = _msgs()
	for i in range(5):
		running = running + _msgs(4)
		wsc_shadow.maybe_observe(running, session_id="cap", projected=running)
	rows = wsc_shadow.log_path().read_text(encoding="utf-8").splitlines()
	assert len(rows) == 2, f"采样上限失效：写了 {len(rows)} 行"
	# 另一个会话独立计数
	wsc_shadow.maybe_observe(running, session_id="other", projected=_msgs())
	assert len(wsc_shadow.log_path().read_text(encoding="utf-8").splitlines()) == 3


def test_short_sessions_are_skipped(shadow_home, monkeypatch):
	"""短会话本来就不该压（docs §11.4 第 2 条），影子也不该为它付费。"""
	monkeypatch.setenv("XEYO_WSC", "1")
	monkeypatch.setenv("XEYO_WSC_MIN_MESSAGES", "999")
	wsc_shadow.maybe_observe(_msgs(), session_id="s1", projected=_msgs())
	assert not wsc_shadow.log_path().exists()


def test_wiring_point_exists_in_query_loop():
	"""接线点必须存在且被 try/except 包裹（防「模块写了但没人调」）。"""
	src = (Path(__file__).resolve().parents[1] / "engine" / "query_loop.py").read_text(
		encoding="utf-8"
	)
	assert "from memory.wsc_shadow import maybe_observe" in src
	idx = src.index("maybe_observe(")
	assert "try:" in src[max(0, idx - 600) : idx], "影子档调用必须包在 try 内"


# ---------------------------------------------------------------------------
# 端到端：真的跑一轮 query_loop，验证接线点**真的会触发**
# （静态断言只能证明「调用了」，证明不了「走到那条分支」）
# ---------------------------------------------------------------------------

class _EchoTurnModel:
	"""每轮调一次 echo 的假模型（不花 API；照 `test_t_now_budget_text_revoked` 的驱动方式）。"""

	def __init__(self) -> None:
		self.requests: list[str] = []
		self.last_usage = {"prompt_tokens": 10, "completion_tokens": 2}

	async def stream(self, messages, tools, abort):  # noqa: ANN001
		abort.raise_if_aborted()
		self.requests.append(json.dumps(messages, ensure_ascii=False))
		yield ModelChunk(
			kind="tool_use",
			tool_use=ToolUse(id=f"call_{len(self.requests)}", name="echo", input={"text": "x"}),
		)


def test_shadow_fires_through_the_real_query_loop(shadow_home, monkeypatch, tmp_path):
	"""端到端：开启影子档后跑真实 `QueryEngine.submit`，账目必须落盘。

	这条测试防的是**接线点选错分支**：影子档接在「全量投影」分支上，
	若哪天缓存路径被改成默认，影子会静默永不触发（静态断言看不出来）。
	"""
	import asyncio

	from engine.query_engine import QueryEngine
	from tools.echo import EchoTool
	from tools.tool_registry import ToolRegistry

	monkeypatch.setenv("XEYO_WSC", "1")
	monkeypatch.setenv("XEYO_WSC_MIN_MESSAGES", "0")  # 单轮会话也要触发
	wsc_shadow.reset_for_tests()

	reg = ToolRegistry()
	reg.register(EchoTool())
	model = _EchoTurnModel()
	eng = QueryEngine(
		{  # type: ignore[arg-type]
			"cwd": str(tmp_path),
			"tools": reg,
			"model_client": model,
			"provider": "deepseek",
			"model": "deepseek-v4-flash",
			"max_turns": 1,
		}
	)

	async def _run():
		return [ev async for ev in eng.submit("go")]

	asyncio.run(_run())

	path = wsc_shadow.log_path()
	assert path.exists(), "影子档开启后跑真实一轮，账目却没落盘（接线点没走到）"
	rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
	assert rows, "账目文件为空"
	r = rows[-1]
	assert r["wsc_hot_tokens"] >= 0 and "fold" in r and "reason" in r
	# 取回视图必须落在**本轮工作区**（`cwd` 从 registry 传来）而不是进程 cwd
	view = Path(r["view_path"])
	assert view.exists() and (tmp_path / ".xeyo_offload") in view.parents, (
		f"视图没落在会话工作区的 offload 根下（cwd 没传对？）：{view}"
	)
	assert r["view_externalized"] is True
