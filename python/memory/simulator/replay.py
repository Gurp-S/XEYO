"""Replay XEYO session JSONL into S0 and run v6.1 vs baseline project()."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memory.simulator.cache_model import CacheState
from memory.simulator.cost_model import shot_cost
from memory.simulator.decision import decide
from memory.simulator.params import Params, load_params
from memory.simulator.scenarios import DEFAULT_SYSTEM, state_from_messages
from memory.simulator.state_model import token_len

CORRECTION_PHRASES = (
	"你已经做过了",
	"不是这个文件",
	"我说的是另一个",
	"已经做过",
	"不是这个",
	"我说的是",
	"重做",
	"撤回",
	"不要改这个",
)

REVERT_PHRASES = ("revert", "redo", "回滚", "重做", "撤销")


def default_sessions_dir() -> Path:
	import os

	override = os.environ.get("XEYO_SESSIONS_DIR", "").strip()
	if override:
		return Path(override).expanduser()
	return Path.home() / ".xeyo" / "sessions"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
	if not path.is_file():
		return []
	out: list[dict[str, Any]] = []
	with path.open("r", encoding="utf-8") as f:
		for line in f:
			line = line.strip()
			if not line:
				continue
			try:
				obj = json.loads(line)
			except json.JSONDecodeError:
				continue
			if isinstance(obj, dict):
				out.append(obj)
	return out


def _as_api_message(row: dict[str, Any]) -> dict[str, Any]:
	role = str(row.get("role") or "user")
	content = row.get("content")
	if role == "tool":
		return {"role": "user", "content": content, "name": row.get("name")}
	msg: dict[str, Any] = {"role": role, "content": content}
	if row.get("name"):
		msg["name"] = row.get("name")
	return msg


def _is_user_text(msg: dict[str, Any]) -> bool:
	if msg.get("role") != "user":
		return False
	c = msg.get("content")
	if isinstance(c, str):
		return True
	if isinstance(c, list):
		return all(
			not (isinstance(b, dict) and b.get("type") == "tool_result") for b in c
		)
	return False


def user_text(msg: dict[str, Any]) -> str:
	c = msg.get("content")
	if isinstance(c, str):
		return c
	if isinstance(c, list):
		parts = []
		for b in c:
			if isinstance(b, dict) and b.get("type") == "text":
				parts.append(str(b.get("text") or ""))
			elif isinstance(b, str):
				parts.append(b)
		return "\n".join(parts)
	return ""


def count_corrections(messages: list[dict[str, Any]]) -> int:
	n = 0
	for m in messages:
		if not _is_user_text(m):
			continue
		text = user_text(m)
		if any(p in text for p in CORRECTION_PHRASES):
			n += 1
	return n


def count_reverts(messages: list[dict[str, Any]]) -> int:
	n = 0
	for m in messages:
		text = user_text(m) if m.get("role") == "user" else str(m.get("content") or "")
		low = text.lower()
		if any(p in text or p in low for p in REVERT_PHRASES):
			n += 1
	return n


def tool_loop_flags(messages: list[dict[str, Any]]) -> dict[str, int]:
	reads: dict[str, int] = {}
	greps: dict[str, int] = {}
	for m in messages:
		c = m.get("content")
		if not isinstance(c, list):
			continue
		for b in c:
			if not isinstance(b, dict) or b.get("type") != "tool_use":
				continue
			name = str(b.get("name") or "")
			inp = b.get("input") if isinstance(b.get("input"), dict) else {}
			if name == "Read":
				key = str(inp.get("path") or inp.get("file") or "unknown")
				reads[key] = reads.get(key, 0) + 1
			elif name == "Grep":
				key = str(inp.get("pattern") or inp.get("q") or "unknown")
				greps[key] = greps.get(key, 0) + 1
	return {
		"same_read_ge3": sum(1 for v in reads.values() if v >= 3),
		"same_grep_ge3": sum(1 for v in greps.values() if v >= 3),
		"read_calls": sum(reads.values()),
		"grep_calls": sum(greps.values()),
	}


def estimate_remaining(messages: list[dict[str, Any]], params: Params | None = None) -> int:
	"""R 估计：收尾=1；否则按会话深度衰减、封顶 params.r_cap（默认 24，不再硬编码）。"""
	p = params or load_params()
	texts = [user_text(m) for m in messages if _is_user_text(m)]
	if texts:
		last = texts[-1]
		if any(x in last for x in ("就这样", "谢谢", "够了", "可以了", "结束")):
			return 1
	n_user = max(1, len(texts))
	cap = max(4, int(getattr(p, "r_cap", 24) or 24))
	return min(cap, max(4, 16 - n_user // 8))


def baseline_tokens(messages: list[dict[str, Any]]) -> int:
	from engine.compact import project as compact_project

	out = compact_project(messages)
	blob = json.dumps(out, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
	return token_len(blob)


@dataclass
class ReplayTurn:
	session: str
	turn: int
	predicted: str
	a4: str
	a8: str
	a16: str
	hardtop: bool
	baseline_tokens: int
	v61_tokens: int
	predicted_hit: float
	simulated_cost: float
	Q: float
	D: float
	L: int
	G_beta: int
	baseline_behavior: str = "always_c1_like"


@dataclass
class ReplaySession:
	session: str
	path: str
	turns: list[ReplayTurn] = field(default_factory=list)
	corrections: int = 0
	reverts: int = 0
	loops: dict[str, int] = field(default_factory=dict)
	n_messages: int = 0


def _user_turn_indices(api_msgs: list[dict[str, Any]]) -> list[int]:
	idxs = []
	for i, m in enumerate(api_msgs):
		if _is_user_text(m):
			idxs.append(i)
	return idxs


def _summary_msg(text: str) -> dict[str, Any]:
	return {"role": "assistant", "content": text, "name": "session_summary"}


def _region_chars(msgs: list[dict[str, Any]]) -> int:
	n = 0
	for m in msgs:
		c = m.get("content")
		if isinstance(c, str):
			n += len(c)
		elif isinstance(c, list):
			for b in c:
				if not isinstance(b, dict):
					continue
				txt = b.get("content") or b.get("text") or b.get("input")
				if isinstance(txt, str):
					n += len(txt)
	return n


def _pair_safe_cut(msgs: list[dict[str, Any]], cut: int) -> int:
	cut = max(0, min(int(cut), len(msgs)))
	ranges: list[tuple[int, int]] = []
	pending: int | None = None
	for i, m in enumerate(msgs):
		role = str(m.get("role") or "")
		c = m.get("content")
		if role == "assistant" and isinstance(c, list) and any(
			isinstance(b, dict) and b.get("type") == "tool_use" for b in c
		):
			pending = i
		elif role == "tool" and pending is not None:
			ranges.append((pending, i + 1))
			pending = None
	for s, e in ranges:
		if s < cut < e:
			cut = s
	return cut


def _c2_cut(api_msgs: list[dict[str, Any]], end: int) -> int:
	from engine.compact import KEEP_TAIL_MESSAGES

	raw = max(0, int(end) - KEEP_TAIL_MESSAGES)
	return _pair_safe_cut(api_msgs[:end], raw)


def replay_messages(
	api_msgs: list[dict[str, Any]],
	*,
	session_id: str,
	params: Params | None = None,
	cursor: int = 0,
) -> ReplaySession:
	"""逐用户轮回放，模型 C1/C2 压缩态持久（与 runtime 一致）。

	- C2 一旦触发，后续轮继续发「冻结摘要 + 右尾」紧凑投影（字节稳定 → KV 命中）；
	  只有待压缩区收益超过 ``c2_min_gain_chars`` 才再次压缩。
	- x_prev 用上一轮实际发送的投影（不是未压缩的 keep 投影），过渡 miss 只记一次。
	"""
	from memory.simulator.cache_model import prices_for
	from memory.simulator.cost_model import c_action_yuan
	from memory.simulator.state_model import apply as apply_action

	p = params or load_params()
	result = ReplaySession(
		session=session_id,
		path="",
		corrections=count_corrections(api_msgs),
		reverts=count_reverts(api_msgs),
		loops=tool_loop_flags(api_msgs),
		n_messages=len(api_msgs),
	)
	starts = _user_turn_indices(api_msgs)
	if not starts:
		starts = [0] if api_msgs else []
	compact_cursor = max(0, int(cursor))
	c2_active = bool(compact_cursor)
	summary_text = ""
	x_prev = ""
	turns_since_c2 = 0
	c1_frozen = 0
	# 压缩态投影 = 冻结摘要 + 右段（按 c1_frozen 相对偏移冻结中间 tool_result），
	# 与 runtime.apply_c2_messages 一致：防止「压完即回血」（缺口②）。

	def mk_eff() -> list[dict]:
		from engine.compact import project as _proj_c0c1

		rel = max(0, c1_frozen - compact_cursor)
		tail = _proj_c0c1(api_msgs[compact_cursor:end], frozen_until=rel)
		return [_summary_msg(summary_text)] + tail

	for t, start in enumerate(starts):
		end = starts[t + 1] if t + 1 < len(starts) else len(api_msgs)
		prefix = api_msgs[:end]
		if len(prefix) < 1:
			continue
		if c2_active:
			eff = mk_eff()
			state = state_from_messages(eff, cursor=1, system=DEFAULT_SYSTEM)
		else:
			eff = prefix
			state = state_from_messages(prefix, cursor=0, system=DEFAULT_SYSTEM)
		cache = CacheState(
			provider=p.provider,
			age_seconds=0.0,
			model=p.model,
			slot=p.price_slot,
			ts=p.default_ts,
			x_prev=x_prev,
		)
		dec = decide(
			state,
			cache,
			remaining_turns=estimate_remaining(prefix),
			params=p,
			forecast="p0",
		)
		action = dec.a_star if dec.a_star in ("keep", "C1", "C2") else "keep"
		cooling = (not dec.hardtop) and turns_since_c2 < p.min_middle_edit_gap
		sent_state = state
		charged = action in ("C1", "C2")
		if action == "C2" and cooling:
			action = "keep"
			charged = False
		if action == "C2":
			new_cursor = max(compact_cursor, _c2_cut(api_msgs, end))
			if new_cursor <= compact_cursor:
				action = "keep"
				charged = False
			elif compact_cursor > 0 and summary_text:
				# 已压缩态：append-only 扩展冻结摘要（与 runtime 一致），不重写旧文本
				from types import SimpleNamespace as _NS

				from memory.runtime import try_extend_c2

				w = _NS(
					compact_cursor=compact_cursor,
					c2_summary_text=summary_text,
					c1_frozen_until=c1_frozen,
					turns_since_c2=turns_since_c2,
					session_id="",
				)
				# HardTop（缺口①）：必要性强制扩展，绕过经济闸，防止窗口溢出
				if try_extend_c2(w, api_msgs, new_cursor, p, estimate_remaining(prefix), force=bool(dec.hardtop)):
					compact_cursor = w.compact_cursor
					summary_text = w.c2_summary_text
					turns_since_c2 = w.turns_since_c2
					c1_frozen = w.c1_frozen_until
					c2_active = True
					eff = mk_eff()
					sent_state = state_from_messages(eff, cursor=1, system=DEFAULT_SYSTEM)
				else:
					action = "keep"
					charged = False
			else:
				# 首次压缩：既有收益门
				region = api_msgs[compact_cursor:new_cursor]
				try:
					from memory.runtime import deterministic_c2_summary
				except Exception:
					deterministic_c2_summary = lambda msgs: f"[C2] compacted {len(msgs)} messages"
				new_summary = deterministic_c2_summary(api_msgs[:new_cursor])
				gain = _region_chars(region) - len(new_summary)
				ratio_ok = True
				if p.c2_min_save_ratio:
					full_chars = _region_chars(api_msgs[:end])
					if full_chars > 0:
						compact_chars = len(new_summary) + _region_chars(api_msgs[new_cursor:end])
						if compact_chars / full_chars > 1.0 - max(0.0, float(p.c2_min_save_ratio)):
							ratio_ok = False
				if (gain >= p.c2_min_gain_chars and ratio_ok) or dec.hardtop:
					compact_cursor = new_cursor
					c2_active = True
					summary_text = new_summary
					turns_since_c2 = 0
					c1_frozen = new_cursor
					eff = mk_eff()
					sent_state = state_from_messages(eff, cursor=1, system=DEFAULT_SYSTEM)
				else:
					action = "keep"
					charged = False
		elif getattr(p, "c2_extend_decouple", False) and c2_active:
			# 解耦扩展：已压缩态不再等 decide 返回 C2，append 四闸门满足即可扩展（与 runtime 一致）
			from types import SimpleNamespace as _NS

			from memory.runtime import try_extend_c2

			new_cursor = max(compact_cursor, _c2_cut(api_msgs, end))
			w = _NS(
				compact_cursor=compact_cursor,
				c2_summary_text=summary_text,
				c1_frozen_until=c1_frozen,
				turns_since_c2=turns_since_c2,
				session_id="",
			)
			if new_cursor > compact_cursor and try_extend_c2(w, api_msgs, new_cursor, p, estimate_remaining(prefix)):
				compact_cursor = w.compact_cursor
				summary_text = w.c2_summary_text
				turns_since_c2 = w.turns_since_c2
				c1_frozen = w.c1_frozen_until
				c2_active = True
				action = "C2"
				charged = True
				eff = mk_eff()
				sent_state = state_from_messages(eff, cursor=1, system=DEFAULT_SYSTEM)
			else:
				action = "keep"
				charged = False
		elif action == "C1":
			if not c2_active:
				sent_state = apply_action("C1", state, p)
			else:
				# 压缩态 C1：不移动 cursor，仅推进冻结边界、原地占位中间 tool_result
				# （与 runtime.send("C1") → apply_c2_messages(frozen_until) 一致）
				from engine.compact import KEEP_TAIL_MESSAGES as _KTP

				c1_frozen = max(c1_frozen, end - _KTP)
				eff = mk_eff()
				sent_state = state_from_messages(eff, cursor=1, system=DEFAULT_SYSTEM)
		_s_a, shot = shot_cost(sent_state, "keep", cache, p, charge_action=False)
		act_cost = 0.0
		if charged:
			act_cost = c_action_yuan(action, state, sent_state, prices_for(cache, p), p)
		b_tok = baseline_tokens(prefix)
		result.turns.append(
			ReplayTurn(
				session=session_id,
				turn=t,
				predicted=action,
				a4=dec.a4,
				a8=dec.a8,
				a16=dec.a16,
				hardtop=dec.hardtop,
				baseline_tokens=b_tok,
				v61_tokens=shot.L,
				predicted_hit=shot.H,
				simulated_cost=shot.c_biz + act_cost,
				Q=shot.Q,
				D=shot.D,
				L=shot.L,
				G_beta=dec.G_beta,
			)
		)
		x_prev = shot.x
		turns_since_c2 += 1
	return result


def replay_path(path: Path, params: Params | None = None) -> ReplaySession:
	rows = load_jsonl(path)
	api = [_as_api_message(r) for r in rows]
	rs = replay_messages(api, session_id=path.stem, params=params)
	rs.path = str(path)
	# TTL：按连续用户消息时间戳计龄
	times = [r.get("ts") for r in rows if isinstance(r.get("ts"), (int, float))]
	return rs


def iter_session_files(root: Path | None = None) -> list[Path]:
	d = root or default_sessions_dir()
	if not d.is_dir():
		return []
	return sorted(d.glob("*.jsonl"))


def replay_all(
	root: Path | None = None,
	params: Params | None = None,
	limit: int | None = None,
) -> list[ReplaySession]:
	files = iter_session_files(root)
	if limit is not None:
		files = files[:limit]
	return [replay_path(p, params) for p in files]
