"""按厂商 / 模型估算消费金额（人民币）。

DeepSeek V4 官方价（2026-08-17 起，元 / 百万 token）：
  高峰 09:00–12:00、14:00–18:00（北京时间）；空闲 = 高峰 × 1/2。
  flash 空闲 命中 0.05 / 未命中 1.5 / 输出 4.5；高峰 0.10 / 3.0 / 9.0
  pro   空闲 命中 0.15 / 未命中 4.5 / 输出 13.5；高峰 0.30 / 9.0 / 27.0

OpenAI 公开价按美元计，再按固定汇率折人民币，仅作看板近似。
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

BJ = timezone(timedelta(hours=8))
USD_CNY = 7.2
_M = 1_000_000.0

# (cache_hit, cache_miss, output) 元 / 百万 token
_DEEPSEEK: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {
	"flash": ((0.05, 1.5, 4.5), (0.10, 3.0, 9.0)),
	"pro": ((0.15, 4.5, 13.5), (0.30, 9.0, 27.0)),
}

# OpenAI：(input, cached_input, output) USD / 百万
_OPENAI_USD: dict[str, tuple[float, float, float]] = {
	"gpt-4o-mini": (0.15, 0.075, 0.60),
	"gpt-4o": (2.50, 1.25, 10.00),
	"gpt-4.1-mini": (0.40, 0.10, 1.60),
	"gpt-4.1": (2.00, 0.50, 8.00),
}


def is_beijing_peak(ts: float) -> bool:
	"""DeepSeek 高峰判断（北京时区）；内部走可配置的时段表。"""
	return time_tier("deepseek", ts) == "peak"

# =============================================================================
# 分时段价格（高峰 / 低峰）：只作用于「静态基价」（实时价接口 / 本地表）。
# usage 自带金额直接采用，不经过这里（见 engine.budget._usage_usd）。
# DeepSeek 官方（2026-08 起）：高峰 09:00-12:00、14:00-18:00（北京时间），
# 低峰 = 高峰 × 1/2；上游实时价与本地表都对齐「低峰」档，故 peak 倍率 2.0。
# 时段 / 倍率可用 XEYO_TIME_TIERS_JSON 整体覆盖，厂商改窗口或折扣不用发版。
# =============================================================================
_DEFAULT_TIME_TIERS: dict[str, Any] = {
	"deepseek": {
		"windows": {
			"peak": (("09:00", "12:00"), ("14:00", "18:00")),
		},
		"multipliers": {"peak": 2.0, "offpeak": 1.0},
	},
}


def _time_tiers() -> dict[str, Any]:
	"""返回时段配置：优先 XEYO_TIME_TIERS_JSON，其次内置 DeepSeek 峰谷表。"""
	raw = os.environ.get("XEYO_TIME_TIERS_JSON", "").strip()
	if raw:
		try:
			obj = json.loads(raw)
		except json.JSONDecodeError:
			obj = None
		if isinstance(obj, dict) and obj:
			return obj
	return _DEFAULT_TIME_TIERS


def _hhmm_minutes(hhmm: Any) -> int:
	try:
		h, _, m = str(hhmm).partition(":")
		return int(h) * 60 + int(m)
	except (TypeError, ValueError):
		return 0


def time_tier(provider: str, ts: float, model: str = "") -> str:
	"""provider 在 ts 时刻的时段档名；不分时 / 未知厂商一律 "offpeak"。"""
	cfg = _time_tiers().get((provider or "").lower())
	if not isinstance(cfg, dict):
		return "offpeak"
	if model:
		disabled = cfg.get("disabled_models")
		if isinstance(disabled, list) and (model or '').lower() in {
			str(m).lower() for m in disabled
		}:
			return "offpeak"
	dt = datetime.fromtimestamp(ts, tz=BJ)
	minutes = dt.hour * 60 + dt.minute
	windows = cfg.get("windows")
	if not isinstance(windows, dict):
		return "offpeak"
	for tier, spans in windows.items():
		if not isinstance(spans, (list, tuple)):
			continue
		for span in spans:
			try:
				start, end = span[0], span[1]
			except (IndexError, TypeError):
				continue
			s, e = _hhmm_minutes(start), _hhmm_minutes(end)
			if s <= e:
				if s <= minutes < e:
					return str(tier)
			elif minutes >= s or minutes < e:  # 跨零点窗口
				return str(tier)
	return "offpeak"


def effective_prices(
	provider: str,
	model: str,
	ts: float,
	base: dict[str, float] | None,
) -> dict[str, float] | None:
	"""静态基价 × 当前时段倍率。base 为 None（拿不到价格）时原样返回。"""
	if base is None:
		return None
	cfg = _time_tiers().get((provider or "").lower())
	mult = 1.0
	if isinstance(cfg, dict):
		mult = float(
			(cfg.get("multipliers") or {}).get(time_tier(provider, ts, model), 1.0)
		)
	if mult == 1.0:
		return dict(base)
	return {k: v * mult for k, v in base.items()}


def _as_int(v: Any) -> int:
	try:
		return max(0, int(v or 0))
	except (TypeError, ValueError):
		return 0


def split_usage(usage: dict[str, Any]) -> tuple[int, int, int]:
	"""返回 (cache_hit, cache_miss, output)。

	命中率口径说明：XEYO 对齐 DSH ``cacheHitPercent`` = cacheRead/(uncached+cacheRead+cacheWrite)。
	无独立 write 档的厂商（DeepSeek）由 ``miss = prompt − hit`` 把 uncached+cacheWrite 合并为
	miss，故 ``hit/(hit+miss)`` 与该公式等价（见 docs/落地前事件.md）。
	"""
	prompt = _as_int(usage.get("prompt_tokens"))
	hit = _as_int(usage.get("prompt_cache_hit_tokens"))
	miss = _as_int(usage.get("prompt_cache_miss_tokens"))
	out = _as_int(usage.get("completion_tokens"))
	details = usage.get("prompt_tokens_details")
	if isinstance(details, dict) and hit == 0:
		hit = _as_int(details.get("cached_tokens"))
	if hit + miss == 0 and prompt > 0:
		miss = max(0, prompt - hit)
		if miss == 0:
			miss = prompt
	elif hit + miss < prompt:
		miss += prompt - hit - miss
	return hit, miss, out


def _deepseek_tier(model: str) -> str:
	m = (model or "").lower()
	# smoke-test #2 修正：优先精确识别档位，flash 变体（-vision-exp 等）不再被
	# 名字子串误判；未知模型仍按子串回退（pro/reasoner → pro 档）。
	_PRO_IDS = frozenset({
		"deepseek-v4-pro",
		"deepseek-reasoner",
		"deepseek-r1",
	})
	if m in _PRO_IDS or "pro" in m or "reasoner" in m:
		return "pro"
	return "flash"


def official_cost_cny(usage: dict[str, Any]) -> float | None:
	"""若 completion usage 自带金额，原样采用（比本地价目更权威）。"""
	if not isinstance(usage, dict):
		return None
	# DeepSeek 当前通常不返回；网关或日后字段出现则直接用。
	for key in ("cost_cny", "cost", "total_cost", "amount"):
		if key not in usage or usage[key] is None:
			continue
		try:
			n = float(usage[key])
		except (TypeError, ValueError):
			continue
		if n < 0:
			continue
		currency = str(
			usage.get("currency") or usage.get("cost_currency") or ""
		).upper()
		if key in ("cost", "total_cost", "amount") and currency in ("USD", "US$"):
			return n * USD_CNY
		return n
	return None


def estimate_cny(
	*,
	provider: str,
	model: str,
	usage: dict[str, Any],
	ts: float,
	local_only: bool = True,
) -> float:
	"""折算一轮 usage 的人民币费用。

	- ``local_only=True``（默认，未设 USD 上限）：DeepSeek 用官方人民币价目（精确，
	  分时倍率），OpenAI 用本地美元价目折人民币 —— 不联网，和旧行为一致。
	- ``local_only=False``（设了 USD 上限）：走厂商实时价（aipricing.guru）链路，
	  与 ``estimate_usd`` / USD 预算同源，保证 费用(CNY) 与 预算(USD) 来自同一条价格链。
	"""
	hit, miss, out = split_usage(usage)
	prov = (provider or "").lower()
	if local_only:
		if prov == "deepseek":
			idle, peak = _DEEPSEEK[_deepseek_tier(model)]
			rates = peak if is_beijing_peak(ts) else idle
			return (hit * rates[0] + miss * rates[1] + out * rates[2]) / _M
		if prov == "openai":
			key = (model or "").lower()
			usd = _OPENAI_USD.get(key) or _OPENAI_USD["gpt-4o-mini"]
			return (miss * usd[0] + hit * usd[1] + out * usd[2]) / _M * USD_CNY
		# 未知厂商（smoke-test #2 修正）：不再一律按 DeepSeek flash 空闲价估算 ——
		# 先按机型匹配本地价目（LOCAL_PRICING_DB，USD/1M）折人民币；
		# 价目也没有时再落 _DEFAULT_USD_PRICES。全程不联网（local_only 语义）。
		price = _local_pricing(provider, model)
		price = effective_prices(provider, model, ts, price) or price
		return (
			hit * price["input_hit"] + miss * price["input_miss"] + out * price["output"]
		) / _M * USD_CNY
	# 对齐 USD 预算：实时价（厂商）→ 本地兜底 → 分时倍率 → CNY
	usd = estimate_usd(
		provider=provider,
		model=model,
		usage=usage,
		local_only=False,
		ts=ts,
	)
	return usd * USD_CNY


def unit_prices_cny_per_mtoken(
	*,
	provider: str,
	model: str,
	ts: float,
	slot: str | None = None,
) -> tuple[float, float, float, float]:
	"""返回 (p_r 命中, p_u 未命中, p_o 输出, p_w 写入) 元/百万 token。

	DeepSeek 无独立 write 档，p_w 恒为 0。
	"""
	prov = (provider or "").lower()
	forced = (slot or "").strip().lower()
	if forced in ("peak", "onpeak"):
		peak = True
	elif forced in ("offpeak", "idle", "off"):
		peak = False
	else:
		peak = is_beijing_peak(ts)
	if prov == "deepseek":
		idle, pk = _DEEPSEEK[_deepseek_tier(model)]
		rates = pk if peak else idle
		return rates[0], rates[1], rates[2], 0.0
	if prov == "openai":
		key = (model or "").lower()
		usd = _OPENAI_USD.get(key) or _OPENAI_USD["gpt-4o-mini"]
		# OpenAI: (input miss, cached hit, output)
		p_u = usd[0] * USD_CNY
		p_r = usd[1] * USD_CNY
		p_o = usd[2] * USD_CNY
		return p_r, p_u, p_o, 0.0
	# 未知厂商（smoke-test #2）：按机型匹配本地价目（USD/1M）折人民币,不再按
	# DeepSeek flash 档估算;价目缺失时落 _DEFAULT_USD_PRICES(env 可覆盖)。
	price = _local_pricing(provider, model)
	price = effective_prices(provider, model, ts, price) or price
	return price["input_hit"] * USD_CNY, price["input_miss"] * USD_CNY, price["output"] * USD_CNY, 0.0


# =========================================================================
# 实时价（L1.2 预算）：USD / 1M tokens，按用户选择的 provider / model 拉取。
# 数据源：https://www.aipricing.guru/api/pricing.json
#   {"deepseek": {"deepseek-v4-flash": {"prompt":..,"cache_prompt":..,"completion":..}}, ...}
# 拉取失败 / 模型不在表内 → 回落 LOCAL_PRICING_DB → env 覆盖 → 旧默认。
# =========================================================================

PRICING_URL = "https://www.aipricing.guru/api/pricing.json"
# 价格变动极少：默认 24h，XEYO_PRICING_TTL_HOURS 可调；价格表落盘，重启不重拉。
_PRICING_TTL_DEFAULT_HOURS = 24.0
_pricing_lock = threading.Lock()
_pricing_cache: tuple[float, dict[str, Any] | None] | None = None  # (fetched_at, data|None)
_pricing_disk_loaded = False  # 每进程只读一次磁盘缓存
_refresh_inflight = False  # 后台刷新去重；网络 IO 不在调用方线程上

# 本地兜底价（USD / 1M tokens）：{provider: {model: {input_miss,input_hit,output}}}
LOCAL_PRICING_DB: dict[str, dict[str, dict[str, float]]] = {
	"deepseek": {
		"deepseek-v4-flash": {"input_miss": 0.2083, "input_hit": 0.00694, "output": 0.625},
		"deepseek-v4-pro": {"input_miss": 0.625, "input_hit": 0.02083, "output": 1.875},
	},
	"openai": {
		"gpt-4o-mini": {"input_miss": 0.15, "input_hit": 0.075, "output": 0.60},
		"gpt-4o": {"input_miss": 2.50, "input_hit": 1.25, "output": 10.00},
		"gpt-4.1-mini": {"input_miss": 0.40, "input_hit": 0.10, "output": 1.60},
		"gpt-4.1": {"input_miss": 2.00, "input_hit": 0.50, "output": 8.00},
	},
}

# 旧默认（与 L1.2 第一版一致），仅作最终兜底；可被 XEYO_BUDGET_PRICE_* 覆盖
_DEFAULT_USD_PRICES: dict[str, float] = {
	"input_miss": 2.0,
	"input_hit": 0.2,
	"output": 8.0,
}


def _price_env(name: str, default: float) -> float:
	raw = os.environ.get(name, "").strip()
	if not raw:
		return default
	try:
		v = float(raw)
	except (TypeError, ValueError):
		return default
	return v if v >= 0 else default


def _normalize_price(price: Any) -> dict[str, float] | None:
	"""aipricing.guru 单模型价格 → (input_miss, input_hit, output) USD/1M。

	兼容两种字段名：新接口 ``pricing.inputPerM / cachedInputPerM / outputPerM``，
	以及历史接口 ``prompt / cache_prompt / completion``。
	"""
	if not isinstance(price, dict):
		return None
	try:
		raw_input = price.get("inputPerM")
		if raw_input is None:
			raw_input = price.get("prompt")
		input_miss = float(raw_input or 0)
		raw_out = price.get("outputPerM")
		if raw_out is None:
			raw_out = price.get("completion")
		output = float(raw_out or 0)
		raw_cache = price.get("cachedInputPerM")
		if raw_cache is None:
			raw_cache = price.get("cache_prompt")
		cached = float(raw_cache) if raw_cache is not None else input_miss
	except (TypeError, ValueError):
		return None
	return {
		"input_miss": max(0.0, input_miss),
		"input_hit": max(0.0, cached),
		"output": max(0.0, output),
	}


def _find_model_entry(
	data: dict[str, Any], provider: str, model_name: str
) -> dict[str, float] | None:
	"""在新接口 ``{"models":[{id,provider,pricing}]}`` 里按 厂商+模型 匹配。

	精确（id / name，忽略大小写）→ 包含匹配；找不到返回 None。
	"""
	name = (model_name or "").strip()
	if not name:
		return None
	low = name.lower()
	models = data.get("models")
	if isinstance(models, list):
		best: dict[str, Any] | None = None
		for m in models:
			if not isinstance(m, dict):
				continue
			if str(m.get("provider") or "").lower() != provider:
				continue
			mid = str(m.get("id") or "").lower()
			mname = str(m.get("name") or "").lower()
			if mid == low or mname == low:
				return _normalize_price(m.get("pricing"))
			if best is None and (low in mid or low in mname):
				best = m
		if best is not None:
			return _normalize_price(best.get("pricing"))
	# 历史接口：{provider: {model: {prompt, cache_prompt, completion}}}
	table = data.get(provider)
	if isinstance(table, dict):
		exact = table.get(name)
		if isinstance(exact, dict):
			return _normalize_price(exact)
		for key, val in table.items():
			if isinstance(val, dict) and (key.lower() == low or low in key.lower()):
				return _normalize_price(val)
	return None


def _pricing_ttl_seconds() -> float:
	"""TTL 秒数：XEYO_PRICING_TTL_HOURS（默认 24h，下限 1h）。"""
	raw = os.environ.get("XEYO_PRICING_TTL_HOURS", "").strip()
	if not raw:
		return _PRICING_TTL_DEFAULT_HOURS * 3600.0
	try:
		hours = float(raw)
	except (TypeError, ValueError):
		return _PRICING_TTL_DEFAULT_HOURS * 3600.0
	return max(1.0, hours) * 3600.0


def _cache_path() -> Path:
	"""价格表磁盘缓存（与用量 ledger 同目录）。"""
	override = os.environ.get("XEYO_USAGE_DIR", "").strip()
	base = Path(override).expanduser() if override else Path.home() / ".xeyo" / "usage"
	return base / "pricing_cache.json"


def _read_disk_cache() -> tuple[float, dict[str, Any]] | None:
	path = _cache_path()
	try:
		raw = path.read_text(encoding="utf-8")
	except OSError:
		return None
	try:
		obj = json.loads(raw)
	except json.JSONDecodeError:
		return None
	if not isinstance(obj, dict):
		return None
	try:
		ts = float(obj.get("fetched_at") or 0)
	except (TypeError, ValueError):
		return None
	data = obj.get("data")
	return (ts, data) if isinstance(data, dict) else None


def _write_disk_cache(ts: float, data: dict[str, Any]) -> None:
	path = _cache_path()
	try:
		path.parent.mkdir(parents=True, exist_ok=True)
		tmp = path.with_suffix(".json.tmp")
		tmp.write_text(
			json.dumps({"fetched_at": ts, "data": data}, ensure_ascii=False),
			encoding="utf-8",
		)
		tmp.replace(path)
	except OSError:
		pass


def _load_pricing_json(timeout: float) -> dict[str, Any] | None:
	"""内存缓存(TTL) → 磁盘缓存(TTL) → 后台线程拉取并落盘。

	网络拉取绝不阻塞调用方（热路径在事件循环上）：TTL 内直接返回缓存；
	过期时立刻返回现有值（含过期磁盘兜底），由后台线程刷新，下轮生效。
	失败也缓存为 None，避免每次 submit 都卡网络。
	"""
	global _pricing_cache, _pricing_disk_loaded, _refresh_inflight
	now = time.time()
	ttl = _pricing_ttl_seconds()
	with _pricing_lock:
		if _pricing_cache is not None and now - _pricing_cache[0] < ttl:
			return _pricing_cache[1]
		if not _pricing_disk_loaded:
			disk = _read_disk_cache()
			if disk is not None:
				_pricing_cache = disk  # type: ignore[assignment]
				_pricing_disk_loaded = True
				if now - disk[0] < ttl and disk[1] is not None:
					return disk[1]
	stale: dict[str, Any] | None = (
		_pricing_cache[1] if _pricing_cache is not None else None
	)
	# 过期：立即返回现有值（可能为 None），后台线程负责刷新。
	with _pricing_lock:
		if _refresh_inflight:
			return stale
		_refresh_inflight = True

	def _refresh() -> None:
		global _refresh_inflight, _pricing_cache, _pricing_disk_loaded
		try:
			url = os.environ.get("XEYO_PRICING_URL", "").strip() or PRICING_URL
			data: dict[str, Any] | None
			try:
				req = Request(url, headers={"User-Agent": "xeyo/0.1"})
				with urlopen(req, timeout=timeout) as resp:
					data = json.loads(resp.read().decode("utf-8"))
			except Exception:
				data = None
			if not isinstance(data, dict):
				data = None
			fetched_at = time.time()
			with _pricing_lock:
				# 拉取失败时保留旧值内容但刷新时间戳，避免每轮都重试网络。
				_pricing_cache = (fetched_at, data if data is not None else stale)
				_pricing_disk_loaded = True
			if data is not None:
				_write_disk_cache(fetched_at, data)
		finally:
			with _pricing_lock:
				_refresh_inflight = False

	threading.Thread(target=_refresh, name="pricing-refresh", daemon=True).start()
	return stale


def refresh_pricing_blocking(timeout: float = 2.0) -> dict[str, Any] | None:
	"""显式同步拉取实时价（供启动预热 / 测试）；热路径请用 _load_pricing_json。"""
	global _pricing_cache, _pricing_disk_loaded, _refresh_inflight
	url = os.environ.get("XEYO_PRICING_URL", "").strip() or PRICING_URL
	data: dict[str, Any] | None
	try:
		req = Request(url, headers={"User-Agent": "xeyo/0.1"})
		with urlopen(req, timeout=timeout) as resp:
			data = json.loads(resp.read().decode("utf-8"))
	except Exception:
		data = None
	if not isinstance(data, dict):
		data = None
	fetched_at = time.time()
	with _pricing_lock:
		_pricing_cache = (fetched_at, data)
		_pricing_disk_loaded = True
		_refresh_inflight = False
	if data is not None:
		_write_disk_cache(fetched_at, data)
	return data


def _pricing_fetch_enabled() -> bool:
	"""XEYO_PRICE_FETCH=0/false/off/no 时完全不联网，只用本地兜底价。"""
	raw = os.environ.get("XEYO_PRICE_FETCH", "1").strip().lower()
	return raw not in ("0", "false", "off", "no")


def get_model_pricing(
	provider: str,
	model_name: str,
	timeout: float = 2.0,
) -> dict[str, float] | None:
	"""USD/1M 单价：{input_miss, input_hit, output}。

	优先用 aipricing.guru 实时价；接口异常 / 模型不在表内 / 开关关闭 → 本地兜底。
	"""
	prov = (provider or "").lower()
	if _pricing_fetch_enabled():
		data = _load_pricing_json(timeout)
		if isinstance(data, dict):
			entry = _find_model_entry(data, prov, model_name)
			if entry is not None:
				return entry
	return _local_pricing(prov, model_name)


def _local_pricing(provider: str, model_name: str) -> dict[str, float]:
	prov = (provider or "").lower()
	name = (model_name or "").strip().lower()
	db = LOCAL_PRICING_DB.get(prov)
	if db:
		exact = db.get(name)
		if exact:
			return dict(exact)
		if prov == "deepseek":
			tier = _deepseek_tier(name)
			return dict(db["deepseek-v4-pro" if tier == "pro" else "deepseek-v4-flash"])
		if "gpt-4o-mini" in db:
			return dict(db["gpt-4o-mini"])
	return {
		"input_miss": _price_env("XEYO_BUDGET_PRICE_INPUT_USD", _DEFAULT_USD_PRICES["input_miss"]),
		"input_hit": _price_env("XEYO_BUDGET_PRICE_CACHED_INPUT_USD", _DEFAULT_USD_PRICES["input_hit"]),
		"output": _price_env("XEYO_BUDGET_PRICE_OUTPUT_USD", _DEFAULT_USD_PRICES["output"]),
	}


def estimate_usd(
	*,
	provider: str,
	model: str,
	usage: dict[str, Any],
	local_only: bool = False,
	ts: float | None = None,
) -> float:
	"""按用户选择的 provider / model 折算一轮 usage 的 USD（实时价优先）。

	``local_only=True`` 只查本地兜底价：未设 USD 上限的普通使用不依赖第三方。
	``ts`` 为消费时刻（默认 now）：DeepSeek 等分时厂商按高峰 / 低峰倍率折算。
	"""
	hit, miss, out = split_usage(usage)
	if ts is None:
		ts = time.time()
	if local_only:
		price = _local_pricing(provider, model)
	else:
		price = get_model_pricing(provider, model) or _local_pricing(provider, model)
	price = effective_prices(provider, model, ts, price) or price
	return (
		hit * price["input_hit"] + miss * price["input_miss"] + out * price["output"]
	) / _M
