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
from memory.token import token_len
from memory.working import WorkingSnapshot


def _idle_seconds(snap: WorkingSnapshot) -> float:
	"""估算距上次打模型的空闲秒数；无记录则 0（与 runtime.idle_seconds 一致）。"""
	at = snap.last_model_call_at
	if at is None:
		return 0.0
	now = datetime.now(at.tzinfo) if at.tzinfo else datetime.now()
	return max(0.0, (now - at).total_seconds())


def _canon(messages: list[dict[str, Any]]) -> str:
	"""历史消息投影的规范序列；不含独立 system/tools，不能等同完整请求前缀。"""
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


#: 断点取证阈值：上一枪投影 ≥ 该 token 数、且与本枪共享前缀不足其一半 ⇒ 记证据。
#: （正常相邻枪 LCP 占比 ≈ 0.9+；只剩"折叠 / 恢复 / 吸收 / 外部注入"这类整段改写会破线。）
_BREAK_MIN_PREV_TOKENS = 8_000
_BREAK_LCP_RATIO = 0.5
_BREAK_SAMPLE_CHARS = 80
_BREAK_SCAN_CHUNK = 4_096


def prefix_break_evidence(
	prev: str, cur: str, *, action: str = "", extra: dict[str, Any] | None = None
) -> dict[str, Any] | None:
	"""前缀断裂的运行时取证：只在"明显断裂"时返回证据（幽灵类事故的唯一现场）。

	证据 = 断裂处的字符/ token 位置 + **断点两侧各 ~80 字符样本**。恢复(resume)、
	吸收、外部注入这类事故的事后重建都被运行时状态挡住（离线回放零复现），
	只有这一刻的两份投影字节能指认"是谁变了"。C2 折叠枪同样会触发（已知机制），
	消费侧按 action 过滤即可。
	"""
	if not prev or not cur:
		return None
	prev_tokens = token_len(prev)
	if prev_tokens < _BREAK_MIN_PREV_TOKENS:
		return None
	n = min(len(prev), len(cur))
	# 分块比较（C 速度）+ 块内逐字符细化；最坏 ~2 遍扫描，远小于一次模型调用。
	i = 0
	while i < n and prev[i : i + _BREAK_SCAN_CHUNK] == cur[i : i + _BREAK_SCAN_CHUNK]:
		i += _BREAK_SCAN_CHUNK
	hi = min(i + _BREAK_SCAN_CHUNK, n)
	while i < hi and prev[i] == cur[i]:
		i += 1
	diff_tokens = token_len(cur[:i])
	if diff_tokens >= int(prev_tokens * _BREAK_LCP_RATIO):
		return None
	lo = max(0, i - _BREAK_SAMPLE_CHARS // 2)

	def _flat(s: str) -> str:
		return " ".join(s.split())[: _BREAK_SAMPLE_CHARS]

	ev: dict[str, Any] = {
		"lcp_tokens": diff_tokens,
		"prev_tokens": prev_tokens,
		"cur_tokens": token_len(cur),
		"diff_char": i,
		"diff_token": diff_tokens,
		"action": str(action or ""),
		"prev_sample": _flat(prev[lo : i + _BREAK_SAMPLE_CHARS // 2]),
		"cur_sample": _flat(cur[lo : i + _BREAK_SAMPLE_CHARS // 2]),
	}
	if extra:
		ev.update(extra)
	return ev


def emit_prefix_break(session_id: str, evidence: dict[str, Any]) -> None:
	"""把断点证据写进审计（本地文件；审计不可用绝不影响主链）。"""
	try:
		from audit.log import default_audit_log

		default_audit_log().record("wsc.prefix_break", session_id=session_id, **evidence)
	except Exception:  # noqa: BLE001 — 取证不得挡推理
		pass


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
	cache_age: float | None = None,
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
			# 请求开始时的快照不受 note_shot 或后台观测调度延迟影响。
			age = _idle_seconds(snap) if cache_age is None else max(0.0, float(cache_age))
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
		# 断点取证（诊断）：明显的前缀断裂把"断在哪、两侧各是什么"写进审计。
		# fail-open、独立于校准账本写入；enabled=False（Ĥ 预热）没有这一路。
		try:
			_ev = prefix_break_evidence(
				getattr(snap, "last_x_sent", "") or "", x_sent, action=action
			)
			if _ev is not None:
				emit_prefix_break(getattr(snap, "session_id", "") or "", _ev)
		except Exception:  # noqa: BLE001 — 取证不得挡推理
			logging.getLogger(__name__).debug("prefix break capture failed", exc_info=True)
	snap.last_x_sent = x_sent
