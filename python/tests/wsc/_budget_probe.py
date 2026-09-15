"""只读探针：热层各段的**未计预算** token 账目，用于校准「固定段 / 主链」双闸。

背景：``hot_budget_tokens`` 原先只闸 ``kept`` 的选择；``[REQUESTS]`` / ``[DECISIONS]`` /
``[PRUNED]`` / ``[WORKING SET]`` 都是「先渲染、后入账」，于是热层实测中位数超预算。
本探针把紧凑渲染（``_segment_groups``，即重冻结后落盘的那一版）逐段量出来，
再给若干候选固定段预算算「多少回合不用截断」。

口径：
* 全部按``node_token_len(line) + 1``（行尾换行）计，与 ``project.py`` 的 ``pin_tokens`` 一致；
* 只统计**区域内**的紧凑渲染，不含日志累积（日志另有 ``journal_growth_tokens`` 独立预算）；
* 零花费、只读，不写任何状态。

用法：
    python tests/wsc/_budget_probe.py <session.jsonl>
    python tests/wsc/_budget_probe.py <sessions-dir> --sample 60
"""

from __future__ import annotations

import argparse
import statistics as stats
import sys
from pathlib import Path

def _repo_root() -> Path:
	return Path(__file__).resolve().parents[3]

ROOT = _repo_root()
if str(ROOT / "python") not in sys.path:
	sys.path.insert(0, str(ROOT / "python"))

from engine.compact import keep_tail_cut  # noqa: E402
from synaptic.assemble import (  # noqa: E402
	H_CONSTRAINTS,
	H_DECISIONS,
	H_MAIN,
	H_NEXT,
	H_PRUNED,
	H_REQUESTS,
	H_TODO,
	H_UNRESOLVED,
	H_WORKING,
	_segment_groups,
)
from synaptic.project import default_params, project  # noqa: E402
from synaptic.replay import _as_api_message, load_jsonl, user_turn_starts  # noqa: E402
from synaptic.textutil import node_token_len  # noqa: E402

FIXED_SEGS = (H_CONSTRAINTS, H_UNRESOLVED, H_TODO, H_WORKING, H_REQUESTS, H_NEXT)
MAIN_SEGS = (H_MAIN,)
CARD_SEGS = (H_DECISIONS, H_PRUNED)


def _seg_tokens(items) -> int:
	return sum(node_token_len(line) + 1 for _, line in items)


class Acc:
	def __init__(self) -> None:
		self.turns = 0
		self.seg: dict[str, list[int]] = {}
		self.fixed: list[int] = []
		self.main: list[int] = []
		self.cards: list[int] = []
		self.total: list[int] = []
		self.req_lines: list[int] = []
		self.req_budget_ok: dict[int, int] = {}

	def add(self, groups: dict) -> None:
		self.turns += 1
		for h in FIXED_SEGS + MAIN_SEGS + CARD_SEGS:
			self.seg.setdefault(h, []).append(_seg_tokens(groups.get(h, ())))
		fx = sum(self.seg[h][-1] for h in FIXED_SEGS)
		mn = sum(self.seg[h][-1] for h in MAIN_SEGS)
		cd = sum(self.seg[h][-1] for h in CARD_SEGS)
		self.fixed.append(fx)
		self.main.append(mn)
		self.cards.append(cd)
		self.total.append(fx + mn + cd)
		self.req_lines.append(len(groups.get(H_REQUESTS, ())))


def _analyze_file(path: Path, acc: Acc, params, max_turns: int) -> int:
	api = [_as_api_message(r) for r in load_jsonl(path)]
	starts = user_turn_starts(api)
	if not starts:
		return 0
	turns = list(range(len(starts)))
	if max_turns and len(turns) > max_turns:
		step = len(turns) / float(max_turns)
		turns = [turns[min(len(turns) - 1, int(i * step))] for i in range(max_turns)]
	for t in turns:
		end = starts[t + 1] if t + 1 < len(starts) else len(api)
		prefix = api[:end]
		region_end = keep_tail_cut(prefix)
		if region_end <= 1:
			continue
		try:
			proj = project(prefix, region_end=region_end, params=params, session=path.stem)
			groups = _segment_groups(
				proj.graph,
				proj.seeds,
				proj.result.hot.pins,
				proj.result.hot.file_states,
				proj.result.hot.cards,
				proj.result.hot.kept_nodes,
				params,
				region_end=region_end,
			)
			acc.add(groups)
		except Exception as exc:  # noqa: BLE001
			acc.seg.setdefault(f"error:{type(exc).__name__}", []).append(0)
	return len(turns)


def _line(label: str, xs: list[int]) -> str:
	if not xs:
		return f"{label:16} (empty)"
	return (
		f"{label:16} n={len(xs):5d} med={int(stats.median(xs)):6d} "
		f"p90={int(sorted(xs)[int(len(xs) * 0.9)]):6d} "
		f"mean={int(stats.fmean(xs)):6d} max={max(xs):6d} sum={sum(xs):9d}"
	)


def main(argv: list[str]) -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("target", help="session.jsonl 或 sessions 目录")
	ap.add_argument("--sample", type=int, default=0, help="目录模式：抽样会话数；0=全部")
	ap.add_argument("--max-turns", type=int, default=0, help="每个会话最多回合数；0=全部")
	ap.add_argument("--level", default="Medium+")
	args = ap.parse_args(argv)

	target = Path(args.target)
	if target.is_file():
		files = [target]
	elif target.is_dir():
		allf = sorted(target.glob("*.jsonl"))
		if args.sample and len(allf) > args.sample:
			step = len(allf) / float(args.sample)
			files = [allf[min(len(allf) - 1, int(i * step))] for i in range(args.sample)]
		else:
			files = allf
	else:
		print(f"no sessions: {target}")
		return 2

	params = default_params(args.level, "closure")
	acc = Acc()
	for f in files:
		_analyze_file(f, acc, params, args.max_turns)

	print(f"target={target} level={args.level} files={len(files)} turns={acc.turns}")
	print("=== per-section ledger (compact rendering, tok) ===")
	for h in FIXED_SEGS:
		print(_line(h, acc.seg.get(h, [])))
	for h in MAIN_SEGS:
		print(_line(h, acc.seg.get(h, [])))
	for h in CARD_SEGS:
		print(_line(h, acc.seg.get(h, [])))
	print("--- aggregates ---")
	print(_line("fixed(pin+ws+req)", acc.fixed))
	print(_line("main", acc.main))
	print(_line("cards", acc.cards))
	print(_line("total", acc.total))
	print(_line("req_lines", acc.req_lines))

	total = int(params.hot_budget_tokens)
	print(f"=== candidate split sweep (total budget = {total}) ===")
	print(f"{'fixed_budget':>12} {'main_budget':>11} {'fixed_fits':>10} {'main_fits':>9} {'both':>7}")
	for fx in (600, 900, 1200, 1500, 1800, 2100, 2400, 2700):
		mn = total - fx
		ff = sum(1 for v in acc.fixed if v <= fx) / max(1, len(acc.fixed))
		mf = sum(1 for v in acc.main if v <= mn) / max(1, len(acc.main))
		bb = sum(
			1
			for a, b in zip(acc.fixed, acc.main)
			if a <= fx and b <= mn
		) / max(1, len(acc.fixed))
		print(f"{fx:12d} {mn:11d} {ff:10.3f} {mf:9.3f} {bb:7.3f}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main(sys.argv[1:]))
