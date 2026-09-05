"""对照 §4.7 v6.1，用 XEYO 现有对话结构打 DeepSeek，观察 KV 缓存命中。

不修改 query_loop / query_engine / model.deepseek：只在本脚本里包一层客户端，
给流式请求加上 stream_options.include_usage，从账单读 prompt_cache_*。

用法（在 python/ 目录，或把 python 加进 PYTHONPATH）::

    cd "D:\\lea\\XenYon code\\python"
    python scripts/kv_cache_probe.py
    python scripts/kv_cache_probe.py --interactive

需要 DEEPSEEK_API_KEY（环境变量或仓库根目录 .env）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

# §4.7 v6.1：块与存活折扣。单价用官方元 / 百万 token（2026-08-17 起，峰谷）。
# Ĥ = ρ L_blk 是预测；账单 H_obs 才是观测。H+U+W_phys=|X|。
# p_w=0 只表示写入免费，不表示没有物理写入。
# DeepSeek 无 write 档：发票 W_phys=0、未命中进 U；物理 fill 记在 W_prior，不进 C_biz。
G_BLOCK = 64
RHO = 0.95  # s × α_hit，α_hit=0.95；短会话近似 s=1
P_W = 0.0  # 表上无写缓存费；DeepSeek 发票分区仍令 W_phys=0
TZ_BJ = timezone(timedelta(hours=8))
# 高峰：北京时间 09:00–12:00、14:00–18:00；其余为空闲（空闲 = 高峰 × 1/2）
# (p_r 命中, p_u 未命中, p_o 输出)
DEEPSEEK_V4_PRICE_YUAN_PER_MTON: dict[str, dict[str, tuple[float, float, float]]] = {
	"deepseek-v4-flash": {"offpeak": (0.05, 1.5, 4.5), "peak": (0.10, 3.0, 9.0)},
	"deepseek-v4-pro": {"offpeak": (0.15, 4.5, 13.5), "peak": (0.30, 9.0, 27.0)},
}


def _is_peak_beijing(now: datetime | None = None) -> bool:
	t = now.astimezone(TZ_BJ) if now else datetime.now(TZ_BJ)
	hm = t.hour * 60 + t.minute
	return (9 * 60 <= hm < 12 * 60) or (14 * 60 <= hm < 18 * 60)


def resolve_prices(model: str, period: str) -> tuple[str, float, float, float]:
	"""返回 (档位, p_r, p_u, p_o)，单位元/百万 token。"""
	key = model.strip().lower()
	table = DEEPSEEK_V4_PRICE_YUAN_PER_MTON.get(key)
	if table is None:
		table = DEEPSEEK_V4_PRICE_YUAN_PER_MTON["deepseek-v4-flash"]
		key = "deepseek-v4-flash"
	if period == "auto":
		slot = "peak" if _is_peak_beijing() else "offpeak"
	elif period in ("peak", "offpeak"):
		slot = period
	else:
		raise ValueError(f"unknown period: {period}")
	p_r, p_u, p_o = table[slot]
	return slot, p_r, p_u, p_o


def c_biz_yuan(
	*,
	prompt: float,
	hit: float,
	out: float,
	p_r: float,
	p_u: float,
	p_o: float,
	w_phys: float = 0.0,
	p_w: float = P_W,
) -> float:
	"""C_biz = p_r H + p_u(|X|-H-W_phys) + p_w W_phys + p_o O，再除 1e6 换成元。

	p_w=0 只让第三项为 0，不把 W_phys 清零（写入免费 ≠ 没有写入）。
	DeepSeek 调用方应传入 w_phys=0：该供应商没有 write 档，未命中全部进 U。
	"""
	h = max(hit, 0.0)
	x = max(prompt, 0.0)
	w = max(w_phys, 0.0)
	u = max(x - h - w, 0.0)
	return (p_r * h + p_u * u + p_w * w + p_o * max(out, 0.0)) / 1_000_000.0


def _load_dotenv() -> None:
	for path in (REPO / ".env", ROOT / ".env", Path.cwd() / ".env"):
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


def _lcp_chars(a: str, b: str) -> int:
	n = min(len(a), len(b))
	i = 0
	while i < n and a[i] == b[i]:
		i += 1
	return i


def _canon_request(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> str:
	from model.deepseek import _normalize_messages_for_openai, _to_openai_tool

	payload = {
		"messages": _normalize_messages_for_openai(messages),
		"tools": [_to_openai_tool(t) for t in tools] if tools else [],
	}
	return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _extract_usage(event: dict[str, Any]) -> dict[str, Any] | None:
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
		"total_tokens": u.get("total_tokens"),
		"prompt_cache_hit_tokens": hit,
		"prompt_cache_miss_tokens": miss,
		"raw": u,
	}


@dataclass
class CallRecord:
	index: int
	user_turn: int
	char_len: int
	lcp_chars: int
	lcp_token_prior: float
	L_blk: int
	H_prior: float
	W_prior: int
	prompt_tokens: int | None
	hit: int | None
	miss: int | None
	completion_tokens: int | None
	hit_rate: float | None
	C_biz_prior: float | None
	C_biz_invoice: float | None
	period: str
	p_r: float
	p_u: float
	p_o: float


class CacheSpyClient:
	"""包装 DeepSeekModelClient：同一套 stream 协议，额外记下 usage。"""

	def __init__(self, inner: Any, *, period: str, p_r: float, p_u: float, p_o: float) -> None:
		self._inner = inner
		self.period = period
		self.p_r = p_r
		self.p_u = p_u
		self.p_o = p_o
		self.calls: list[CallRecord] = []
		self._prev_canon: str | None = None
		self._prev_prompt_tokens: int | None = None
		self.user_turn = 0

	async def stream(
		self,
		messages: list[dict[str, Any]],
		tools: list[dict[str, Any]],
		abort: Any,
	) -> AsyncIterator[Any]:
		from engine.abort import AbortController
		from model.deepseek import _consume_sse_line, _finish_tool_bufs

		try:
			import httpx
		except ImportError:
			httpx = None  # type: ignore

		abort.raise_if_aborted()
		canon = _canon_request(messages, tools)
		lcp_c = _lcp_chars(canon, self._prev_canon) if self._prev_canon else 0
		char_len = len(canon)
		# 无分词器：用「字符 LCP / 本请求字符」× 上轮 prompt_tokens 估 token LCP
		if self._prev_prompt_tokens and self._prev_canon:
			lcp_tok = self._prev_prompt_tokens * (lcp_c / max(len(self._prev_canon), 1))
		else:
			lcp_tok = 0.0
		l_blk = G_BLOCK * int(lcp_tok // G_BLOCK)
		h_prior = RHO * l_blk
		if self._prev_canon is None:
			w_prior = 0  # 第一枪写入以账单为准；先验先记 0，回填 prompt 后再印
		else:
			growth = max(char_len - len(self._prev_canon), 0)
			# keep 追加：多出来的对齐块（字符近似）
			if self._prev_prompt_tokens:
				extra_tok = self._prev_prompt_tokens * (
					growth / max(len(self._prev_canon), 1)
				)
			else:
				extra_tok = growth / 4.0
			w_prior = G_BLOCK * int(extra_tok // G_BLOCK)

		usage_acc: dict[str, Any] | None = None
		body = self._inner._build_body(messages, tools, stream=True)
		body["stream_options"] = {"include_usage": True}
		url = f"{self._inner._base_url}/chat/completions"
		tool_bufs: dict[int, dict[str, str]] = {}

		if httpx is None:
			async for chunk in self._inner.stream(messages, tools, abort):
				yield chunk
			self._finish_record(
				canon,
				char_len,
				lcp_c,
				lcp_tok,
				l_blk,
				h_prior,
				w_prior,
				None,
			)
			return

		async with httpx.AsyncClient(timeout=180.0) as client:
			async with client.stream(
				"POST", url, headers=self._inner._headers(), json=body
			) as resp:
				if resp.status_code >= 400:
					err = await resp.aread()
					raise RuntimeError(
						f"DeepSeek HTTP {resp.status_code}: "
						f"{err.decode('utf-8', errors='replace')}"
					)
				async for line in resp.aiter_lines():
					if isinstance(abort, AbortController):
						abort.raise_if_aborted()
					if not line or not line.startswith("data:"):
						continue
					payload = line[len("data:") :].strip()
					if payload == "[DONE]":
						continue
					try:
						event = json.loads(payload)
					except json.JSONDecodeError:
						continue
					got = _extract_usage(event)
					if got:
						usage_acc = got
					for chunk in _consume_sse_line(line, tool_bufs):
						yield chunk
		for chunk in _finish_tool_bufs(tool_bufs):
			yield chunk

		self._finish_record(
			canon,
			char_len,
			lcp_c,
			lcp_tok,
			l_blk,
			h_prior,
			w_prior,
			usage_acc,
		)

	def _finish_record(
		self,
		canon: str,
		char_len: int,
		lcp_c: int,
		lcp_tok: float,
		l_blk: int,
		h_prior: float,
		w_prior: int,
		usage: dict[str, Any] | None,
	) -> None:
		prompt = None
		hit = None
		miss = None
		comp = None
		if usage:
			prompt = _as_int(usage.get("prompt_tokens"))
			hit = _as_int(usage.get("prompt_cache_hit_tokens"))
			miss = _as_int(usage.get("prompt_cache_miss_tokens"))
			comp = _as_int(usage.get("completion_tokens"))
			if prompt is not None and self._prev_canon is None:
				# 第一枪：写入先验 ≈ 整段按块对齐
				w_prior = G_BLOCK * (prompt // G_BLOCK)
			if prompt is not None and lcp_tok == 0 and self._prev_prompt_tokens:
				pass
		hit_rate = None
		if prompt and hit is not None:
			hit_rate = hit / prompt
		# 官方价：命中 p_r、未命中 p_u、输出 p_o，单位元/百万 token。
		# DeepSeek 无 write 档：发票 W_phys=0（物理 fill 只记 W_prior，不进 C_biz）。
		c_inv = None
		if prompt is not None and hit is not None:
			c_inv = c_biz_yuan(
				prompt=prompt,
				hit=hit,
				out=comp or 0,
				p_r=self.p_r,
				p_u=self.p_u,
				p_o=self.p_o,
				w_phys=0.0,
			)
		x_hat = prompt if prompt is not None else max(int(char_len / 4), 1)
		c_prior = c_biz_yuan(
			prompt=x_hat,
			hit=h_prior,
			out=comp or 0,
			p_r=self.p_r,
			p_u=self.p_u,
			p_o=self.p_o,
			w_phys=0.0,
		)

		rec = CallRecord(
			index=len(self.calls) + 1,
			user_turn=self.user_turn,
			char_len=char_len,
			lcp_chars=lcp_c,
			lcp_token_prior=round(lcp_tok, 1),
			L_blk=l_blk,
			H_prior=round(h_prior, 1),
			W_prior=w_prior,
			prompt_tokens=prompt,
			hit=hit,
			miss=miss,
			completion_tokens=comp,
			hit_rate=round(hit_rate, 4) if hit_rate is not None else None,
			C_biz_prior=round(c_prior, 8) if c_prior is not None else None,
			C_biz_invoice=round(c_inv, 8) if c_inv is not None else None,
			period=self.period,
			p_r=self.p_r,
			p_u=self.p_u,
			p_o=self.p_o,
		)
		self.calls.append(rec)
		self._prev_canon = canon
		if prompt is not None:
			self._prev_prompt_tokens = prompt
		_print_call(rec)


def _as_int(v: Any) -> int | None:
	if v is None:
		return None
	try:
		return int(v)
	except (TypeError, ValueError):
		return None


def _print_call(rec: CallRecord) -> None:
	print()
	print(f"── API #{rec.index}  (用户回合 {rec.user_turn}) ──")
	print(
		f"  公式先验  LCP̃≈{rec.lcp_token_prior} tok  "
		f"L_blk={rec.L_blk}  H=ρ·L_blk={rec.H_prior}  W≈{rec.W_prior}"
	)
	if rec.prompt_tokens is None:
		print("  账单      （流式未带回 usage。确认模型支持 stream_options.include_usage）")
		return
	hit = rec.hit if rec.hit is not None else "?"
	miss = rec.miss if rec.miss is not None else "?"
	rate = f"{rec.hit_rate:.1%}" if rec.hit_rate is not None else "?"
	print(
		f"  账单      prompt={rec.prompt_tokens}  "
		f"hit={hit}  miss={miss}  out={rec.completion_tokens}  命中率={rate}"
	)
	if rec.hit is not None and rec.H_prior:
		delta = rec.hit - rec.H_prior
		print(f"  对照      账单hit − H先验 = {delta:+.1f}")
	print(
		f"  C_biz     先验={rec.C_biz_prior:.6f} 元  账单={rec.C_biz_invoice:.6f} 元"
		if rec.C_biz_invoice is not None
		else f"  C_biz     先验={rec.C_biz_prior:.6f} 元"
	)
	print(
		f"  定价      {rec.period}  "
		f"命中 {rec.p_r}/命中未 {rec.p_u}/输出 {rec.p_o} 元/百万token"
	)


def _print_table(calls: list[CallRecord]) -> None:
	if not calls:
		print("没有记录到任何模型调用。")
		return
	print()
	print("======== KV 命中与费用（§4.7 + DeepSeek 官方价）========")
	hdr = (
		f"{'#':>3} {'回合':>4} {'prompt':>8} {'hit':>8} {'miss':>8} "
		f"{'率':>7} {'账单元':>10} {'先验元':>10}"
	)
	print(hdr)
	sum_inv = 0.0
	for r in calls:
		rate = f"{r.hit_rate:.0%}" if r.hit_rate is not None else "-"
		inv = r.C_biz_invoice
		pri = r.C_biz_prior
		if inv is not None:
			sum_inv += inv
		print(
			f"{r.index:>3} {r.user_turn:>4} "
			f"{_fmt(r.prompt_tokens):>8} {_fmt(r.hit):>8} {_fmt(r.miss):>8} "
			f"{rate:>7} "
			f"{inv if inv is not None else float('nan'):>10.6f} "
			f"{pri if pri is not None else float('nan'):>10.6f}"
		)
	print(f"合计账单 ≈ {sum_inv:.6f} 元")
	print()
	print("读法：keep 且前缀从位置 0 起未改时，后一轮 hit 应接近上轮 prompt 按 64 对齐再乘 0.95。")
	print("第一枪 hit 通常 ≈0（整段 miss）。费用按官方 元/百万 token，无写缓存费。")


def _fmt(v: int | None) -> str:
	return "-" if v is None else str(v)


def _build_engine(spy: CacheSpyClient, *, cwd: str, max_turns: int, model: str):
	from engine.query_engine import QueryEngine, QueryEngineConfig
	from prompt.assembler import PromptAssembler
	from tools.catalog import build_default_registry

	registry = build_default_registry(cwd=cwd)
	config: QueryEngineConfig = {
		"cwd": cwd,
		"tools": registry,
		"model_client": spy,  # type: ignore[typeddict-item]
		"prompt_assembler": PromptAssembler(),
		"append_system_prompt": "",
		"user_specified_model": model,
		"max_turns": max_turns,
		"session_id": "kv-cache-probe",
	}
	return QueryEngine(config)


async def _one_user_turn(engine: Any, spy: CacheSpyClient, text: str) -> None:
	from msgtypes.events import (
		AssistantDelta,
		FinalEvent,
		ResultEvent,
		StoppedEvent,
		ToolCallEvent,
		ToolResultEvent,
	)

	spy.user_turn += 1
	print()
	print(f">>>>>>>> 用户[{spy.user_turn}]: {text}")
	async for ev in engine.submit(text):
		if isinstance(ev, AssistantDelta):
			sys.stdout.write(ev.text)
			sys.stdout.flush()
		elif isinstance(ev, ToolCallEvent):
			print(f"\n  [tool] {ev.name} {json.dumps(ev.input, ensure_ascii=False)[:240]}")
		elif isinstance(ev, ToolResultEvent):
			preview = (ev.output or "")[:200].replace("\n", " ")
			print(f"  [result{'!' if ev.is_error else ''}] {ev.name}: {preview}")
		elif isinstance(ev, FinalEvent):
			if ev.text:
				print()
		elif isinstance(ev, StoppedEvent):
			print(f"\n  [stopped] {ev.reason}")
		elif isinstance(ev, ResultEvent) and ev.is_error:
			print(f"\n  [result-error] {ev.subtype} {ev.stop_reason}")


DEMO_TURNS = [
	"只用一句话回答：你是谁。不要调用任何工具。",
	"继续，还是一句话：不要重复自我介绍，只说你会帮我看代码。不要调用工具。",
	"用 Glob 找出 python/engine/query_loop.py，再 Read 它的前 60 行。",
	"根据刚才读到的内容，用两句话说明 query_loop 在调用模型之前做了哪一步。不要再读文件。",
]


async def async_main(args: argparse.Namespace) -> int:
	_load_dotenv()
	os.environ.setdefault("XEYO_NO_SESSION_PERSISTENCE", "1")
	os.environ["DEEPSEEK_MODEL"] = args.model
	if not os.environ.get("DEEPSEEK_API_KEY") and not os.environ.get("XEYO_MODEL_API_KEY"):
		print("缺少 DEEPSEEK_API_KEY（或 XEYO_MODEL_API_KEY）。写入环境变量或仓库 .env。")
		return 2
	if not os.environ.get("DEEPSEEK_API_KEY") and os.environ.get("XEYO_MODEL_API_KEY"):
		os.environ["DEEPSEEK_API_KEY"] = os.environ["XEYO_MODEL_API_KEY"]

	from model.deepseek import DeepSeekModelClient

	inner = DeepSeekModelClient(model=args.model)
	slot, p_r, p_u, p_o = resolve_prices(args.model, args.period)
	spy = CacheSpyClient(inner, period=slot, p_r=p_r, p_u=p_u, p_o=p_o)
	cwd = os.path.abspath(args.cwd)
	engine = _build_engine(spy, cwd=cwd, max_turns=args.max_turns, model=args.model)

	print(f"model={inner._model}  base={inner._base_url}  cwd={cwd}")
	print("对话走 QueryEngine.submit → query_loop（未改引擎代码）。")
	print(f"公式：g={G_BLOCK}, ρ={RHO}, 命中 H=ρ·g⌊LCP/g⌋")
	print(
		f"定价：{slot}  命中 {p_r} / 未命中 {p_u} / 输出 {p_o} 元/百万token"
		f"（2026-08-17 起；高峰 9–12、14–18 北京时间）"
	)

	if args.interactive:
		print("交互模式：输入内容回车发送，空行或 /q 结束。")
		while True:
			try:
				line = input("\nyou> ").strip()
			except EOFError:
				break
			if not line or line in ("/q", "/quit", "exit"):
				break
			await _one_user_turn(engine, spy, line)
	else:
		turns = list(DEMO_TURNS)
		if args.turns:
			turns = args.turns
		for text in turns:
			await _one_user_turn(engine, spy, text)

	_print_table(spy.calls)
	if args.json:
		out = Path(args.json)
		out.write_text(
			json.dumps([asdict(c) for c in spy.calls], ensure_ascii=False, indent=2),
			encoding="utf-8",
		)
		print(f"已写入 {out}")
	return 0


def main() -> None:
	parser = argparse.ArgumentParser(description="XEYO 对话 + DeepSeek KV 命中对照 §4.7")
	parser.add_argument("--model", default="deepseek-v4-flash")
	parser.add_argument(
		"--period",
		choices=("auto", "peak", "offpeak"),
		default="auto",
		help="auto=按北京时间选高峰/空闲；也可强制 peak / offpeak",
	)
	parser.add_argument("--cwd", default=str(REPO))
	parser.add_argument("--interactive", action="store_true")
	parser.add_argument("--max-turns", type=int, default=16)
	parser.add_argument("--json", default="", help="把每枪 usage 写成 JSON")
	parser.add_argument(
		"--turns",
		nargs="*",
		help="自定义用户句（非交互）。省略则跑内置 4 句 demo。",
	)
	args = parser.parse_args()
	raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
	main()
