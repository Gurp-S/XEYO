# ruff: noqa: T201
"""只跑 C2 的 live 命中率评测（单进程、冷启动一次，不跑 project 对照）。

步骤:
  1) 扩展真实会话到 200 user 轮（循环拼接 + id 重映射）
  2) 逐 user 轮发送 C2 投影，记录 cache hit/miss
  3) 写 quality_validation.json 表D 行 hitrate_real200_c2_only

用法 (GLM-5.3-Flash 示例):
  set ZHIPU_API_KEY=...
  set XEYO_PROBE_BASE_URL=https://open.bigmodel.cn/api/paas/v4
  set XEYO_PROBE_MODEL=glm-5.3-flash
  python scripts/hitrate_c2_only_live.py --turns 200

  # 只生成 200 轮 JSONL，不打 API:
  python scripts/hitrate_c2_only_live.py --build-only --turns 200
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from scripts.session_extend_turns import (
	DEFAULT_OUT,
	build_extended_session,
	resolve_source,
	rows_to_api,
)
from scripts.memory_stack_eval import (
	SUBMIT_TIMEOUT_S,
	_projection_sequence,
	_build_ab_system,
	apply_sandbox,
	seed_workspace,
	update_docs12_table_d,
	upsert_quality_row,
)

DEFAULT_SESSION_OUT = DEFAULT_OUT


def _configure_probe_body(client, *, max_tokens: int) -> None:
	"""Probe 请求：限制输出长度；GLM-5.x 必须开 thinking，默认用 low 避免每轮深度推理卡分钟级。"""
	orig = client._build_body
	model_l = (client._model or "").lower()
	base_l = (client._base_url or "").lower()
	is_glm = "glm" in model_l or "bigmodel" in base_l
	effort = os.environ.get("XEYO_PROBE_REASONING_EFFORT", "low").strip().lower()
	if effort not in ("low", "high", "max"):
		effort = "low"

	def _build_body(messages, tools, *, stream):
		body = orig(messages, tools, stream=stream)
		body["max_tokens"] = max_tokens
		if is_glm:
			body["thinking"] = {"type": "enabled"}
			body["reasoning_effort"] = effort
		return body

	client._build_body = _build_body  # type: ignore[method-assign]


def _probe_client_from_env():
	from model.openai_compat import OpenAICompatClient, PROVIDER_PRESETS

	key = (
		os.environ.get("XEYO_PROBE_API_KEY", "").strip()
		or os.environ.get("ZHIPU_API_KEY", "").strip()
		or os.environ.get("DEEPSEEK_API_KEY", "").strip()
		or os.environ.get("XEYO_MODEL_API_KEY", "").strip()
	)
	if not key:
		return None, "missing API key (XEYO_PROBE_API_KEY / ZHIPU_API_KEY / DEEPSEEK_API_KEY)"
	base = (
		os.environ.get("XEYO_PROBE_BASE_URL", "").strip()
		or os.environ.get("ZHIPU_BASE_URL", "").strip()
		or os.environ.get("DEEPSEEK_BASE_URL", "").strip()
		or PROVIDER_PRESETS["deepseek"]["base_url"]
	).rstrip("/")
	model = (
		os.environ.get("XEYO_PROBE_MODEL", "").strip()
		or os.environ.get("ZHIPU_MODEL", "").strip()
		or os.environ.get("DEEPSEEK_MODEL", "").strip()
		or "deepseek-chat"
	)
	provider = os.environ.get("XEYO_PROBE_PROVIDER", "").strip() or "openai_compat"
	client = OpenAICompatClient(
		api_key=key,
		base_url=base,
		model=model,
		provider=provider,
		thinking=os.environ.get("XEYO_PROBE_THINKING", "disabled"),
		temperature=0.0,
	)
	return client, None


async def _probe_chat(client, messages: list[dict]) -> dict:
	from engine.abort import AbortController

	timeout_s = float(os.environ.get("XEYO_PROBE_TIMEOUT_S", str(SUBMIT_TIMEOUT_S)))
	parts: list[str] = []
	try:
		async with asyncio.timeout(timeout_s):
			async for chunk in client.stream(messages, [], AbortController()):
				if chunk.kind == "text_delta" and chunk.text:
					parts.append(chunk.text)
	except Exception as exc:
		return {"text": "".join(parts), "usage": client.last_usage or {}, "error": f"{type(exc).__name__}: {exc}"}
	return {"text": "".join(parts), "usage": client.last_usage or {}}


def _tail_rates(per_turn: list[dict], *, tail_n: int) -> dict:
	if not per_turn:
		return {"tail_n": 0, "tail_rate": 0.0}
	slice_rows = per_turn[-tail_n:] if len(per_turn) >= tail_n else per_turn
	hit = miss = 0
	for r in slice_rows:
		hit += int(r.get("hit") or 0)
		miss += int(r.get("miss") or 0)
	total = hit + miss
	return {
		"tail_n": len(slice_rows),
		"tail_hit": hit,
		"tail_miss": miss,
		"tail_rate": round((hit / total * 100.0) if total else 0.0, 4),
	}


def _checkpoint_path(target_turns: int) -> Path:
	return ROOT / "memory" / "simulator" / "out" / f"hitrate_real{target_turns}_c2_only.partial.json"


def _load_checkpoint(path: Path) -> dict | None:
	if not path.is_file():
		return None
	try:
		return json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return None


def _save_checkpoint(path: Path, summary: dict) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def _next_probe_turn(per_turn: list[dict], start_turn: int) -> int:
	"""下一 probe 轮次（0-based）：失败/缺失行优先重试。"""
	if not per_turn:
		return max(0, start_turn - 1)
	by_turn = {int(r["turn"]): r for r in per_turn if "turn" in r}
	max_t = max(by_turn)
	for t in range(max_t + 2):
		row = by_turn.get(t)
		if row is None:
			return t
		if int(row.get("prompt") or 0) <= 0:
			return t
	return max_t + 1


def _merge_resume(per_turn: list[dict], ckpt: dict) -> tuple[list[dict], dict]:
	"""把 checkpoint 里已有轮次合并进当前 run（按 turn 去重）。"""
	prior = list(ckpt.get("per_turn") or [])
	by_turn = {int(r["turn"]): r for r in prior if "turn" in r}
	for r in per_turn:
		by_turn[int(r["turn"])] = r
	merged = [by_turn[k] for k in sorted(by_turn)]
	totals = {
		"total_hit": sum(int(r.get("hit") or 0) for r in merged),
		"total_miss": sum(int(r.get("miss") or 0) for r in merged),
		"total_out": sum(int(r.get("output") or 0) for r in merged if "output" in r)
		or sum(int((r.get("usage_raw") or {}).get("completion_tokens") or 0) for r in merged),
		"total_prompt": sum(int(r.get("prompt") or 0) for r in merged),
		"transitions": sum(1 for r in merged if r.get("transition")),
		"errors": int(ckpt.get("errors") or 0),
	}
	steady_hit = steady_miss = 0
	for r in merged:
		t = int(r.get("turn") or 0)
		if t > 0 and not r.get("transition"):
			steady_hit += int(r.get("hit") or 0)
			steady_miss += int(r.get("miss") or 0)
	totals["steady_hit"] = steady_hit
	totals["steady_miss"] = steady_miss
	return merged, totals


async def _probe_chat_with_retry(
	client,
	messages: list[dict],
	*,
	max_retries: int = 6,
	base_delay_s: float = 15.0,
) -> dict:
	"""429 限流时指数退避重试。"""
	last: dict = {"text": "", "usage": {}, "error": "no attempt"}
	for attempt in range(max_retries + 1):
		last = await _probe_chat(client, messages)
		err = str(last.get("error") or "")
		if not err:
			return last
		is_rate = "429" in err or "限流" in err or "too many" in err.lower()
		if not is_rate or attempt >= max_retries:
			return last
		wait = base_delay_s * (2**attempt)
		print(f"  rate limited, retry in {wait:.0f}s ({attempt + 1}/{max_retries})...", flush=True)
		await asyncio.sleep(wait)
	return last


async def run_c2_only(
	*,
	session_path: Path,
	target_turns: int,
	tail_n: int = 20,
	delay_s: float = 0.0,
	max_tokens: int = 64,
	progress_every: int = 1,
	start_turn: int = 1,
	resume_path: Path | None = None,
) -> int:
	from memory.simulator.params import load_params
	from memory.simulator.replay import load_jsonl, _user_turn_indices

	rows = load_jsonl(session_path)
	api = rows_to_api(rows)
	user_turns = _user_turn_indices(api)
	total_turns = min(len(user_turns), target_turns)
	if len(user_turns) < target_turns:
		print(f"WARN: session has {len(user_turns)} user turns < {target_turns}")
	# 截断到恰好 target_turns 个 user 轮（按消息边界）
	if len(user_turns) > target_turns:
		cut_msg_idx = user_turns[target_turns]
		api = api[:cut_msg_idx]
		user_turns = user_turns[:target_turns]

	proj_dir = apply_sandbox()
	seed_workspace(proj_dir)
	sys_text = await _build_ab_system(proj_dir)
	params = load_params()
	from usage.pricing import split_usage

	probe_client, probe_err = _probe_client_from_env()
	if probe_client is None:
		print(f"ERROR: {probe_err}")
		return 1
	_configure_probe_body(probe_client, max_tokens=max_tokens)

	checkpoint_path = resume_path or _checkpoint_path(target_turns)
	ckpt = _load_checkpoint(checkpoint_path) if resume_path or checkpoint_path.is_file() else None
	start_idx = max(0, start_turn - 1)

	per_turn: list[dict] = []
	total_hit = total_miss = total_out = total_prompt = 0
	steady_hit = steady_miss = transitions = errors = 0
	proj_start = 0
	initial_working = None
	initial_turns_since_c2: int | None = None
	if ckpt:
		per_turn, restored = _merge_resume([], ckpt)
		total_hit = restored["total_hit"]
		total_miss = restored["total_miss"]
		total_out = restored["total_out"]
		total_prompt = restored["total_prompt"]
		steady_hit = restored["steady_hit"]
		steady_miss = restored["steady_miss"]
		transitions = restored["transitions"]
		errors = restored["errors"]
		start_idx = _next_probe_turn(per_turn, start_turn)
		proj_saved = ckpt.get("projection") if isinstance(ckpt.get("projection"), dict) else None
		if proj_saved and isinstance(proj_saved.get("working"), dict):
			from memory.working import _from_dict

			initial_working = _from_dict(proj_saved["working"], "hitrate")
			initial_turns_since_c2 = int(proj_saved.get("turns_since_c2") or 0)
			proj_start = int(proj_saved.get("turn") or 0) + 1
			print(
				f"resume: {checkpoint_path} ({len(per_turn)} probe rows, "
				f"projection from turn {proj_start + 1}, probe from turn {start_idx + 1})"
			)
		else:
			print(
				f"resume: {checkpoint_path} ({len(per_turn)} probe rows, probe from turn {start_idx + 1})\n"
				f"WARN: no projection snapshot — replaying turns 1-{start_idx} offline (~1-3 min, no API)..."
			)
	elif start_idx > 0:
		print(
			f"WARN: no checkpoint — replaying turns 1-{start_idx} offline (~1-3 min, no API)..."
		)
	t0 = time.perf_counter()

	last_projection: dict = {}

	def _replay_progress(t: int, working, turns_since_c2: int) -> None:
		from memory.working import _to_dict

		last_projection.clear()
		last_projection.update(
			{
				"turn": t,
				"turns_since_c2": int(turns_since_c2),
				"working": _to_dict(working),
			}
		)
		if initial_working is not None:
			return
		if t < start_idx and ((t + 1) % 5 == 0 or t + 1 == start_idx):
			print(f"  [replay {t + 1:3d}/{start_idx}] building C2 projection state...", flush=True)

	print(f"session: {session_path}")
	print(f"user turns: {len(user_turns)}, messages: {len(api)}")
	print(f"model: {os.environ.get('XEYO_PROBE_MODEL') or os.environ.get('ZHIPU_MODEL') or os.environ.get('DEEPSEEK_MODEL') or '(default)'}")
	print(f"progress: every {max(1, progress_every)} turn(s), tail window={tail_n}, start_turn={start_idx + 1}")
	sys.stdout.flush()

	for t, msgs, plen, transition in _projection_sequence(
		api,
		mode="c2",
		sys_text=sys_text,
		params=params,
		force_c2=True,
		start_turn=proj_start if initial_working is not None else 0,
		initial_working=initial_working,
		initial_turns_since_c2=initial_turns_since_c2,
		on_step=_replay_progress,
	):
		if t < start_idx:
			continue
		if delay_s > 0 and t > start_idx:
			await asyncio.sleep(delay_s)
		print(f"  -> turn {t + 1}/{total_turns} requesting...", flush=True)
		r = await _probe_chat_with_retry(probe_client, msgs)
		if r.get("error"):
			errors += 1
			print(f"  [{t + 1:3d}/{total_turns}] ERROR {r['error']}", flush=True)
		u = r.get("usage") or {}
		hit, miss, out = split_usage(u)
		prompt = int(u.get("prompt_tokens") or 0) or hit + miss
		# 覆盖同 turn 重跑
		per_turn = [r for r in per_turn if int(r.get("turn") or -1) != t]
		total_hit = sum(int(r.get("hit") or 0) for r in per_turn)
		total_miss = sum(int(r.get("miss") or 0) for r in per_turn)
		total_out = sum(int((r.get("usage_raw") or {}).get("completion_tokens") or 0) for r in per_turn)
		total_prompt = sum(int(r.get("prompt") or 0) for r in per_turn)
		steady_hit = sum(int(r.get("hit") or 0) for r in per_turn if int(r.get("turn") or 0) > 0 and not r.get("transition"))
		steady_miss = sum(int(r.get("miss") or 0) for r in per_turn if int(r.get("turn") or 0) > 0 and not r.get("transition"))
		transitions = sum(1 for r in per_turn if r.get("transition"))
		row = {
			"turn": t,
			"prefix_msgs": plen,
			"prompt": prompt,
			"hit": hit,
			"miss": miss,
			"transition": transition,
			"usage_raw": u,
			"output": out,
		}
		per_turn.append(row)
		total_hit += hit
		total_miss += miss
		total_out += out
		total_prompt += prompt
		if transition:
			transitions += 1
		if t > 0 and not transition:
			steady_hit += hit
			steady_miss += miss

		partial = {
			"mode": "c2_only",
			"turns": len(per_turn),
			"target_turns": target_turns,
			"session_path": str(session_path),
			"prompt": total_prompt,
			"hit": total_hit,
			"miss": total_miss,
			"output": total_out,
			"errors": errors,
			"per_turn": per_turn,
		}
		if last_projection:
			partial["projection"] = dict(last_projection)
		_save_checkpoint(checkpoint_path, partial)

		show = (
			t == 0
			or (t + 1) % max(1, progress_every) == 0
			or t + 1 == total_turns
		)
		if show:
			elapsed = time.perf_counter() - t0
			pct = (t + 1) / total_turns * 100.0 if total_turns else 0.0
			eta_s = (elapsed / (t + 1)) * (total_turns - t - 1) if t >= 0 else 0.0
			turn_rate = (hit / (hit + miss) * 100) if (hit + miss) else 0.0
			agg_rate_now = (total_hit / (total_hit + total_miss) * 100) if (total_hit + total_miss) else 0.0
			steady_rate_now = (steady_hit / (steady_hit + steady_miss) * 100) if (steady_hit + steady_miss) else 0.0
			tail_now = _tail_rates(per_turn, tail_n=tail_n)
			print(
				f"  [{t + 1:3d}/{total_turns} {pct:5.1f}%] "
				f"prompt={prompt:6d} hit={hit:6d} miss={miss:6d} "
				f"turn={turn_rate:5.1f}% agg={agg_rate_now:5.1f}% steady={steady_rate_now:5.1f}% "
				f"tail{tail_n}={tail_now['tail_rate']:5.1f}% "
				f"trans={int(transition)} elapsed={elapsed:6.0f}s eta={eta_s:6.0f}s",
				flush=True,
			)

	agg_rate = (total_hit / (total_hit + total_miss) * 100.0) if (total_hit + total_miss) else 0.0
	steady_rate = (steady_hit / (steady_hit + steady_miss) * 100.0) if (steady_hit + steady_miss) else 0.0
	tail = _tail_rates(per_turn, tail_n=tail_n)

	summary = {
		"mode": "c2_only",
		"turns": len(per_turn),
		"target_turns": target_turns,
		"session_path": str(session_path),
		"prompt": total_prompt,
		"hit": total_hit,
		"miss": total_miss,
		"hit_rate": round(agg_rate, 4),
		"steady_hit": steady_hit,
		"steady_miss": steady_miss,
		"steady_rate": round(steady_rate, 4),
		"transitions": transitions,
		"errors": errors,
		"output": total_out,
		"per_turn": per_turn,
		**tail,
	}

	case_id = f"hitrate_real{target_turns}_c2_only"
	upsert_quality_row(
		case_id,
		source="表C",
		input_tokens=total_hit + total_miss,
		cache_hit=total_hit,
		cache_miss=total_miss,
		action=f"live·真实扩展{target_turns}轮·仅C2·冷启动单次",
		output=(
			f"agg={agg_rate:.2f}% steady={steady_rate:.2f}% "
			f"tail{tail['tail_n']}={tail['tail_rate']:.2f}% "
			f"trans={transitions} err={errors} in={total_hit + total_miss} out={total_out}"
		),
		detail=summary,
	)
	from scripts.memory_stack_eval import load_quality_rows

	update_docs12_table_d(load_quality_rows())

	report_path = ROOT / "memory" / "simulator" / "out" / f"{case_id}.json"
	report_path.parent.mkdir(parents=True, exist_ok=True)
	report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

	print("\n=== SUMMARY ===")
	print(json.dumps({k: summary[k] for k in summary if k != "per_turn"}, ensure_ascii=False, indent=2))
	print(f"report: {report_path}")
	print(f"A1 tail{tail_n} >= 99% ? {'PASS' if tail['tail_rate'] >= 99.0 else 'CHECK'}")
	return 0 if errors == 0 else 2


def main() -> int:
	ap = argparse.ArgumentParser(description="C2-only live hitrate (200-turn real session, single cold start)")
	ap.add_argument("--turns", type=int, default=200, help="user turns to run (default 200)")
	ap.add_argument("--tail", type=int, default=20, help="tail window for A1 (default 20)")
	ap.add_argument("--source", default="", help="base real session JSONL")
	ap.add_argument("--session", default="", help="extended session JSONL (skip build if exists)")
	ap.add_argument("--out", default="", help="extended session output path when building")
	ap.add_argument("--build-only", action="store_true", help="only build extended JSONL, do not call API")
	ap.add_argument("--delay-ms", type=int, default=0, help="delay between turns (rate limit)")
	ap.add_argument("--start-turn", type=int, default=1, help="1-based turn to start/resume probing")
	ap.add_argument("--resume", default="", help="partial checkpoint JSON (default: auto .partial.json)")
	ap.add_argument("--max-tokens", type=int, default=64, help="completion max tokens per probe")
	ap.add_argument("--progress-every", type=int, default=1, help="print progress every N turns (default 1)")
	args = ap.parse_args()

	session_path = Path(args.session).expanduser() if args.session else DEFAULT_SESSION_OUT
	if not session_path.is_file() or args.out:
		src = resolve_source(args.source or None) if args.source else None
		out = Path(args.out).expanduser() if args.out else session_path
		build_extended_session(source=src, target_user_turns=args.turns, out_path=out)
		session_path = out

	if args.build_only:
		return 0

	print("=== C2 ONLY LIVE (do not run project in same process) ===")
	t0 = time.perf_counter()
	resume_path = Path(args.resume).expanduser() if args.resume else None
	rc = asyncio.run(
		run_c2_only(
			session_path=session_path,
			target_turns=args.turns,
			tail_n=args.tail,
			delay_s=max(0.0, args.delay_ms / 1000.0),
			max_tokens=args.max_tokens,
			progress_every=max(1, args.progress_every),
			start_turn=max(1, args.start_turn),
			resume_path=resume_path,
		)
	)
	print(f"elapsed_s={time.perf_counter() - t0:.1f}")
	return rc


if __name__ == "__main__":
	raise SystemExit(main())
