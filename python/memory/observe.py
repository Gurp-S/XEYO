"""逐枪校准观测：把热路径真实投影换算成 LCP / 预测 Ĥ，落盘给 calibration。

- 每个模型请求（note_shot 同一处）调用 observe_shot，用「上一枪实际发送的投影」算 LCP，
  再按 ρ̂(C)·g·⌊LCP/g⌋ 得预测命中，与 provider 返回的 observed_hit 一起写 calibration_events.jsonl。
- 本模块只在热路径做轻量计算 + 一次 JSONL 追加；任何异常都吞掉，绝不阻塞主循环。
- 供 memory/simulator/calibration.py 的 scan_rho 消费真实数据（对齐 prompt_cache_hit_tokens）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from memory.simulator.cache_model import CacheState, rho_hat
from memory.simulator.cost_model import hat_H
from memory.simulator.params import load_params
from memory.simulator.projection import lcp_tokens
from memory.working import WorkingSnapshot


def _idle_seconds(snap: WorkingSnapshot) -> float:
	"""估算距上次打模型的空闲秒数；无记录则 0（与 runtime.idle_seconds 一致）。"""
	at = snap.last_model_call_at
	if at is None:
		return 0.0
	now = datetime.now(at.tzinfo) if at.tzinfo else datetime.now()
	return max(0.0, (now - at).total_seconds())


def _canon(messages: list[dict[str, Any]]) -> str:
	"""实际发送投影的规范化字节序列（与 probe._canon 对齐，保证 LCP 可比）。"""
	try:
		return json.dumps(messages, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
	except (TypeError, ValueError):
		return ""


def _tool_result_chars(messages: list[dict[str, Any]]) -> int:
	"""投影里 tool_result 内容总字符数（反映 M 区负担）。"""
	n = 0
	for msg in messages:
		content = msg.get("content")
		if not isinstance(content, list):
			continue
		for block in content:
			if not isinstance(block, dict) or block.get("type") != "tool_result":
				continue
			raw = block.get("content")
			if isinstance(raw, str):
				n += len(raw)
	return n


def observe_shot(
	snap: WorkingSnapshot,
	projected: list[dict[str, Any]],
	*,
	hit: int = 0,
	miss: int = 0,
	out: int = 0,
	context_tokens: int | None = None,
	turn: int = 0,
	ts: float | None = None,
	provider: str | None = None,
	model: str | None = None,
	enabled: bool = True,
) -> None:
	"""记录一枪校准观测并更新 snap.last_x_sent（供下一枪 LCP）。

	enabled=False 时只更新 last_x_sent（供 Ĥ 预热），不落盘。
	"""
	action = str(getattr(snap, "last_action", "") or "keep")
	x_sent = _canon(projected)
	prompt_tokens = max(int(hit) + int(miss), 0)
	if enabled:
		try:
			p = load_params()
			age = _idle_seconds(snap)
			cache = CacheState(
				age_seconds=age,
				provider=provider or p.provider,
				model=model or p.model,
			)
			lcp = lcp_tokens(x_sent, getattr(snap, "last_x_sent", "") or "")
			pred_hit, _lcp_tok = hat_H(
				x_a=x_sent,
				x_prev=getattr(snap, "last_x_sent", "") or "",
				L=prompt_tokens or len(x_sent),
				action=action,
				rho=rho_hat(cache, p),
				g=p.g,
			)
			from usage.ledger import record_calibration_shot

			record_calibration_shot(
				ts=ts,
				session_id=getattr(snap, "session_id", "") or "",
				provider=provider or p.provider,
				model=model or p.model,
				action=action,
				cache_age=age,
				lcp=lcp,
				predicted_hit=pred_hit,
				observed_hit=float(hit),
				prompt_tokens=prompt_tokens,
				output_tokens=max(int(out), 0),
				context_length=max(int(context_tokens or prompt_tokens), 0),
				conversation_length=max(int(turn), 0),
				tool_result_size=_tool_result_chars(projected),
			)
		except Exception:
			# 校准观测失败不阻塞热路径
			logging.getLogger(__name__).debug("calibration observe failed", exc_info=True)
	snap.last_x_sent = x_sent
