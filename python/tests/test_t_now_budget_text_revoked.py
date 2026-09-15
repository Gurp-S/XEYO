"""撤块回归（2026-09-15 用户裁定）：预算/收尾文本从模型可见面撤除，
执行层（收尾窗状态机 / 收尾工具配额 / 硬停语义 / 成本闸）一律保留。

## 为什么撤（结构性根因，不是措辞问题）

``# Wrap-up(预算已尽)`` 与 ``# Runtime budget notice`` 都是 ``directive`` 类
（预算内绝不裁剪 ⇒ 必然进注意力），而它们只说"预算已尽 / 预算"**不标作用域**。
同一个 ``TurnBudget`` 里混装三种作用域的预算：

- 回合级：``max_turns`` / 工具配额 / ``grace_turns_remaining``（每次
  ``reset_for_new_submit`` 重置）
- 任务级：``wall_deadline_ts``（``reset_for_new_submit`` 不清除）
- 会话级：``used_usd`` / ``usd_limit``

⇒ 模型收到不标作用域的"预算已尽"只能自己猜：第五轮猜成「上下文窗口」、
第六轮再次猜成「上下文窗口」（本会话第一手复现）。

按引擎铁律（注意力里只出现信息不出现导演 / 限制只在执行层 / 能静默就不说话）：
收尾窗、工具配额、硬停、成本闸本来就是执行层事实，由 ``engine/query_loop``
的 ``prepare_next_turn()`` → ``forced_wrap_up`` → ``StoppedEvent`` 强制，
**不需要讲给模型听** ⇒ 撤文本，不撤机制。

## 本文件是双向回归

① **负向**：任何策略 / 任何声道下，模型可见面都不得出现该文本；
② **正向**：删的只是文本——收尾窗状态机、收尾配额、硬停与成本闸逐条照旧。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from engine.query_engine import QueryEngine
from model.chunks import ModelChunk
from msgtypes.events import StoppedEvent, ToolCallEvent, ToolResultEvent
from msgtypes.message import ToolUse
from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject
from tools.echo import EchoTool
from tools.tool_registry import ToolRegistry
from usage import pricing

#: 已撤文本的可检索指纹：出现在任何模型可见字节里即失败。
BANNED_BUDGET_TEXT = (
	"Wrap-up(预算已尽)",
	"Runtime budget notice",
	"预算/回合已达上限",
)

#: 块渲染指纹（只可能由已撤渲染器产出）。用于扫描**混有项目文档**的整请求字节
#: ——项目文档本身可能合法提到块名，但不可能内含块头（如 ``# Wrap-up(…)``）。
BLOCK_RENDER_FINGERPRINTS = (
	"# Wrap-up(预算已尽)",
	"# Runtime budget notice",
)

#: 固定价格表（USD/1M）——成本闸用例不依赖实时价与网络。
_PIN = {"input_miss": 2.0, "input_hit": 0.2, "output": 8.0}


# ---------------------------------------------------------------------------
# ① 负向：模型可见面（system 段 + 任何声道的注入尾）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", ("", "env_channel", "legacy", "system_channel"))
def test_revoked_budget_text_invisible_on_every_channel(strategy):
	"""撤块锚：任何声道都不得把预算文本送上模型可见面。"""
	kw: dict = {
		"forced_wrap_up": True,
		"runtime_notice": "turn 5/8",
		"multi_agent": True,
	}
	if strategy:
		kw["strategy"] = strategy
	out = run_pre_llm_inject(
		[{"role": "user", "content": "hi"}], InjectContext(cwd="", **kw)
	)
	blob = json.dumps(out, ensure_ascii=False)
	for banned in BANNED_BUDGET_TEXT:
		assert banned not in blob, f"{strategy or 'default'} 声道泄漏已撤文本：{banned}"
	# 非空洞：同一投影里"仍然存活"的块照常送达——撤的是这两个块，不是整个声道。
	assert "Multi-Agent" in blob


def test_registry_and_renderers_are_gone():
	"""撤块必须是**删除**而非"关掉装配点"：渲染器/常量不得留在模块上。

保留一个"预算已尽"文本生成器 = 给它留了重新接线的口子；本断言让重新接线
必须先新增代码，而不是改一行 ``if``。
	"""
	from prompt import pre_llm_inject as inj

	assert "wrap_up" not in inj.T_NOW_BLOCK_REGISTRY
	assert "runtime_budget" not in inj.T_NOW_BLOCK_REGISTRY
	assert not hasattr(inj, "_wrap_up_block_text"), "撤块后仍留着 wrap_up 渲染器"
	assert not hasattr(inj, "WRAP_UP_INSTRUCTIONS"), "撤块后仍留着 wrap_up 常量"


# ---------------------------------------------------------------------------
# ② 正向：执行层照旧（端到端驱动 query_loop，不经任何提示文本）
# ---------------------------------------------------------------------------


class _AlwaysToolModel:
	"""每轮调一次 echo；记录模型收到的每条请求字节，供"请求里有无预算文本"断言。"""

	def __init__(self, usage: dict | None = None) -> None:
		self.requests: list[str] = []
		self.last_usage = usage

	async def stream(self, messages, tools, abort):  # noqa: ANN001
		abort.raise_if_aborted()
		self.requests.append(json.dumps(messages, ensure_ascii=False))
		yield ModelChunk(
			kind="tool_use",
			tool_use=ToolUse(
				id=f"call_{len(self.requests)}",
				name="echo",
				input={"text": "loop"},
			),
		)


def _engine(model: object, **extra: object) -> QueryEngine:
	reg = ToolRegistry()
	reg.register(EchoTool())
	cfg: dict = {
		"cwd": ".",
		"tools": reg,
		"model_client": model,
		"provider": "deepseek",
		"model": "deepseek-v4-flash",
	}
	cfg.update(extra)
	return QueryEngine(cfg)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_wrap_window_and_hard_stop_survive_text_revocation():
	"""进收尾窗 → 配额内放行 → 硬停：全链路与提示文本无关。"""
	model = _AlwaysToolModel()
	eng = _engine(model, max_turns=1)
	events = [ev async for ev in eng.submit("go")]

	stopped = [e for e in events if isinstance(e, StoppedEvent)]
	assert stopped, "撤文本后硬停语义丢失"
	assert stopped[-1].reason == "max_turns"
	# 收尾窗确实打开过：预算耗尽后模型仍被请求至少一次（拿到收尾机会）
	assert len(model.requests) >= 2, "预算耗尽后未进入收尾窗"
	# 收尾配额内工具仍被执行（R3'：不再一开闸全禁）
	results = [e for e in events if isinstance(e, ToolResultEvent)]
	assert len(results) >= 2, "收尾窗内工具被误禁"
	# 全链路没有任何预算块文本进入模型可见面
	# （整请求含项目文档，故用块头指纹——文档可以提块名，不可能含块头）
	for blob in model.requests:
		for fp in BLOCK_RENDER_FINGERPRINTS:
			assert fp not in blob


@pytest.mark.asyncio
async def test_wrap_quota_still_gates_tools_inside_window(monkeypatch):
	"""收尾配额机制完好：``XEYO_WRAP_QUOTA=0`` 仍拒绝收尾窗内的调用。

数据口径（2026-09-15 探针 ``_wsc_out/_r7_probe_wrap.py``，``max_turns=1``，
确定性重放）：默认配额 → 4 次 ToolCallEvent；配额 0 → 3 次（被拒的那次不发
ToolCallEvent）。撤文本**没有**顺手把收尾配额放宽 —— 本测试是对照组。
	"""

	async def _tool_calls() -> int:
		model = _AlwaysToolModel()
		eng = _engine(model, max_turns=1)
		events = [ev async for ev in eng.submit("go")]
		return len([e for e in events if isinstance(e, ToolCallEvent)])

	monkeypatch.delenv("XEYO_WRAP_QUOTA", raising=False)
	default_calls = await _tool_calls()
	monkeypatch.setenv("XEYO_WRAP_QUOTA", "0")
	zero_calls = await _tool_calls()
	assert default_calls >= 3, "默认配额下收尾窗未放行任何调用"
	assert zero_calls < default_calls, "XEYO_WRAP_QUOTA=0 不再拦截收尾窗内调用"
	assert zero_calls == default_calls - 1


@pytest.mark.asyncio
async def test_cost_gate_unaffected_by_text_revocation(monkeypatch):
	"""成本闸照旧：USD 超限即 ``budget_usd`` 急停（与提示文本无关）。"""
	monkeypatch.setattr(
		pricing, "get_model_pricing", lambda provider, model, timeout=3.0: _PIN
	)
	usage = {
		"prompt_tokens": 500,
		"completion_tokens": 600,
		"total_tokens": 1100,
		"prompt_cache_hit_tokens": 0,
		"prompt_cache_miss_tokens": 500,
	}
	model = _AlwaysToolModel(usage=usage)
	eng = _engine(model, max_budget_usd=0.005, max_turns=50)
	events = [ev async for ev in eng.submit("go")]
	stopped = [e for e in events if isinstance(e, StoppedEvent)]
	assert stopped and stopped[-1].reason == "budget_usd"
