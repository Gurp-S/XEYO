"""WSC 扩展的旁路经济测量：同一历史上的 keep/fold 投影，而非 C2 摘要。

候选只复制当前冷层与组装状态；Read 路径及行号沿用生产布局，取回视图不落盘。
UTF-8 字节/4 是本地估参口径，不是厂商 tokenizer 或实付账单。
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass

from memory.token import token_len

ENV = "XEYO_WSC_EXTENSION_ECONOMICS"
BASIS = "wsc_projected_json_utf8_quarters"


def enabled() -> bool:
	from memory.memory_switches import env_flag

	return env_flag(ENV)


def absorb_boundary(messages: list[dict], cursor: int) -> int:
	"""发射与候选共用一个 pair-safe 上界。"""
	from engine.compact import keep_tail_cut
	from memory.runtime import pair_safe_cut

	upper = min(len(messages), max(int(keep_tail_cut(messages)), int(cursor)))
	try:
		pair_safe = int(pair_safe_cut(messages, upper))
		if 1 < pair_safe < upper:
			upper = pair_safe
	except Exception:
		logging.getLogger(__name__).debug("candidate boundary unavailable", exc_info=True)
	return upper


@dataclass(frozen=True)
class ExtensionEconomics:
	keep_tokens: int
	fold_tokens: int
	shared_tokens: int

	@property
	def saved_tokens(self) -> int:
		return self.keep_tokens - self.fold_tokens

	@property
	def transition_tokens(self) -> int:
		return max(0, self.fold_tokens - self.shared_tokens)

	def account(self) -> dict:
		return {
			"economics_basis": BASIS,
			"projection_keep_tokens": self.keep_tokens,
			"projection_fold_tokens": self.fold_tokens,
			"projection_shared_tokens": self.shared_tokens,
			"projection_saved_tokens": self.saved_tokens,
			"projection_transition_tokens": self.transition_tokens,
		}


def compare(keep: list[dict], fold: list[dict]) -> ExtensionEconomics:
	"""同一点的完整历史投影，包含工具参数，保留负收益。"""
	def canon(messages):
		return json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

	a, b = canon(keep), canon(fold)
	lo, hi = 0, min(len(a), len(b))
	while lo < hi:
		mid = (lo + hi + 1) // 2
		if a[:mid] == b[:mid]:
			lo = mid
		else:
			hi = mid - 1
	return ExtensionEconomics(token_len(a), token_len(b), token_len(a[:lo]))


def measure(messages: list[dict], working, new_cursor: int, *, cwd=None):
	"""不改活状态或生产冷层视图；未有冻结头/测量失败返回 None 并由调用方记账。"""
	from memory import wsc_projection as wp
	from memory.offload import ref_path_for
	from synaptic.project import project
	from synaptic.replay import _region_raw_tokens

	try:
		session = str(getattr(working, "session_id", "") or "-")
		cursor = int(getattr(working, "compact_cursor", 0) or 0)
		cached = wp._STATE.get(wp._state_key(session, cwd))
		if cached is None:
			cached = wp._restore_frozen(session, cursor, messages, cwd)
		if cached is None or not cached.head or cached.cursor != cursor:
			return None
		# 实际发射会在历史回滚时丢弃冻结态；此时旧头的候选不代表下一次发射。
		if len(messages) < cached.n_messages:
			return None
		from memory import wsc_head_store
		from memory.wsc_source_layout import LEGACY, APPEND, validate
		layout = validate(getattr(working, "compression_source_layout", LEGACY))
		if cached.source_seal and cached.source_seal != wsc_head_store.region_seal(messages, cached.region_end, source_layout=layout):
			return None
		if not wp._junction_intact(messages, cached.region_end):
			return None
		upper = absorb_boundary(messages, new_cursor)
		if upper <= cached.region_end:
			return None
		pinned = wp._pinned(cached, cwd)
		from memory.wsc_continuation import resume_inputs
		params = wp.production_params()
		path = cached.view_path or wp._view_path_for(wp._cwd_of(cwd), session)
		previous, cold, path = resume_inputs(cached, path, mode=params.mode, level=params.level)
		candidate = project(
			messages, region_end=upper, params=params,
			prev=copy.deepcopy(previous), cold=copy.deepcopy(cold),
			session=session, region_baseline_tokens=int(_region_raw_tokens(messages[:upper])),
			view_path=path, view_ref=ref_path_for(path, wp._cwd_of(cwd) or None),
			persist_view=False,
			exclude_state_notes=layout == APPEND,
		)
		frozen = int(getattr(working, "c1_frozen_until", 0) or 0)
		keep = wp._emit(cached.head, messages, cached.region_end, frozen, cwd=pinned, view_path=cached.view_path)
		fold = (
			wp._emit(candidate.text, messages, upper, max(frozen, new_cursor), cwd=pinned, view_path=path)
			if candidate.result.compressed else keep
		)
		return compare(keep, fold)
	except Exception:
		logging.getLogger(__name__).debug("WSC extension measurement failed", exc_info=True)
		return None
