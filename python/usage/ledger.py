"""用量事件 JSONL：追加写入、按日聚合。"""

from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from usage.attribution import canonical_vendor, event_vendor
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
	base_url: str | None = None,
	request_id: str = "",
	attempt: int = 1,
	kind: str = "turn",
	cache_write: int | None = None,
	reasoning_tokens: int | None = None,
) -> None:
	"""追加一笔用量事件。

	``provider`` = 接入通道（deepseek/openai preset 等），保持「通道」语义不变；
	事件同时写 ``vendor``（模型真实厂商，见 usage.attribution），统计 / 计价 / 分组
	一律按 vendor —— 修 P0-1（provider 与模型错位导致套错价目与分组错乱）。

	对齐 DeepSeek Harness 记账纪律（v4 设计，S2/S4）：
	- ``request_id``：逻辑模型调用唯一 id（engine 在每个请求前生成，跨 attempt 不变）。
	  **只在 request_id 非空时**才把 request_id/attempt/kind 写进行——其余调用点
	  （CLI/评测/无 meta 场景）保持旧行结构，零扰动。
	- ``attempt``：同一逻辑调用的第几次尝试（dsh S4：重试 attempt 各自入账——
	  provider 对每次 HTTP 请求独立计费，死 attempt 若真的烧了 token 就该留下）。
	- ``kind``：回合类型。``turn`` 主循环；``compact_summary`` C2 LLM 摘要旁路
	  （dsh D-3 教训：压缩走模型的调用必须可归因、不得静默消失）。
	- 每个 ``stream()`` 内的双写防御由模型适配器 ``_usage_recorded_this_stream``
	  布尔完成（同一次尝试只记一次 = dsh S2 的流内单结算）。
	"""
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
	vendor = canonical_vendor(model=model, provider=provider, base_url=base_url)
	api_cost = official_cost_cny(usage)
	if api_cost is not None:
		cost_cny = api_cost
		cost_source = "api"
	else:
		# 计价按真实厂商(vendor)，而不是接入通道 —— 错位通道不再套错档。
		cost_cny = estimate_cny(
			provider=vendor, model=model, usage=usage, ts=now
		)
		cost_source = "estimate"
	event: dict[str, Any] = {
		"ts": now,
		"day": datetime.fromtimestamp(now, tz=BJ).date().isoformat(),
		"provider": (provider or "unknown").lower(),
		"vendor": vendor,
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
	rid = (request_id or "").strip()
	if rid:
		# schema v2 记账键（B0.5）：请求归因 + retry 可观测 + 会话/请求下钻。
		event["request_id"] = rid
		event["attempt"] = max(1, int(attempt or 1))
		event["kind"] = (kind or "turn").strip() or "turn"
		cw = _as_int(cache_write)
		if cw > 0:
			# dsh S1 四桶兜底：DeepSeek 通道恒 0（无 cache write），保留字段对齐跨厂。
			event["cache_write"] = cw
		rt = _as_int(reasoning_tokens)
		if rt > 0:
			# reasoning 归 output 子分类，只作诊断字段、不参与 output 求和（dsh S1）。
			event["reasoning_tokens"] = rt
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


def _hit_rate(hit: Any, miss: Any) -> float | None:
	"""缓存命中率（官方口径）hit÷(hit+miss)，百分数一位小数；无输入时 None。

	对齐 DeepSeek Harness usage-stats 生态同一公式。命中率是健康指标（前缀稳定度），
	不是营销数字；本地界面只展示、不设阈值文案。
	"""
	h, m = _as_int(hit), _as_int(miss)
	if h + m <= 0:
		return None
	return round(h / (h + m) * 100.0, 1)


def _bucket_view(bucket: dict[str, Any]) -> dict[str, Any]:
	"""把聚合桶渲染成对外口径（v4：无金额、无吞吐大数）。

	- 三分类（hit/miss/output）分列 —— dsh S1 disjoint，禁止相加成「总消耗」；
	- input_total = hit + miss（官方 prompt_tokens 语义），唯一允许的合计；
	- hit_rate 健康指标常驻；requests = 成功结算的模型调用数（S3）。
	"""
	h = _as_int(bucket.get("cache_hit"))
	m = _as_int(bucket.get("cache_miss"))
	o = _as_int(bucket.get("output"))
	return {
		"requests": int(bucket.get("requests") or 0),
		"input_hit": h,
		"input_miss": m,
		"output": o,
		"input_total": h + m,
		"hit_rate": _hit_rate(h, m),
	}


def _empty_bucket() -> dict[str, int]:
	return {
		"requests": 0,
		"cache_hit": 0,
		"cache_miss": 0,
		"output": 0,
	}


def _add(bucket: dict[str, int], ev: dict[str, Any]) -> None:
	bucket["requests"] = int(bucket["requests"]) + 1
	bucket["cache_hit"] = int(bucket["cache_hit"]) + _as_int(ev.get("cache_hit"))
	bucket["cache_miss"] = int(bucket["cache_miss"]) + _as_int(ev.get("cache_miss"))
	bucket["output"] = int(bucket["output"]) + _as_int(ev.get("output"))


def _series_from(
	days: list[str],
	by_day: dict[str, dict[str, int]],
) -> list[dict[str, Any]]:
	out: list[dict[str, Any]] = []
	for d in days:
		b = by_day.get(d) or _empty_bucket()
		point = _bucket_view(b)
		point["day"] = d
		out.append(point)
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
	for ev in events:
		fp = str(ev.get("key_fp") or "")
		if fp and fp != "…":
			keys.add(fp)
		if want_model and str(ev.get("model") or "") != want_model:
			continue
		# 厂商过滤语义（P0-1 钉正）：仅在「纯厂商视图」（未指定 model/key）时按
		# vendor 匹配 —— 厂商已是最细维度时它=「该厂商全部用量」。一旦 model 或
		# key_fp 已把行子集唯一化，再按厂商卡会滤空错位通道的历史行（如 openai
		# 通道 key 下全是 vendor=deepseek 的 deepseek-v4-flash 行）。
		# event_vendor 对缺 vendor 字段的迁移前旧行也能现场推断，不漏滤。
		if want_provider and not want_model and not want_key and event_vendor(ev) != want_provider:
			continue
		if want_key and fp != want_key:
			continue
		if ev.get("day") not in day_set:
			continue
		filtered.append(ev)

	totals = _empty_bucket()
	by_day: dict[str, dict[str, int]] = {}
	# 结构：(provider, model) -> {day -> bucket}
	by_model: dict[tuple[str, str], dict[str, dict[str, int]]] = {}
	model_totals: dict[tuple[str, str], dict[str, int]] = {}

	for ev in filtered:
		_add(totals, ev)
		d = str(ev.get("day") or "")
		by_day.setdefault(d, _empty_bucket())
		_add(by_day[d], ev)
		# 按「真实厂商(model 归属)」分组，不再按接入通道 —— P0-1。
		key = (event_vendor(ev), str(ev.get("model") or "unknown"))
		model_totals.setdefault(key, _empty_bucket())
		_add(model_totals[key], ev)
		slot = by_model.setdefault(key, {})
		slot.setdefault(d, _empty_bucket())
		_add(slot[d], ev)

	models: list[dict[str, Any]] = []
	for (prov, mid), tot in sorted(
		model_totals.items(),
		# v4 排序：默认按「输入未命中(新增内容)」降序 —— 谁让模型读的新东西最多
		# 排最前；无金额后不再按 cost 排。命中率最低者前缀漂移最重。
		key=lambda kv: (
			-_as_int(kv[1].get("cache_miss")),
			-_as_int(kv[1].get("requests")),
			kv[0][0],
			kv[0][1],
		),
	):
		mv = _bucket_view(tot)
		mv.update(
			{
				# provider 字段携带真实厂商 id（前端分组头/厂商名映射读它）。
				"provider": prov,
				"vendor": prov,
				"model": mid,
				"series": _series_from(day_ids, by_model.get((prov, mid), {})),
			}
		)
		models.append(mv)

	return {
		"days": day_ids,
		"totals": _bucket_view(totals),
		"series": _series_from(day_ids, by_day),
		"models": models,
		"keys": sorted(keys),
		# source 由 combine 层注入（local/vendor/mixed），本地纯账本恒 local。
		"source": "local",
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
