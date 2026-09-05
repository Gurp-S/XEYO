"""DeepSeek live probe: Ĥ vs prompt_cache_hit_tokens. Default tests skip this."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from memory.simulator.cache_model import CacheState, prices_for, rho_hat
from memory.simulator.cost_model import c_biz_yuan, hat_H, split_tokens
from memory.simulator.metrics import HitRecord
from memory.simulator.params import Params, load_params
from memory.simulator.state_model import apply, freeze_s0, token_len

TTL_SLEEP = {
	"continuous": 0.0,
	"5min": 300.0,
	"10min": 600.0,
	"30min": 1800.0,
	"1h": 3600.0,
	"2h": 7200.0,
}


def _load_dotenv() -> None:
	root = Path(__file__).resolve().parents[3]
	py = Path(__file__).resolve().parents[2]
	for path in (root / ".env", py / ".env", Path.cwd() / ".env"):
		if not path.is_file():
			continue
		for raw in path.read_text(encoding="utf-8").splitlines():
			line = raw.strip()
			if not line or line.startswith("#") or "=" not in line:
				continue
			key, _, val = line.partition("=")
			key = key.strip()
			val = val.strip().strip("'").strip('"')
			if key and key not in os.environ:
				os.environ[key] = val


def have_api_key() -> bool:
	_load_dotenv()
	return bool(
		os.environ.get("DEEPSEEK_API_KEY", "").strip()
		or os.environ.get("XEYO_MODEL_API_KEY", "").strip()
	)


def _ensure_key() -> None:
	_load_dotenv()
	if not os.environ.get("DEEPSEEK_API_KEY") and os.environ.get("XEYO_MODEL_API_KEY"):
		os.environ["DEEPSEEK_API_KEY"] = os.environ["XEYO_MODEL_API_KEY"]


def messages_from_x(x: str) -> list[dict[str, Any]]:
	"""Wrap projected text as a single user message so the prefix is the payload."""
	return [{"role": "user", "content": x[:80_000]}]


def extract_usage(event: dict[str, Any]) -> dict[str, Any] | None:
	u = event.get("usage")
	if not isinstance(u, dict) or not u:
		return None
	details = u.get("prompt_tokens_details")
	cached = None
	if isinstance(details, dict):
		cached = details.get("cached_tokens")
	hit = u.get("prompt_cache_hit_tokens")
	if hit is None:
		hit = cached
	miss = u.get("prompt_cache_miss_tokens")
	prompt = u.get("prompt_tokens")
	if miss is None and prompt is not None and hit is not None:
		miss = max(int(prompt) - int(hit), 0)
	return {
		"prompt_tokens": prompt,
		"completion_tokens": u.get("completion_tokens"),
		"prompt_cache_hit_tokens": hit,
		"prompt_cache_miss_tokens": miss,
	}


async def probe_one(
	messages: list[dict[str, Any]],
	*,
	max_tokens: int = 8,
) -> dict[str, Any]:
	"""One streaming call with include_usage. Does not change model.deepseek defaults."""
	_ensure_key()
	from engine.abort import AbortController
	from model.deepseek import DeepSeekModelClient

	try:
		import httpx
	except ImportError as e:  # pragma: no cover
		raise RuntimeError("httpx required for live probe") from e

	inner = DeepSeekModelClient()
	abort = AbortController()
	body = inner._build_body(messages, [], stream=True)
	body["stream_options"] = {"include_usage": True}
	body["max_tokens"] = max_tokens
	url = f"{inner._base_url}/chat/completions"
	usage: dict[str, Any] | None = None
	async with httpx.AsyncClient(timeout=180.0) as client:
		async with client.stream("POST", url, headers=inner._headers(), json=body) as resp:
			resp.raise_for_status()
			async for line in resp.aiter_lines():
				if not line.startswith("data:"):
					continue
				payload = line[len("data:") :].strip()
				if not payload or payload == "[DONE]":
					continue
				try:
					event = json.loads(payload)
				except json.JSONDecodeError:
					continue
				got = extract_usage(event)
				if got:
					usage = got
	return usage or {}


def record_from_usage(
	*,
	action: str,
	cache: CacheState,
	x: str,
	lcp: int,
	predicted_hit: float,
	predicted_cost: float,
	usage: dict[str, Any],
	params: Params,
	age: float,
) -> HitRecord:
	from usage.pricing import estimate_cny, split_usage

	prompt = int(usage.get("prompt_tokens") or 0)
	hit, miss, out = split_usage(usage)
	actual = estimate_cny(
		provider=cache.provider,
		model=cache.model,
		usage=usage,
		ts=params.default_ts,
	)
	return HitRecord(
		request_id=uuid.uuid4().hex,
		provider=cache.provider,
		cache_age=age,
		action=action,
		LCP=lcp,
		predicted_hit=predicted_hit,
		observed_hit=float(hit),
		prompt_tokens=prompt,
		output_tokens=int(out),
		predicted_cost=predicted_cost,
		actual_cost=actual,
		context_length=prompt or token_len(x),
	)


async def probe_state_actions(
	s0,
	cache: CacheState,
	actions: tuple[str, ...] = ("keep", "C1", "C2"),
	params: Params | None = None,
) -> list[HitRecord]:
	p = params or load_params()
	s0 = freeze_s0(s0)
	rows: list[HitRecord] = []
	for a in actions:
		if a not in ("keep", "C1", "C2"):
			continue
		s_a = apply(a, s0, p)
		proj, spl = split_tokens(s_a=s_a, cache=cache, action=a, params=p)
		prices = prices_for(cache, p)
		pred_cost = c_biz_yuan(spl, p.o_mean, prices)
		usage = await probe_one(messages_from_x(proj.x))
		if not usage:
			continue
		rows.append(
			record_from_usage(
				action=a,
				cache=cache,
				x=proj.x,
				lcp=spl.lcp,
				predicted_hit=spl.H,
				predicted_cost=pred_cost,
				usage=usage,
				params=p,
				age=cache.age_seconds,
			)
		)
	return rows


def predicted_split_for_x(x: str, cache: CacheState, action: str, params: Params):
	h, lcp = hat_H(
		x_a=x,
		x_prev=cache.x_prev,
		L=token_len(x),
		action=action,
		rho=rho_hat(cache, params),
		g=params.g,
	)
	return h, lcp


def ttl_grid_rho(params: Params | None = None) -> list[dict[str, float | str]]:
	"""Predicted ρ at each TTL bucket (no network)."""
	p = params or load_params()
	out: list[dict[str, float | str]] = []
	for name, age in TTL_SLEEP.items():
		rho = rho_hat(CacheState(age_seconds=age, provider=p.provider), p)
		out.append({"ttl": name, "age_seconds": age, "rho": rho})
	return out


def _lcp_chars(a: str, b: str) -> int:
	n = min(len(a), len(b))
	i = 0
	while i < n and a[i] == b[i]:
		i += 1
	return i


def _canon(messages: list[dict[str, Any]]) -> str:
	return json.dumps(messages, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _predict_from_prior(
	*,
	messages: list[dict[str, Any]],
	prev_canon: str | None,
	prev_prompt: int | None,
	params: Params,
	age: float,
) -> tuple[float, int]:
	canon = _canon(messages)
	if not prev_canon or not prev_prompt:
		return 0.0, 0
	lcp_c = _lcp_chars(canon, prev_canon)
	lcp_tok = prev_prompt * (lcp_c / max(len(prev_canon), 1))
	cache = CacheState(age_seconds=age, provider=params.provider, model=params.model, slot=params.price_slot)
	rho = rho_hat(cache, params)
	h, lcp = hat_H(
		x_a=canon,
		x_prev=prev_canon,
		L=int(prev_prompt) + max(int(lcp_tok), 0),
		action="keep",
		rho=rho,
		g=params.g,
	)
	# Use token LCP from char ratio, not char-tokenizer of JSON
	blk = params.g * int(lcp_tok // params.g)
	h = min(float(prev_prompt + 8), max(0.0, rho * blk))
	return h, int(lcp_tok)


async def probe_keep_pair(
	prefix: str,
	*,
	idle_seconds: float = 0.0,
	label: str = "pair",
	params: Params | None = None,
) -> list[HitRecord]:
	"""Two keep shots: fill cache, then reuse prefix. Optional idle between them."""
	import asyncio

	p = params or load_params()
	follow = "\n请只回复一个字：好"
	msgs1 = [{"role": "user", "content": prefix}]
	msgs2 = [{"role": "user", "content": prefix + follow}]
	u1 = await probe_one(msgs1)
	if idle_seconds > 0:
		await asyncio.sleep(idle_seconds)
	u2 = await probe_one(msgs2)
	cache = CacheState(
		provider=p.provider,
		model=p.model,
		slot=p.price_slot,
		ts=p.default_ts,
		age_seconds=idle_seconds,
	)
	rows: list[HitRecord] = []
	prompt1 = int((u1 or {}).get("prompt_tokens") or 0)
	for i, (msgs, usage, age, prev_c, prev_p) in enumerate(
		(
			(msgs1, u1, 0.0, None, None),
			(msgs2, u2, idle_seconds, _canon(msgs1), prompt1),
		)
	):
		if not usage:
			continue
		pred, lcp = _predict_from_prior(
			messages=msgs,
			prev_canon=prev_c,
			prev_prompt=prev_p,
			params=p,
			age=age,
		)
		prices = prices_for(cache, p)
		from memory.simulator.cost_model import Split

		prompt = int(usage.get("prompt_tokens") or 0)
		spl = Split(
			H=pred,
			U=max(float(prompt) - pred, 0.0),
			W_phys=0.0,
			W_fill=0.0,
			L=prompt,
			lcp=lcp,
			rho=rho_hat(CacheState(age_seconds=age), p),
		)
		pred_cost = c_biz_yuan(spl, float(usage.get("completion_tokens") or 0), prices)
		rows.append(
			record_from_usage(
				action="keep",
				cache=CacheState(age_seconds=age, provider=p.provider, model=p.model),
				x=_canon(msgs),
				lcp=lcp,
				predicted_hit=pred,
				predicted_cost=pred_cost,
				usage=usage,
				params=p,
				age=age,
			)
		)
		rows[-1].conversation_length = i + 1
	return rows


def hits_path() -> Path:
	return Path(__file__).with_name("out") / "probe_hits.json"


def save_hits(rows: list[HitRecord], path: Path | None = None) -> Path:
	p = path or hits_path()
	p.parent.mkdir(parents=True, exist_ok=True)
	payload = [r.__dict__ for r in rows]
	p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	return p


def load_hits(path: Path | None = None) -> list[HitRecord]:
	p = path or hits_path()
	if not p.is_file():
		return []
	raw = json.loads(p.read_text(encoding="utf-8"))
	out: list[HitRecord] = []
	for row in raw:
		out.append(HitRecord(**{k: row[k] for k in HitRecord.__dataclass_fields__ if k in row}))
	return out
