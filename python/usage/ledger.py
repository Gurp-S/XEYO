"""用量事件 JSONL：追加写入、按日聚合。"""

from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from usage.pricing import BJ, estimate_cny, official_cost_cny, split_usage

_lock = threading.Lock()
_MAX_LINES = 80_000
_events_cache: tuple[str, float, int, list[dict[str, Any]]] | None = None


def usage_dir() -> Path:
	override = os.environ.get("XEYO_USAGE_DIR", "").strip()
	if override:
		return Path(override).expanduser()
	return Path.home() / ".xeyo" / "usage"


def events_path() -> Path:
	return usage_dir() / "events.jsonl"


def key_fingerprint(api_key: str) -> str:
	s = "".join(c for c in (api_key or "").strip() if c.isalnum())
	if len(s) < 4:
		return "…"
	return f"…{s[-4:]}"


def _as_int(v: Any) -> int:
	try:
		return max(0, int(v or 0))
	except (TypeError, ValueError):
		return 0


def record_from_openai_usage(
	*,
	provider: str,
	model: str,
	api_key: str,
	usage: dict[str, Any],
	ts: float | None = None,
	session_id: str = "",
) -> None:
	if not isinstance(usage, dict) or not usage:
		return
	now = float(ts if ts is not None else datetime.now(tz=BJ).timestamp())
	hit, miss, out = split_usage(usage)
	prompt = _as_int(usage.get("prompt_tokens"))
	official_total = _as_int(usage.get("total_tokens"))
	tokens = official_total if official_total > 0 else (
		prompt + out if prompt or out else hit + miss + out
	)
	if tokens <= 0 and hit + miss + out <= 0:
		tokens = 0
	api_cost = official_cost_cny(usage)
	if api_cost is not None:
		cost_cny = api_cost
		cost_source = "api"
	else:
		cost_cny = estimate_cny(
			provider=provider, model=model, usage=usage, ts=now
		)
		cost_source = "estimate"
	event = {
		"ts": now,
		"day": datetime.fromtimestamp(now, tz=BJ).date().isoformat(),
		"provider": (provider or "unknown").lower(),
		"model": model or "unknown",
		"session_id": (session_id or "").strip(),
		"key_fp": key_fingerprint(api_key),
		"prompt_tokens": prompt,
		"completion_tokens": out,
		"cache_hit": hit,
		"cache_miss": miss,
		"output": out,
		"tokens": tokens,
		"cost_cny": round(float(cost_cny), 8),
		"cost_source": cost_source,
	}
	_append(event)


def _append(event: dict[str, Any]) -> None:
	path = events_path()
	line = json.dumps(event, ensure_ascii=False) + "\n"
	with _lock:
		path.parent.mkdir(parents=True, exist_ok=True)
		with path.open("a", encoding="utf-8") as f:
			f.write(line)


def _read_events() -> list[dict[str, Any]]:
	global _events_cache
	path = events_path()
	if not path.is_file():
		_events_cache = None
		return []
	try:
		st = path.stat()
	except OSError:
		return []
	cache_key = (str(path.resolve()), st.st_mtime, st.st_size)
	cached = _events_cache
	if cached is not None and cached[0] == cache_key[0] and cached[1] == cache_key[1] and cached[2] == cache_key[2]:
		return cached[3]
	out: list[dict[str, Any]] = []
	try:
		raw = path.read_text(encoding="utf-8")
	except OSError:
		return []
	for i, line in enumerate(raw.splitlines()):
		if i >= _MAX_LINES:
			break
		line = line.strip()
		if not line:
			continue
		try:
			row = json.loads(line)
		except json.JSONDecodeError:
			continue
		if isinstance(row, dict):
			out.append(row)
	_events_cache = (cache_key[0], cache_key[1], cache_key[2], out)
	return out


def _day_list(days: int, *, end: date | None = None) -> list[str]:
	span = max(1, min(366, int(days)))
	last = end or datetime.now(tz=BJ).date()
	start = last - timedelta(days=span - 1)
	cur = start
	out: list[str] = []
	while cur <= last:
		out.append(cur.isoformat())
		cur += timedelta(days=1)
	return out


def _empty_bucket() -> dict[str, float | int]:
	return {
		"cost": 0.0,
		"requests": 0,
		"tokens": 0,
		"cache_hit": 0,
		"cache_miss": 0,
		"output": 0,
	}


def _add(bucket: dict[str, float | int], ev: dict[str, Any]) -> None:
	bucket["cost"] = float(bucket["cost"]) + float(ev.get("cost_cny") or 0)
	bucket["requests"] = int(bucket["requests"]) + 1
	bucket["tokens"] = int(bucket["tokens"]) + _as_int(ev.get("tokens"))
	bucket["cache_hit"] = int(bucket["cache_hit"]) + _as_int(ev.get("cache_hit"))
	bucket["cache_miss"] = int(bucket["cache_miss"]) + _as_int(ev.get("cache_miss"))
	bucket["output"] = int(bucket["output"]) + _as_int(ev.get("output"))


def _series_from(
	days: list[str],
	by_day: dict[str, dict[str, float | int]],
) -> list[dict[str, Any]]:
	out: list[dict[str, Any]] = []
	for d in days:
		b = by_day.get(d) or _empty_bucket()
		out.append(
			{
				"day": d,
				"cost": round(float(b["cost"]), 6),
				"requests": int(b["requests"]),
				"tokens": int(b["tokens"]),
				"cache_hit": int(b["cache_hit"]),
				"cache_miss": int(b["cache_miss"]),
				"output": int(b["output"]),
			}
		)
	return out


def query_usage(
	*,
	days: int = 30,
	model: str | None = None,
	provider: str | None = None,
	key_fp: str | None = None,
) -> dict[str, Any]:
	day_ids = _day_list(days)
	day_set = set(day_ids)
	want_model = (model or "").strip()
	want_provider = (provider or "").strip().lower()
	want_key = (key_fp or "").strip()

	events = _read_events()
	filtered: list[dict[str, Any]] = []
	keys: set[str] = set()
	lifetime_cost = 0.0
	cost_from_api = 0
	cost_from_estimate = 0
	for ev in events:
		fp = str(ev.get("key_fp") or "")
		if fp and fp != "…":
			keys.add(fp)
		lifetime_cost += float(ev.get("cost_cny") or 0)
		if ev.get("day") not in day_set:
			continue
		if want_model and str(ev.get("model") or "") != want_model:
			continue
		if want_provider and str(ev.get("provider") or "").lower() != want_provider:
			continue
		if want_key and fp != want_key:
			continue
		filtered.append(ev)
		if str(ev.get("cost_source") or "") == "api":
			cost_from_api += 1
		else:
			cost_from_estimate += 1

	totals = _empty_bucket()
	by_day: dict[str, dict[str, float | int]] = {}
	# (provider, model) -> {day -> bucket}
	by_model: dict[tuple[str, str], dict[str, dict[str, float | int]]] = {}
	model_totals: dict[tuple[str, str], dict[str, float | int]] = {}

	for ev in filtered:
		_add(totals, ev)
		d = str(ev.get("day") or "")
		by_day.setdefault(d, _empty_bucket())
		_add(by_day[d], ev)
		key = (str(ev.get("provider") or "unknown"), str(ev.get("model") or "unknown"))
		model_totals.setdefault(key, _empty_bucket())
		_add(model_totals[key], ev)
		slot = by_model.setdefault(key, {})
		slot.setdefault(d, _empty_bucket())
		_add(slot[d], ev)

	models: list[dict[str, Any]] = []
	for (prov, mid), tot in sorted(
		model_totals.items(),
		key=lambda kv: (-int(kv[1]["requests"]), kv[0][0], kv[0][1]),
	):
		models.append(
			{
				"provider": prov,
				"model": mid,
				"requests": int(tot["requests"]),
				"tokens": int(tot["tokens"]),
				"cost": round(float(tot["cost"]), 6),
				"series": _series_from(day_ids, by_model.get((prov, mid), {})),
			}
		)

	return {
		"days": day_ids,
		"totals": {
			"cost": round(float(totals["cost"]), 6),
			"requests": int(totals["requests"]),
			"tokens": int(totals["tokens"]),
		},
		"lifetime_cost": round(lifetime_cost, 6),
		"cost_source": "api" if cost_from_api and not cost_from_estimate else (
			"mixed" if cost_from_api else "estimate"
		),
		"series": _series_from(day_ids, by_day),
		"models": models,
		"keys": sorted(keys),
	}


def c2_events_path() -> Path:
	"""C2 触发事件独立文件，避免污染 token 用量 ledger。"""
	return usage_dir() / "c2_events.jsonl"


def record_c2_event(*, session_id: str = "", cursor: int = 0) -> None:
	"""记录一次实际生效的 C2 压缩（供 C4 每日监控统计 C2 次数）。"""
	now = datetime.now(tz=BJ).timestamp()
	event = {
		"ts": now,
		"day": datetime.fromtimestamp(now, tz=BJ).date().isoformat(),
		"type": "c2",
		"session_id": str(session_id or ""),
		"cursor": _as_int(cursor),
	}
	path = c2_events_path()
	with _lock:
		path.parent.mkdir(parents=True, exist_ok=True)
		with path.open("a", encoding="utf-8") as f:
			f.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_c2_events() -> list[dict[str, Any]]:
	"""读取全部 C2 触发事件。"""
	path = c2_events_path()
	if not path.is_file():
		return []
	out: list[dict[str, Any]] = []
	for line in path.read_text(encoding="utf-8").splitlines():
		if not line.strip():
			continue
		try:
			row = json.loads(line)
		except json.JSONDecodeError:
			continue
		if isinstance(row, dict):
			out.append(row)
	return out


def calibration_events_path() -> Path:
	"""逐枪校准观测独立文件：LCP / action / predicted vs observed hit，喂 scan_rho。

	与 token 用量 ledger 分开，避免污染计费统计；由 memory/observe.py 写、
	memory/simulator/calibration.py 读回 HitRecord。
	"""
	return usage_dir() / "calibration_events.jsonl"


def record_calibration_shot(
	*,
	ts: float | None = None,
	session_id: str = "",
	request_id: str = "",
	provider: str = "deepseek",
	model: str = "deepseek-v4-flash",
	action: str = "keep",
	cache_age: float = 0.0,
	lcp: int = 0,
	predicted_hit: float = 0.0,
	observed_hit: float = 0.0,
	prompt_tokens: int = 0,
	output_tokens: int = 0,
	context_length: int = 0,
	conversation_length: int = 0,
	tool_result_size: int = 0,
) -> None:
	"""追加一条逐枪校准观测（热路径可选；失败不阻塞）。"""
	now = float(ts if ts is not None else datetime.now(tz=BJ).timestamp())
	event = {
		"ts": now,
		"day": datetime.fromtimestamp(now, tz=BJ).date().isoformat(),
		"session_id": str(session_id or ""),
		"request_id": str(request_id or ""),
		"provider": (provider or "deepseek").lower(),
		"model": model or "deepseek-v4-flash",
		"action": str(action or "keep"),
		"cache_age": max(0.0, float(cache_age)),
		"LCP": _as_int(lcp),
		"predicted_hit": round(max(0.0, float(predicted_hit)), 3),
		"observed_hit": max(0.0, float(observed_hit)),
		"prompt_tokens": _as_int(prompt_tokens),
		"output_tokens": _as_int(output_tokens),
		"context_length": _as_int(context_length),
		"conversation_length": _as_int(conversation_length),
		"tool_result_size": _as_int(tool_result_size),
	}
	path = calibration_events_path()
	with _lock:
		path.parent.mkdir(parents=True, exist_ok=True)
		with path.open("a", encoding="utf-8") as f:
			f.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_calibration_events() -> list[dict[str, Any]]:
	"""读取全部逐枪校准观测。"""
	path = calibration_events_path()
	if not path.is_file():
		return []
	out: list[dict[str, Any]] = []
	try:
		raw = path.read_text(encoding="utf-8")
	except OSError:
		return []
	for line in raw.splitlines():
		if not line.strip():
			continue
		try:
			row = json.loads(line)
		except json.JSONDecodeError:
			continue
		if isinstance(row, dict):
			out.append(row)
	return out
