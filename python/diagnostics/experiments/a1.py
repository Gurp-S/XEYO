"""A1 —— 同检查点单次响应配对（设计 §7 A1）。

冻结原始历史、工具 schema、模型与生成参数，只替换指定的提示词块，产生两份响应
并排呈现。**工具调用协议保留在请求里，但返回的 tool_use 一律不执行**：本模块不
接触 ToolRegistry / query_loop，直接驱动 ``prompt.assembler`` + ``client.stream``。

A1 回答"下一步输出或选择是否变化"，不证明整题成功；检查点里的历史本身就是旧提示
词影响下生成的（见 ``CAVEAT``）。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping

from diagnostics.identity import _s
from diagnostics.experiments.manifest import compare_arms, digest

MODE = "a1"

CAVEAT = (
	"检查点内的历史是在旧提示词影响下生成的：A1 测的是**检查点之后**替换该块的效果，"
	"不等同于从任务开始就采用新提示词。同参数同 seed 也不承诺云模型逐字确定。"
)
ANSWERS = "下一步输出或工具选择是否变化（结构可比部分给出事实，其余交人复核）。"
DOES_NOT_ANSWER = (
	"不回答整题能否完成、不回答多轮经济性、不把两臂输出相同当作等价证明。"
)

#: 变体能改的字段就是这些；其余一律由共享检查点提供，因此不可能逐臂漂移。
VARIANT_KEYS = ("blocks", "messages", "tools", "model", "provider", "params", "env")


class A1Error(RuntimeError):
	"""A1 层的中性错误。"""


class MarkerLeakError(A1Error):
	"""实验身份出现在请求正文里 ⇒ 观察器改变了被观察对象，立刻停止。"""


@dataclass
class Checkpoint:
	"""一次 A1 配对的冻结输入。"""

	blocks: dict[str, str] = field(default_factory=dict)
	block_order: list[str] = field(default_factory=list)
	messages: list[dict[str, Any]] = field(default_factory=list)
	tools: list[dict[str, Any]] = field(default_factory=list)
	model: str = ""
	provider: str = ""
	params: dict[str, Any] = field(default_factory=dict)
	env: dict[str, str] = field(default_factory=dict)
	source: dict[str, Any] = field(default_factory=dict)

	def system_text(self) -> str:
		"""system 消息由声明顺序的块拼成；未列入顺序的块不参与渲染（但仍在可比面里）。"""
		order = list(self.block_order or list(self.blocks))
		return "\n\n".join(_s(self.blocks.get(name)) for name in order if name in self.blocks)

	def substituted_blocks(self) -> list[str]:
		return list(self.block_order or list(self.blocks))


def _freeze(value: Any) -> Any:
	"""深拷贝一份，防止一臂的请求改动串到另一臂。"""
	return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _raw(value: Any) -> str:
	"""模型正文原样保留：``_s`` 会 strip，逐字流式片段不能被它改写。"""
	if value is None:
		return ""
	return value if isinstance(value, str) else str(value)


def apply_variant(checkpoint: Checkpoint, variant: Mapping[str, Any]) -> Checkpoint:
	"""把某臂的变体套到检查点上，返回独立副本。

	未知键直接拒绝：静默忽略一个"以为改了"的变量，等于偷偷做了一次非配对实验。
	"""
	unknown = sorted(k for k in (variant or {}) if k not in VARIANT_KEYS)
	if unknown:
		raise A1Error(f"variant_key_unsupported: {unknown}")
	out = replace(checkpoint)
	for key in VARIANT_KEYS:
		if key not in (variant or {}):
			continue
		value = (variant or {})[key]
		if key == "blocks":
			blocks = dict(out.blocks)
			for name, text in dict(value or {}).items():
				if not isinstance(text, str):
					raise A1Error(f"variant_block_not_text: {name}")
				blocks[_s(name)] = text
			out.blocks = blocks
			out.block_order = [n for n in (out.block_order or list(out.blocks)) if n in blocks]
		elif key == "params":
			params = dict(out.params)
			params.update(dict(value or {}))
			out.params = params
		elif key == "env":
			env = dict(out.env)
			env.update({_s(k): _s(v) for k, v in dict(value or {}).items()})
			out.env = env
		elif key in ("messages", "tools"):
			setattr(out, key, [dict(m) for m in list(value or [])])
		else:
			setattr(out, key, _s(value))
	return out


def render_arm(checkpoint: Checkpoint) -> dict[str, Any]:
	"""一臂的可比文档：逐字段展开后任何第二处差异都藏不住。"""
	return {
		"blocks": {name: _s(text) for name, text in checkpoint.blocks.items()},
		"block_order": list(checkpoint.block_order),
		"model": _s(checkpoint.model),
		"provider": _s(checkpoint.provider),
		"params": dict(checkpoint.params),
		"tools_digest": digest(_freeze(checkpoint.tools)),
		"history_digest": digest(_freeze(checkpoint.messages)),
		"history_count": len(checkpoint.messages),
		"env": dict(checkpoint.env),
	}


def build_request(checkpoint: Checkpoint) -> dict[str, Any]:
	"""真正发给模型客户端的请求面（system + 历史 + 工具协议 + 生成参数）。"""
	from prompt.assembler import PromptAssembler

	messages = PromptAssembler().build(
		checkpoint.system_text(),
		[dict(m) for m in _freeze(checkpoint.messages)],
	)
	return {
		"messages": messages,
		"tools": _freeze(checkpoint.tools),
		"model": _s(checkpoint.model),
		"provider": _s(checkpoint.provider),
		"params": dict(checkpoint.params),
	}


def _assert_no_marker(request: Mapping[str, Any], markers: Iterable[str]) -> None:
	payload = json.dumps(request.get("messages"), ensure_ascii=False, default=str)
	tools = json.dumps(request.get("tools"), ensure_ascii=False, default=str)
	for marker in markers:
		clean = _s(marker)
		if clean and (clean in payload or clean in tools):
			raise MarkerLeakError(f"marker_in_request: {clean[:16]}")


def _compress(events: list[str]) -> list[str]:
	out: list[str] = []
	for item in events:
		if out and out[-1] == item:
			continue
		out.append(item)
	return out


async def stream_once(
	*,
	client: Any,
	request: Mapping[str, Any],
	timeout_sec: float | None = None,
) -> dict[str, Any]:
	"""流式收一次响应，把结果**当数据**收下；tool_use 只登记，不执行。"""
	from engine.abort import AbortController

	abort = AbortController(label="a1")
	text: list[str] = []
	reasoning: list[str] = []
	tool_calls: list[dict[str, Any]] = []
	kinds: list[str] = []

	async def _consume() -> None:
		async for chunk in client.stream(
			list(request.get("messages") or []),
			list(request.get("tools") or []),
			abort,
		):
			kind = _s(getattr(chunk, "kind", "")) or type(chunk).__name__
			kinds.append(kind)
			if kind == "tool_use":
				use = getattr(chunk, "tool_use", None)
				tool_calls.append(
					{
						"id": _s(getattr(use, "id", "")),
						"name": _s(getattr(use, "name", "")),
						"input": getattr(use, "input", None),
						"input_digest": digest(getattr(use, "input", None)),
					}
				)
			elif kind == "reasoning_delta":
				reasoning.append(_raw(getattr(chunk, "text", "")))
			else:
				text.append(_raw(getattr(chunk, "text", "")))

	started = time.time()
	timed_out = False
	error = ""
	try:
		if timeout_sec:
			await asyncio.wait_for(_consume(), timeout=float(timeout_sec))
		else:
			await _consume()
	except asyncio.TimeoutError:
		timed_out = True
		abort.abort("a1_timeout")
	except Exception as exc:  # noqa: BLE001 — 失败本身就是要配对呈现的事实
		error = f"{type(exc).__name__}: {exc}"
	wall_ms = int((time.time() - started) * 1000)
	usage = getattr(client, "last_usage", None)
	return {
		"text": "".join(text),
		"reasoning_chars": len("".join(reasoning)),
		"tool_calls": tool_calls,
		"tool_calls_executed": 0,
		"event_kinds": _compress(kinds),
		"usage": dict(usage) if isinstance(usage, Mapping) else None,
		"usage_reported": isinstance(usage, Mapping) and bool(usage),
		"timed_out": timed_out,
		"aborted": bool(abort.aborted),
		"error": error,
		"wall_ms": wall_ms,
		"request_chars": sum(
			len(_raw(m.get("content")))
			for m in request.get("messages") or []
			if isinstance(m, Mapping)
		),
	}


def _structural_features(arm: Mapping[str, Any]) -> dict[str, Any]:
	response = arm.get("response") or {}
	text = _raw(response.get("text"))
	return {
		"error": _s(arm.get("error")) or _s(response.get("error")),
		"timed_out": bool(response.get("timed_out")),
		"text_chars": len(text),
		"first_line": text.splitlines()[0][:80] if text else "",
		"tool_names": sorted(_s(c.get("name")) for c in response.get("tool_calls") or []),
		"tool_call_count": len(response.get("tool_calls") or []),
		"tool_input_digests": sorted(_s(c.get("input_digest")) for c in response.get("tool_calls") or []),
		"event_shape": list(response.get("event_kinds") or []),
	}


def score_structural(arms: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
	"""能按结构判的就判（相等/不等是事实）；判不了的一律标 ``needs_human_review``。

	这里不出现"更好"：两臂输出不同只说明**变了**，不说明变化是收益。
	"""
	names = sorted(arms)
	feats = {arm: _structural_features(arms[arm]) for arm in names}
	deterministic: list[dict[str, Any]] = []
	needs_review: list[str] = []
	for feature in sorted({k for v in feats.values() for k in v}):
		values = {arm: feats[arm].get(feature) for arm in names}
		try:
			equal = len({json.dumps(v, ensure_ascii=False, sort_keys=True, default=str) for v in values.values()}) == 1
		except (TypeError, ValueError):
			equal = False
		deterministic.append({"feature": feature, "equal": equal, "values": values})
		if feature in ("text_chars", "first_line") and not equal:
			needs_review.append(f"{feature}: 文本内容差异需人工复核（结构判分不评价优劣）")
	return {
		"method": "structural",
		"features": deterministic,
		"identical_output": bool(
			feats and len({digest(feats[arm]) for arm in feats}) == 1
		),
		"different_output": bool(
			feats and len({digest(feats[arm]) for arm in feats}) > 1
		),
		"needs_human_review": sorted(set(needs_review)),
		"statement": (
			"结构判分只给出相同/不同与形状事实；文本谁更符合要求交给人复核。"
		),
	}


def _default_client() -> Any:
	from model.fake import FakeModelClient

	return FakeModelClient()


def run_pair(
	*,
	checkpoint: Checkpoint,
	variants: Mapping[str, Mapping[str, Any]],
	client: Any = None,
	allowed_differences: Iterable[str] | None = None,
	arm_order: Iterable[str] = ("A", "B"),
	budget: Any = None,
	experiment_id: str = "",
	request_keys: Mapping[str, str] | None = None,
	max_input_tokens: int | None = None,
	max_output_tokens: int | None = None,
	timeout_sec: float | None = None,
) -> dict[str, Any]:
	"""跑一次 A1 配对：先过单变量闸门，再逐臂发**一条**请求。

	``budget`` 是 ``reservation.Ledger``：预留被拒 ⇒ 该臂根本不发请求。usage 拿不到
	时账本按最大预留保留（A1 的 fake/流式客户端未必报用量）。
	"""
	arms_expected = ("A", "B")
	missing = [arm for arm in arms_expected if arm not in (variants or {})]
	if missing:
		raise A1Error(f"variants_missing_arms: {missing}")
	arm_cps = {arm: apply_variant(checkpoint, variants[arm]) for arm in arms_expected}
	docs = {arm: render_arm(arm_cps[arm]) for arm in arms_expected}
	declared = None if allowed_differences is None else list(allowed_differences)
	comparability = compare_arms(
		docs,
		allowed_differences=declared if declared is not None else _auto_allow(docs),
	)
	if not comparability.get("ok"):
		# 闸门在任何客户端调用之前：不可比的实验一分钱也不该花。
		raise _violation(comparability)

	client = client if client is not None else _default_client()
	used_client = client
	requests = {arm: build_request(arm_cps[arm]) for arm in arms_expected}
	# 先全臂检查标记泄漏：一臂被污染时另一臂也不该发出去（否则半途失败仍花了钱）。
	for arm in arms_expected:
		markers = [
			experiment_id,
			f"{experiment_id}_{arm}",
			request_keys.get(arm, "") if request_keys else "",
		]
		_assert_no_marker(requests[arm], [m for m in markers if _s(m)])
	results: dict[str, Any] = {}
	budget_rows: dict[str, Any] = {}
	for arm in [a for a in arm_order if a in arms_expected]:
		request = requests[arm]
		key = _s((request_keys or {}).get(arm)) or f"{_s(experiment_id) or 'a1'}#{arm}"
		gate: dict[str, Any] = {"allowed": True, "reason": "no_budget_gate"}
		if budget is not None:
			gate = budget.reserve(
				key,
				max_input_tokens=max_input_tokens
				if max_input_tokens is not None
				else _request_bound(request),
				max_output_tokens=max_output_tokens,
				billing_class="unknown",
				arm=arm,
			)
		if not gate.get("allowed"):
			results[arm] = {
				"sent": False,
				"invalid": True,
				"error": f"reservation_denied: {gate.get('reason')}",
				"response": {},
			}
			budget_rows[arm] = gate
			continue
		response = asyncio.run(stream_once(client=used_client, request=request, timeout_sec=timeout_sec))
		settled: dict[str, Any] = {}
		if budget is not None:
			settled = budget.reconcile(
				key,
				response.get("usage"),
				provider=_s(arm_cps[arm].provider),
				model=_s(arm_cps[arm].model),
				outcome="timeout" if response.get("timed_out") else "",
			)
		results[arm] = {
			"sent": True,
			"invalid": bool(response.get("error") or response.get("timed_out")),
			"request": {
				"message_count": len(request.get("messages") or []),
				"tool_count": len(request.get("tools") or []),
				"model": _s(request.get("model")),
				"provider": _s(request.get("provider")),
				"params": dict(request.get("params") or {}),
				"request_digest": digest(request),
			},
			"response": response,
			"error": _s(response.get("error")),
		}
		budget_rows[arm] = settled or gate
	pairing = score_structural(results)
	executed = sum(int((r.get("response") or {}).get("tool_calls_executed") or 0) for r in results.values())
	return {
		"mode": MODE,
		"experiment_id": _s(experiment_id),
		"generated_at": round(time.time(), 3),
		"comparability": comparability,
		"arms": results,
		"pairing": pairing,
		"budget": budget_rows,
		"tool_calls_executed_total": executed,
		"caveat": CAVEAT,
		"answers": ANSWERS,
		"does_not_answer": DOES_NOT_ANSWER,
		"claims": {
			"task_success": False,
			"allowed_conclusion": "只说明该块替换后下一步输出/选择是否变化。",
			"forbidden_conclusion": "不得据 A1 宣称整题成功、成本更低或新提示词更好。",
		},
		"coverage_gap": (
			"A1 只覆盖检查点之后的第一条响应；不执行工具，因此工具结果反馈后的行为不在范围内。"
		),
	}


def _auto_allow(docs: Mapping[str, Mapping[str, Any]]) -> list[str]:
	"""未显式声明时，把"两臂实际差异路径"当作声明项交给闸门。

	闸门本身仍要求差异恰好一处，所以自动推断不会放松单变量约束。
	"""
	flat = {arm: _flatten(doc) for arm, doc in docs.items()}
	paths = sorted({p for v in flat.values() for p in v})
	return [p for p in paths if len({json.dumps(flat[a].get(p), default=str) for a in flat}) > 1]


def _flatten(doc: Mapping[str, Any]) -> dict[str, Any]:
	from diagnostics.experiments.manifest import flatten

	return flatten(doc)


def _request_bound(request: Mapping[str, Any]) -> int:
	"""最坏输入上界：把请求正文按 4 字符/token 上取整，宁可多留不少留。"""
	chars = 0
	for message in request.get("messages") or []:
		if isinstance(message, Mapping):
			chars += len(_s(message.get("content")))
	chars += len(json.dumps(request.get("tools") or [], ensure_ascii=False, default=str))
	return int(chars / 4) + 1


def _violation(comparability: Mapping[str, Any]) -> A1Error:
	from diagnostics.experiments.manifest import SingleVariableViolation

	return SingleVariableViolation(dict(comparability))


def to_markdown(result: Mapping[str, Any]) -> str:
	"""两臂并排呈现（A1 的主产物就是给人看的对照，而不是一个分数）。"""
	lines = ["# A1 同检查点单请求配对", ""]
	lines.append(f"- 实验：`{_s(result.get('experiment_id')) or '—'}` · 生成时间：{result.get('generated_at')}")
	comparability = result.get("comparability") or {}
	lines.append(f"- 单变量闸门：{'通过' if comparability.get('ok') else '未通过'}")
	lines.append(f"- 差异路径：{', '.join(comparability.get('differences') or []) or '无'}")
	lines.append(f"- 声明项：{', '.join(comparability.get('allowed_differences') or []) or '（自动推断）'}")
	lines += ["", "## 两臂并排", ""]
	for arm in sorted(result.get("arms") or {}):
		entry = (result.get("arms") or {})[arm] or {}
		response = entry.get("response") or {}
		lines.append(f"### 臂 {arm}")
		lines.append("")
		lines.append(f"- 已发出请求：{'是' if entry.get('sent') else '否（' + _s(entry.get('error')) + '）'}")
		request = entry.get("request") or {}
		lines.append(
			f"- 请求面：{request.get('message_count', 0)} 条消息 / "
			f"{request.get('tool_count', 0)} 个工具 / 模型 `{_s(request.get('model'))}`"
		)
		text = _s(response.get("text"))
		lines.append(f"- 输出（{len(text)} 字符，工具调用未执行）：")
		lines.append("")
		lines.append("```text")
		lines.append(text[:2000] or "（无文本输出）")
		lines.append("```")
		calls = response.get("tool_calls") or []
		lines.append(f"- 返回的 tool_use：{len(calls)} 个 → " + ", ".join(_s(c.get("name")) for c in calls))
		if response.get("error") or response.get("timed_out"):
			lines.append(f"- 失败事实：{_s(response.get('error')) or 'timeout'}")
		lines.append("")
	pairing = result.get("pairing") or {}
	lines += ["## 结构判分", ""]
	lines.append(str(pairing.get("statement")))
	for feature in pairing.get("features") or []:
		lines.append(f"- `{feature.get('feature')}`：{'相同' if feature.get('equal') else '不同'}")
	review = pairing.get("needs_human_review") or []
	if review:
		lines.append("- 需人工复核：" + "；".join(review))
	lines += ["", "## 预算", ""]
	for arm in sorted(result.get("budget") or {}):
		row = result.get("budget") or {}
		lines.append(f"- 臂 {arm}：{_budget_line((row.get(arm) or {}))}")
	lines += ["", "## 结论边界", ""]
	lines.append(_s(result.get("caveat")))
	lines.append(_s(result.get("answers")))
	lines.append(_s(result.get("does_not_answer")))
	lines.append(f"覆盖缺口：{_s(result.get('coverage_gap'))}")
	claims = result.get("claims") or {}
	lines.append(_s(claims.get("allowed_conclusion")))
	lines.append(_s(claims.get("forbidden_conclusion")))
	return "\n".join(lines) + "\n"


def _budget_line(row: Mapping[str, Any]) -> str:
	if not row:
		return "无预算门（不付费路径）"
	if not row.get("allowed"):
		return f"预留被拒：{_s(row.get('reason'))}"
	spent = row.get("spent_cny")
	if spent is None:
		return f"已预留 {row.get('reserved_cny')}"
	usage = "有用量" if row.get("usage_seen") else "用量未知（按最大预留保留，未释放）"
	return f"花费 {spent}（{usage}）"


__all__ = [
	"ANSWERS",
	"CAVEAT",
	"DOES_NOT_ANSWER",
	"A1Error",
	"Checkpoint",
	"MarkerLeakError",
	"MODE",
	"VARIANT_KEYS",
	"apply_variant",
	"build_request",
	"render_arm",
	"run_pair",
	"score_structural",
	"stream_once",
	"to_markdown",
]
