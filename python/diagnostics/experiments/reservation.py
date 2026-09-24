"""实验级统一预算与**持久预留**账本（设计 §9.1）。

产品侧 ``engine.budget.BudgetTracker`` 是单进程、单次 submit、内存态的；一个实验
跨两臂、跨重试、跨 repeat、跨进程，必须有一张落盘的账。本模块复用 BudgetTracker
的**计价语义**（厂商金额优先，否则按 usage 估算），不复用它的生命周期。

三条硬规则（写在这里是因为它们只能靠账本保证）：
  1. 两臂 + 所有重试 + 所有 repeat 共用同一个上限，任何一臂都拿不到"全额预算"。
  2. 价格未知、输入上界缺失、usage 不明的调用 ⇒ 预留不释放，也绝不按 ¥0 记。
  3. 账本写不进去 ⇒ 停止发新的付费请求（fail closed），实验不得标成成功。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from diagnostics import store
from diagnostics.identity import _s

SCHEMA = "diagnostics.reservation.v1"

#: usage 里出现这些键才认为"厂商报了用量"；全零但报了也算报了（已知量）。
_USAGE_MARKERS = (
	"prompt_tokens",
	"completion_tokens",
	"total_tokens",
	"prompt_cache_hit_tokens",
	"prompt_cache_miss_tokens",
	"completion_tokens_details",
	"cost_cny",
	"cost",
	"amount",
)

#: 写失败按**路径**记住：同一进程换了 tmp 目录不会继承上一次的坏账状态。
_LEDGER_ERRORS: set[str] = set()


class ReservationDenied(RuntimeError):
	"""预留被拒（中性事实：调用方不得发该请求）。"""


def _now() -> float:
	return round(time.time(), 3)


def _money(value: Any) -> float | None:
	try:
		n = float(value)
	except (TypeError, ValueError):
		return None
	return n if n == n else None


def _rate_table(price: Mapping[str, Any] | None) -> dict[str, float] | None:
	"""从 manifest 的 price 段取三档单价（元/百万 token）；不可得返回 None。"""
	if not isinstance(price, Mapping):
		return None
	if _s(price.get("status")) not in ("", "ok") :
		return None
	rates = price.get("rates")
	if not isinstance(rates, Mapping):
		return None
	try:
		hit = float(rates.get("hit"))
		miss = float(rates.get("miss"))
		out = float(rates.get("out"))
	except (TypeError, ValueError):
		return None
	return {"hit": max(0.0, hit), "miss": max(0.0, miss), "out": max(0.0, out)}


def price_is_known(price: Mapping[str, Any] | None) -> bool:
	return _rate_table(price) is not None


def worst_case_cny(
	price: Mapping[str, Any] | None,
	*,
	max_input_tokens: int | None,
	max_output_tokens: int | None,
	billing_class: str = "unknown",
) -> dict[str, Any]:
	"""按最坏输入 + 最大输出 + 计费类别算预留上界。

	类别未知 ⇒ 输入按**更贵的那一档**计（hit/miss 取大）：预留宁可多留。
	"""
	rates = _rate_table(price)
	if rates is None:
		return {"amount_cny": None, "reason": "unknown_price"}
	try:
		input_tokens = int(max_input_tokens) if max_input_tokens is not None else -1
	except (TypeError, ValueError):
		input_tokens = -1
	if input_tokens <= 0:
		return {"amount_cny": None, "reason": "missing_input_bound"}
	try:
		output_tokens = max(0, int(max_output_tokens or 0))
	except (TypeError, ValueError):
		output_tokens = 0
	cls = _s(billing_class).lower() or "unknown"
	if cls == "hit":
		input_rate = rates["hit"]
	elif cls == "miss":
		input_rate = rates["miss"]
	else:
		input_rate = max(rates["hit"], rates["miss"])
	amount = (input_tokens * input_rate + output_tokens * rates["out"]) / 1_000_000.0
	return {
		"amount_cny": round(amount, 8),
		"reason": "",
		"basis": {
			"max_input_tokens": input_tokens,
			"max_output_tokens": output_tokens,
			"billing_class": cls,
			"input_rate_used": input_rate,
			"output_rate_used": rates["out"],
			"currency": _s((price or {}).get("currency")) or "CNY",
		},
	}


def usage_is_reported(usage: Any) -> bool:
	"""厂商是否真的报了用量。没报 ⇒ 费用未知，不得按 ¥0 释放预留。"""
	if not isinstance(usage, Mapping) or not usage:
		return False
	return any(key in usage for key in _USAGE_MARKERS)


def priced_cny(usage: Mapping[str, Any], *, provider: str, model: str) -> dict[str, Any]:
	"""复用产品计价语义：厂商金额优先，其次按 usage 估算（不联网）。

	``local_only`` 恒真：实验记账不许为了算钱去联网拉实时价。
	"""
	from engine.budget import BudgetTracker

	tracker = BudgetTracker(provider=_s(provider) or "unknown", model=_s(model) or "")
	try:
		tracker.add_usage(dict(usage))
	except Exception as exc:  # noqa: BLE001 — 折算失败即费用未知
		return {"cny": None, "source": "", "error": f"{type(exc).__name__}: {exc}"}
	return {
		"cny": round(float(tracker.last_usage_cny), 8),
		"source": _s(tracker.last_cost_source),
		"tokens": int(tracker.last_usage_tokens),
	}


def reservations_path() -> Path:
	return store.reservations_path()


def ledger_error(path: Path | None = None) -> bool:
	return str(path or reservations_path()) in _LEDGER_ERRORS


def clear_ledger_errors() -> None:
	"""仅供测试与人工修复后复位（复位不会把已丢的账找回来）。"""
	_LEDGER_ERRORS.clear()


def read_rows(experiment_id: str = "") -> list[dict[str, Any]]:
	"""读账本（旧→新）。坏行由 ``store.read_jsonl`` 丢弃，不做补值。"""
	rows = store.read_jsonl(reservations_path(), limit=0)
	if not experiment_id:
		return [row for row in rows if _s(row.get("schema")) == SCHEMA]
	return [
		row
		for row in rows
		if _s(row.get("schema")) == SCHEMA and _s(row.get("experiment_id")) == _s(experiment_id)
	]


def summarize_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
	"""把预留流水折成当前状态：已花、在途未明、剩余、是否必须停。

	``committed`` = 已结算花费 + 未结算预留（最坏值）。未知结局的钱**始终**留在账上。
	"""
	cap: float | None = None
	price_version = ""
	currency = ""
	settled: dict[str, float] = {}
	pending: dict[str, float] = {}
	settled_keys: set[str] = set()
	unknown_usage_keys: list[str] = []
	ledger_errors = 0
	for row in rows:
		kind = _s(row.get("kind"))
		key = _s(row.get("request_key"))
		if kind == "cap":
			cap = _money(row.get("cap_cny"))
			price_version = _s(row.get("price_version"))
			currency = _s(row.get("currency"))
		elif kind == "reserve":
			pending[key] = float(_money(row.get("amount_cny")) or 0.0)
		elif kind == "settle":
			settled_keys.add(key)
			settled[key] = float(_money(row.get("spent_cny")) or 0.0)
			if not row.get("usage_seen"):
				unknown_usage_keys.append(key)
			if row.get("ledger_error"):
				ledger_errors += 1
	for key in settled_keys:
		pending.pop(key, None)
	spent = sum(settled.values())
	held = sum(pending.values())
	committed = spent + held
	remaining = None if cap is None else round(cap - committed, 8)
	return {
		"cap_cny": cap,
		"price_version": price_version,
		"currency": currency or "CNY",
		"settled_cny": round(spent, 8),
		"held_cny": round(held, 8),
		"committed_cny": round(committed, 8),
		"remaining_cny": remaining,
		"requests_reserved": len(settled_keys) + len(pending),
		"requests_settled": len(settled),
		"unknown_outcome": sorted(pending),
		"unknown_usage_keys": sorted(set(unknown_usage_keys)),
		"ledger_write_errors": ledger_errors,
		"must_stop": bool(cap is not None and committed >= cap),
	}


def state_of(experiment_id: str) -> dict[str, Any]:
	"""重启后读已落盘状态即得全貌（含未知请求清单，绝不盲目重发）。"""
	state = summarize_rows(read_rows(experiment_id))
	state["experiment_id"] = _s(experiment_id)
	state["ledger_unwritable"] = ledger_error()
	state["ledger_locator"] = str(reservations_path())
	return state


class Ledger:
	"""一个实验的预留账本句柄：上限一次、逐请求预留、完成后对账。"""

	def __init__(
		self,
		experiment_id: str,
		*,
		cap_cny: float | None = None,
		price: Mapping[str, Any] | None = None,
		provider: str = "",
		model: str = "",
		max_requests: int | None = None,
	) -> None:
		self.experiment_id = _s(experiment_id)
		self.cap_cny = _money(cap_cny)
		self.price = dict(price or {})
		self.provider = _s(provider)
		self.model = _s(model)
		self.max_requests = None if max_requests is None else int(max_requests)
		self.path = reservations_path()

	# ---------- 写入 ----------

	def _append(self, row: dict[str, Any]) -> dict[str, Any]:
		"""写一行；失败即置坏账标记并向上返回拒绝原因（fail closed）。"""
		payload = {"schema": SCHEMA, "ts": _now(), **row}
		try:
			store.append_jsonl(self.path, payload)
		except OSError as exc:
			_LEDGER_ERRORS.add(str(self.path))
			return {
				"allowed": False,
				"reason": "ledger_unwritable",
				"error": f"{type(exc).__name__}: {exc}",
				"row": payload,
			}
		return {"allowed": True, "row": payload}

	# ---------- 上限 ----------

	def open(self) -> dict[str, Any]:
		"""登记该实验的统一上限（两臂/重试/repeat 共用）。重复登记只读回，不改口。"""
		existing = [row for row in read_rows(self.experiment_id) if _s(row.get("kind")) == "cap"]
		if existing:
			last = existing[-1]
			if self.cap_cny is not None and _money(last.get("cap_cny")) != self.cap_cny:
				return {
					"allowed": False,
					"reason": "cap_immutable",
					"recorded_cap_cny": _money(last.get("cap_cny")),
					"requested_cap_cny": self.cap_cny,
				}
			return {"allowed": True, "reason": "cap_already_open", "state": self.state()}
		if ledger_error(self.path):
			return {"allowed": False, "reason": "ledger_unwritable"}
		res = self._append(
			{
				"kind": "cap",
				"experiment_id": self.experiment_id,
				"cap_cny": self.cap_cny,
				"currency": _s(self.price.get("currency")) or "CNY",
				"price_version": _s(self.price.get("price_version")),
				"price_status": _s(self.price.get("status")) or "unknown",
				"cap_scope": "experiment_total",
			}
		)
		if not res.get("allowed"):
			return res
		return {"allowed": True, "reason": "", "state": self.state()}

	# ---------- 预留 / 对账 ----------

	def may_send(self, request_key: str) -> dict[str, Any]:
		"""这个请求键是否允许发出：已预留未结算 ⇒ 结局未知，不得重发。

		行是旧→新，所以取**最后一条**同键记录判断，而不是见到预留就下结论：
		结算过的键允许一次"已知的重试"，未结算的键才是崩溃后不该重发的未知结局。
		"""
		key = _s(request_key)
		last: dict[str, Any] | None = None
		for row in read_rows(self.experiment_id):
			if _s(row.get("request_key")) != key:
				continue
			if _s(row.get("kind")) in ("reserve", "settle"):
				last = row
		if last is None:
			return {"allowed": True, "reason": "never_sent", "request_key": key}
		if _s(last.get("kind")) == "settle":
			return {"allowed": True, "reason": "already_settled", "request_key": key}
		return {
			"allowed": False,
			"reason": "outcome_unknown",
			"request_key": key,
			"held_cny": _money(last.get("amount_cny")),
		}

	def reserve(
		self,
		request_key: str,
		*,
		max_input_tokens: int | None,
		max_output_tokens: int | None = None,
		billing_class: str = "unknown",
		arm: str = "",
		attempt: int | None = None,
	) -> dict[str, Any]:
		"""请求发出前按最坏情况预留。任何一环不确定 ⇒ 拒绝发出。"""
		key = _s(request_key)
		if not key:
			return {"allowed": False, "reason": "missing_request_key"}
		if ledger_error(self.path):
			return {"allowed": False, "reason": "ledger_unwritable"}
		state = self.state()
		if state["cap_cny"] is None:
			return {"allowed": False, "reason": "cap_missing", "state": state}
		if self.max_requests is not None and state["requests_reserved"] >= int(self.max_requests):
			return {
				"allowed": False,
				"reason": "max_requests_reached",
				"max_requests": int(self.max_requests),
				"state": state,
			}
		worst = worst_case_cny(
			self.price,
			max_input_tokens=max_input_tokens,
			max_output_tokens=max_output_tokens,
			billing_class=billing_class,
		)
		if worst["amount_cny"] is None:
			return {"allowed": False, "reason": worst["reason"], "state": state}
		amount = float(worst["amount_cny"])
		if amount <= 0:
			# 上界算出 0 元：要么价目为 0 要么输入上界为 0，都不构成可信上界。
			return {"allowed": False, "reason": "unbounded_worst_case", "state": state}
		remaining = state["remaining_cny"]
		if remaining is None or amount > remaining:
			return {
				"allowed": False,
				"reason": "budget_exhausted",
				"amount_cny": amount,
				"remaining_cny": remaining,
				"state": state,
			}
		gate = self.may_send(key)
		if not gate.get("allowed"):
			return {**gate, "state": state}
		res = self._append(
			{
				"kind": "reserve",
				"experiment_id": self.experiment_id,
				"request_key": key,
				"arm": _s(arm),
				"attempt": attempt,
				"amount_cny": amount,
				"basis": worst.get("basis") or {},
			}
		)
		if not res.get("allowed"):
			return {**res, "state": self.state()}
		return {
			"allowed": True,
			"reason": "",
			"request_key": key,
			"reserved_cny": amount,
			"state": self.state(),
		}

	def reconcile(
		self,
		request_key: str,
		usage: Any,
		*,
		provider: str = "",
		model: str = "",
		outcome: str = "",
	) -> dict[str, Any]:
		"""完成后对账：有用量 ⇒ 释放多留的部分；无用量 ⇒ 全额保留。

		``outcome`` 为 ``cancelled`` / ``timeout`` 时即使拿到部分 usage 也按保留最大
		处理——取消与超时都可能仍在计费，钱不能提前放回池子。
		"""
		key = _s(request_key)
		state = self.state()
		reserved = next(
			(
				float(_money(row.get("amount_cny")) or 0.0)
				for row in read_rows(self.experiment_id)
				if _s(row.get("kind")) == "reserve" and _s(row.get("request_key")) == key
			),
			None,
		)
		held = key in set(state["unknown_outcome"])
		if reserved is None and held:
			reserved = 0.0
		stop_like = _s(outcome).lower() in ("cancelled", "cancel", "timeout", "aborted")
		spent: float | None = None
		reported = usage_is_reported(usage)
		# 取消/超时即使拿到部分 usage 也不能用于对账：这条账的"用量是否可信"就是 False。
		usage_seen = bool(reported and not stop_like)
		source = ""
		if usage_seen:
			priced = priced_cny(
				usage,
				provider=provider or self.provider,
				model=model or self.model,
			)
			spent = priced.get("cny")
			source = _s(priced.get("source"))
			if spent is None:
				usage_seen = False
		if stop_like:
			source = "kept_max_reservation"
		if spent is None:
			# 未知用量 / 取消超时：保留该次最大预留，绝不释放成 0。
			spent = float(reserved or 0.0)
		spent = round(max(0.0, spent), 8)
		released = round(max(0.0, float(reserved or 0.0) - spent), 8)
		row: dict[str, Any] = {
			"kind": "settle",
			"experiment_id": self.experiment_id,
			"request_key": key,
			"spent_cny": spent,
			"released_cny": released,
			"reserved_cny": reserved,
			"usage_seen": bool(usage_seen),
			"usage_reported": bool(reported),
			"cost_source": source or ("estimate" if usage_seen else "unknown"),
			"cost_basis": "按 usage 估算（非账单实付）",
		}
		if stop_like:
			row["outcome"] = _s(outcome).lower()
			row["kept_max_reservation"] = True
		if reserved is None:
			row["unbooked"] = True
		res = self._append(row)
		if not res.get("allowed"):
			return {**res, "state": self.state()}
		new_state = self.state()
		return {
			"allowed": True,
			"reason": "settled_without_reservation" if reserved is None else "",
			"request_key": key,
			"spent_cny": spent,
			"released_cny": released,
			"usage_seen": bool(usage_seen),
			"usage_reported": bool(reported),
			"overrun_cny": round(
				max(0.0, new_state["committed_cny"] - float(new_state["cap_cny"] or 0.0)), 8
			)
			if new_state["cap_cny"] is not None
			else 0.0,
			"state": new_state,
		}

	def abandon(self, request_key: str, *, reason: str = "") -> dict[str, Any]:
		"""请求结果未知（进程丢了/超时未回）：按该次最大预留入账并保留在账上。"""
		return self.reconcile(request_key, None, outcome=_s(reason) or "unknown")

	# ---------- 读取 ----------

	def state(self) -> dict[str, Any]:
		state = state_of(self.experiment_id)
		if self.cap_cny is not None and state["cap_cny"] is None:
			state["cap_cny"] = self.cap_cny
			state["remaining_cny"] = round(self.cap_cny - state["committed_cny"], 8)
		return state


__all__ = [
	"Ledger",
	"ReservationDenied",
	"SCHEMA",
	"clear_ledger_errors",
	"ledger_error",
	"priced_cny",
	"read_rows",
	"reservations_path",
	"state_of",
	"summarize_rows",
	"usage_is_reported",
	"worst_case_cny",
]
