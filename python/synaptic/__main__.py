"""CLI：``py -3.11 -m synaptic <replay|single|check|levels>``

纯离线，不联网、不写生产数据；产物落在 ``--out`` 指定的目录。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from synaptic.assemble import pick_level
from synaptic.metrics import assert_no_llm_dependency, determinism_digest
from synaptic.project import default_params, project
from synaptic.replay import (
	default_sessions_dir,
	iter_session_files,
	load_jsonl,
	run_session,
	_as_api_message,
)
from synaptic.report import (
	aggregate,
	build_report,
	cohort_aggregates,
	render_markdown,
	write_report,
)
from synaptic.types import LEVELS, MODE_APPEND_ONLY, MODE_CLOSURE, WscParams


def _modes(raw: str) -> list[str]:
	out = [m.strip() for m in (raw or "").split(",") if m.strip()]
	return out or [MODE_CLOSURE]


def main(argv: list[str] | None = None) -> int:
	ap = argparse.ArgumentParser(prog="synaptic", description="突触压缩 WSC 离线工具")
	sub = ap.add_subparsers(dest="cmd", required=True)

	p_rp = sub.add_parser("replay", help="在真实会话 JSONL 上跑基线 vs WSC")
	p_rp.add_argument("--sessions-dir", default=None)
	p_rp.add_argument("--out", default="synaptic_out")
	p_rp.add_argument("--level", default="Medium+", choices=LEVELS)
	p_rp.add_argument("--mode", default=f"{MODE_CLOSURE},{MODE_APPEND_ONLY}")
	p_rp.add_argument("--limit", type=int, default=0, help="只跑前 N 个会话（0=全部）")
	p_rp.add_argument(
		"--sample-turns",
		type=int,
		default=0,
		help=(
			"每会话抽样回合数（0=全部，**默认必须为 0**）。"
			"抽样会把相邻两轮之间的 x_prev 拉到 N 轮之前，命中率随即被系统性压低："
			"199 回合会话 append_only 逐回合 0.731 / 抽样 12 → 0.051（差 14 倍）。"
			"只在明确要「抽样口径」时使用，报告会标注。"
		),
	)
	p_rp.add_argument("--min-messages", type=int, default=8)
	p_rp.add_argument(
		"--no-stable-order",
		action="store_true",
		help="关掉规则 2 的动态段落排序（回退固定先验序），用于 A/B 对照",
	)
	p_rp.add_argument(
		"--no-journal",
		action="store_true",
		help="关掉规则 8 的日志布局（回退分段仪表盘），用于 A/B 对照",
	)
	p_rp.add_argument("--md", action="store_true", help="把 Markdown 报告打到 stdout")

	p_one = sub.add_parser("single", help="单会话投影明细（含热层全文与审计表）")
	p_one.add_argument("file")
	p_one.add_argument("--level", default="Medium+", choices=LEVELS)
	p_one.add_argument("--mode", default=MODE_CLOSURE, choices=[MODE_CLOSURE, MODE_APPEND_ONLY])
	p_one.add_argument("--turn", type=int, default=-1, help="第几个用户回合（-1=最后一个）")
	p_one.add_argument("--show-hot", action="store_true")
	p_one.add_argument("--show-audit", action="store_true")

	sub.add_parser("check", help="静态检查 + 确定性自检")

	p_lv = sub.add_parser("levels", help="打印水位分档")
	p_lv.add_argument("--ratio", type=float, default=0.0)

	args = ap.parse_args(argv)

	if args.cmd == "replay":
		return _replay(args)
	if args.cmd == "single":
		return _single(args)
	if args.cmd == "check":
		return _check()
	if args.cmd == "levels":
		if args.ratio > 0:
			print(pick_level(args.ratio))
			return 0
		for lv in LEVELS:
			p = default_params(lv)
			print(f"{lv}\tbudget={p.hot_budget_tokens}\thops={p.closure_hops}\tcards={p.max_cards}")
		return 0
	return 2


def _replay(args) -> int:
	root = Path(args.sessions_dir) if args.sessions_dir else default_sessions_dir()
	files = iter_session_files(root)
	if args.limit:
		files = files[: args.limit]
	if not files:
		print(f"no session jsonl under {root}")
		return 2

	aggs = []
	all_records: dict[str, list] = {}
	flags = []
	if args.no_stable_order:
		flags.append("no-stable-order")
	if args.no_journal:
		flags.append("no-journal")
	tag = f"（{'+'.join(flags)}）" if flags else ""
	if args.sample_turns:
		print(
			f"⚠ 抽样口径：--sample-turns={args.sample_turns}。命中率不可与逐回合结果比较"
			"（x_prev 被拉到 N 轮之前，等价于每轮冷启动）。",
			file=sys.stderr,
		)
	for mode in _modes(args.mode):
		pset = WscParams(
			mode=mode,
			stable_prefix_ordering=not args.no_stable_order,
			journal_layout=not args.no_journal,
		).for_level(args.level)
		records = []
		for i, f in enumerate(files):
			records.append(
				run_session(
					f,
					level=args.level,
					mode=mode,
					min_prefix_messages=args.min_messages,
					sample_turns=args.sample_turns,
					params=pset,
					# 生产触发口径旁路开关（默认关；见 replay.run_session 的说明与 docs §13.8）。
					# 用环境变量而非 CLI 标志：这是**评测用**开关，不进产品命令行面。
					#   XEYO_WSC_TRIGGER_RATIO=0.8  XEYO_WSC_CONTEXT_LIMIT=131072
					trigger_ratio=float(os.environ.get("XEYO_WSC_TRIGGER_RATIO") or 0),
					context_limit_tokens=int(os.environ.get("XEYO_WSC_CONTEXT_LIMIT") or 0),
				)
			)
			if (i + 1) % 25 == 0:
				print(f"  [{mode}] {i + 1}/{len(files)} ...", file=sys.stderr)
		all_records[mode] = records
		aggs.append(
			aggregate(records, label=f"WSC/{args.level}/{mode}{tag}", level=args.level, mode=mode)
		)
		for a in aggs[-1:]:
			s = a.summary()
			print(
				f"[{mode}] sessions={s.get('sessions')} turns={s.get('turns')} "
				f"skipped={s.get('skipped')} errors={s.get('errors')}"
			)

	cohorts: list = []
	mode_notes: dict = {}
	for mode in _modes(args.mode):
		cohorts.extend(cohort_aggregates(all_records[mode], level=args.level, mode=mode))
		sub = [a for a in aggs if a.mode == mode]
		if sub:
			mode_notes[mode] = sub[0].summary()

	det = _determinism_probe(files)
	rep = build_report(
		aggs,
		corpus=str(root),
		n_files=len(files),
		determinism=det,
		cohorts=cohorts,
		mode_notes=mode_notes,
		sampling={
			"sample_turns": int(args.sample_turns),
			"decimated": bool(args.sample_turns),
			"stable_prefix_ordering": not args.no_stable_order,
			"journal_layout": not args.no_journal,
		},
	)
	jp, mp = write_report(rep, Path(args.out))
	print(jp)
	print(mp)
	if args.md:
		print(render_markdown(rep))
	return 0


def _determinism_probe(files: list[Path], n: int = 5) -> dict:
	"""确定性自检：同输入跑两次，比 digest。

从**最大的**几个会话里抽样——按文件名序取前几个会全是短会话，
探测等于没做（首轮实测 checked_sessions=1）。
	"""
	try:
		cands = sorted(files, key=lambda p: p.stat().st_size, reverse=True)[:n]
	except OSError:
		cands = files[:n]
	out: dict = {"checked_sessions": 0, "identical": 0, "mismatch": []}
	for f in cands:
		api = [_as_api_message(r) for r in load_jsonl(f)]
		if len(api) < 8:
			continue
		try:
			from engine.compact import keep_tail_cut
		except Exception:  # noqa: BLE001
			return {"error": "engine.compact unavailable"}
		region_end = keep_tail_cut(api)
		if region_end <= 1:
			continue
		p = default_params("Medium+")
		d1 = determinism_digest(project(api, region_end=region_end, params=p).result)
		d2 = determinism_digest(project(api, region_end=region_end, params=p).result)
		out["checked_sessions"] += 1
		if d1 == d2:
			out["identical"] += 1
		else:
			out["mismatch"].append({"session": f.stem, "d1": d1, "d2": d2})
	return out


def _single(args) -> int:
	from engine.compact import keep_tail_cut

	f = Path(args.file)
	api = [_as_api_message(r) for r in load_jsonl(f)]
	if not api:
		print("empty session")
		return 2
	from synaptic.replay import user_turn_starts

	starts = user_turn_starts(api)
	t = args.turn if args.turn >= 0 else len(starts) - 1
	end = starts[t + 1] if t + 1 < len(starts) else len(api)
	prefix = api[:end]
	region_end = keep_tail_cut(prefix)

	p = default_params(args.level, args.mode)
	proj = project(prefix, region_end=region_end, params=p, session=f.stem)
	s = proj.result
	print(
		json.dumps(
			{
				"session": f.stem,
				"messages": len(prefix),
				"region_end": region_end,
				"level": s.level,
				"mode": s.mode,
				"base_tokens": s.base_tokens,
				"hot_tokens": s.hot.tokens,
				"rebuilt": s.rebuilt,
				"kept": len(s.hot.kept_nodes),
				"pruned": len(s.hot.pruned_nodes),
				"cards": len(s.hot.cards),
				"pins": len(s.hot.pins),
				"trace": s.trace,
			},
			ensure_ascii=False,
			indent=2,
		)
	)
	if args.show_hot:
		print("\n=== HOT ===")
		print(proj.text)
	if args.show_audit:
		print("\n=== AUDIT ===")
		for row in proj.audit:
			print(json.dumps(row, ensure_ascii=False))
	return 0


def _check() -> int:
	problems = assert_no_llm_dependency()
	print(json.dumps({"forbidden_imports": problems}, ensure_ascii=False, indent=2))
	return 1 if problems else 0


if __name__ == "__main__":
	sys.exit(main())
