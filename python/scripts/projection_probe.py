"""projection_probe — 实测「投影长度 / 上下文窗口」占比曲线。

只读、零 LLM、零费用：从转录 JSONL 重建消息，逐 assistant 调用用 production
默认 project 模式（project_c0c1，不 patch v61）驱动 project_for_model，
逐轮统计投影 token 数，对比 context_limit 得到占比。

用法（在 python/ 下）:
  py -3.11 -m scripts.projection_probe <session_id> [context_limit]
context_limit 缺省 = params.window_tokens（128k）；传入真实窗口则按真实口径算占比。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))


def _load(session_id: str) -> list[dict]:
	from session.hydrate import message_from_row
	from session.record_transcript import load_transcript, transcript_read_paths
	from session.persistence import transcript_path

	rows: list[dict] = []
	try:
		for p in transcript_read_paths(transcript_path(session_id)):
			rows.extend(load_transcript(p))
	except Exception as exc:  # noqa: BLE001
		print(f"[warn] transcript read: {exc}")
	out: list[dict] = []
	for r in rows:
		m = message_from_row(r)
		if m is not None:
			out.append(m.__dict__)
	return out


def main() -> int:
	import argparse

	ap = argparse.ArgumentParser()
	ap.add_argument("session_id")
	ap.add_argument("context_limit", nargs="?", default=None, type=int)
	args = ap.parse_args()

	from engine.query_loop import _projected_tokens
	from memory.runtime import project_for_model
	from memory.simulator.params import load_params
	from memory.working import WorkingSnapshot, hydrate

	messages = _load(args.session_id)
	print(f"[session] {args.session_id}  messages={len(messages)}")
	if not messages:
		return 0

	p = load_params()
	win = int(args.context_limit) if args.context_limit else int(p.window_tokens)
	print(f"context_limit = {win}")

	working = hydrate(args.session_id)
	if not working.session_id:
		working = WorkingSnapshot(session_id=args.session_id)

	call_idxs = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
	rows: list[tuple[int, int, float]] = []
	for idx in call_idxs:
		try:
			proj = project_for_model(
				messages[:idx],
				working,
				remaining_turns=8,
				include_memory_index=False,
			)
		except Exception as exc:  # noqa: BLE001
			print(f"[skip] idx={idx} {exc}")
			continue
		tok = _projected_tokens(proj)
		rows.append((idx, tok, tok / win))

	print("\n# 逐轮投影长度")
	print(f"{'turn':>5} {'proj_tok':>9} {'占比':>7}")
	last = 0.0
	for idx, tok, ratio in rows:
		flag = ""
		if abs(ratio - last) > 0.005:
			flag = " *"
		print(f"{idx:>5} {tok:>9} {ratio*100:>6.1f}%{flag}")
		last = ratio

	if rows:
		toks = [r[1] for r in rows]
		ratios = [r[2] for r in rows]
		print("\n# 汇总")
		print(f"轮数               = {len(rows)}")
		print(f"投影token  min/max = {min(toks)}/{max(toks)}")
		print(f"占比      min/max = {min(ratios)*100:.1f}%/{max(ratios)*100:.1f}%")
		print(f"占比      mean    = {sum(ratios)/len(ratios)*100:.1f}%")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
