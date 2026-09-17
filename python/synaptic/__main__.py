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
	run_sessions_parallel,
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
	p_rp.add_argument(
		"--jobs",
		type=int,
		default=1,
		help=(
			"按会话并行度（1=串行）。会话之间独立 ⇒ 聚合指标与串行完全一致；"
			"⚠️ 但 latency_ms 是进程内 perf_counter，>1 会混入 CPU 争用 ⇒ "
			"**只有 --jobs 1 才是串行延迟基线**（实际值会写进报告 sampling.jobs）。"
		),
	)
	p_rp.add_argument(
		"--compact-model",
		default=os.environ.get("XEYO_WSC_COMPACT_MODEL", "legacy"),
		choices=["legacy", "adopted"],
		help=(
			"压缩口径。legacy（默认，历史口径）= 每回合尝试压缩、未过闸发整段原文；"
			"adopted = 收养后生产语义（一旦压过就一直发紧凑投影，水位基准=上一枪实际发送的 "
			"prompt tokens）。两个档的数字**不可混用**，见 docs §15。"
		),
	)
	p_rp.add_argument(
		"--fold-cadence",
		default=os.environ.get("XEYO_WSC_FOLD_CADENCE", "always"),
		choices=["always", "econ"],
		help=(
			"折叠节奏。always（默认）= 由调用方判据决定何时折（生产水位 / 评测台 trigger_ratio）；"
			"econ = **成本驱动**（synaptic.cadence 判据：R×saved ≥ price_ratio×margin×transition）。"
			"实测两者差 2.6 倍总成本（docs §15.9.2）⇒ 生产应走 econ。"
		),
	)
	p_rp.add_argument(
		"--dump-turns",
		action="store_true",
		help=(
			"额外落盘逐回合明细 turns_<mode>.jsonl（含逐回合针命中/命中率/延迟/"
			"两道闸标记）。用途：跨触发口径比针时必须**按同一批回合对齐分母**——"
			"只看汇总会把'样本退出'读成'指标退化'（第七轮踩过）。"
		),
	)

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
	jobs = max(1, int(getattr(args, "jobs", 1) or 1))
	for mode in _modes(args.mode):
		pset = WscParams(
			mode=mode,
			stable_prefix_ordering=not args.no_stable_order,
			journal_layout=not args.no_journal,
			fold_cadence=str(getattr(args, "fold_cadence", "always") or "always"),
		).for_level(args.level)
		# 评测用参数覆盖（不进产品命令行面）：`[PATHS]` 配额与折叠边际的扫描用。
		#   XEYO_WSC_PATH_LIMIT=48  XEYO_WSC_PATH_BUDGET=512  XEYO_WSC_FOLD_MARGIN=0.5
		_pl = os.environ.get("XEYO_WSC_PATH_LIMIT", "").strip()
		_pb = os.environ.get("XEYO_WSC_PATH_BUDGET", "").strip()
		_fm = os.environ.get("XEYO_WSC_FOLD_MARGIN", "").strip()
		if _pl or _pb or _fm:
			import dataclasses as _dc

			pset = _dc.replace(
				pset,
				path_index_limit=int(_pl) if _pl else pset.path_index_limit,
				path_index_budget_tokens=int(_pb) if _pb else pset.path_index_budget_tokens,
				fold_margin=float(_fm) if _fm else pset.fold_margin,
			)
		# 生产触发口径旁路开关（默认关；见 replay.run_session 的说明与 docs §13.8）。
		# 用环境变量而非 CLI 标志：这是**评测用**开关，不进产品命令行面。
		#   XEYO_WSC_TRIGGER_RATIO=0.8  XEYO_WSC_CONTEXT_LIMIT=131072
		# 句柄形态旁路（评测用，不进产品命令行面）：
		#   XEYO_WSC_HANDLE_STYLE=read  XEYO_WSC_VIEW_DIR=<dir>
		# `read` 档渲染 `Read(file_path=…, offset=…, limit=…)`，必须给视图目录。
		_hs = (os.environ.get("XEYO_WSC_HANDLE_STYLE", "") or "").strip() or "expand"
		_vd = (os.environ.get("XEYO_WSC_VIEW_DIR", "") or "").strip()
		# 引用形态：`XEYO_WSC_VIEW_REF_BASE=<dir>` 时渲染成相对该目录的路径（= 模型侧 Read 的 cwd）。
		# 不设 = 绝对路径。两者热层 token 差很多 ⇒ 跨形态数字不可混用（报告 sampling 留痕）。
		_vb = (os.environ.get("XEYO_WSC_VIEW_REF_BASE", "") or "").strip()
		kw = dict(
			level=args.level,
			mode=mode,
			min_prefix_messages=args.min_messages,
			sample_turns=args.sample_turns,
			params=pset,
			handle_style=_hs,
			view_dir=_vd,
			view_ref_base=_vb,
			trigger_ratio=float(os.environ.get("XEYO_WSC_TRIGGER_RATIO") or 0),
			context_limit_tokens=int(os.environ.get("XEYO_WSC_CONTEXT_LIMIT") or 0),
			compact_model=str(getattr(args, "compact_model", "legacy") or "legacy"),
		)
		if jobs > 1:
			print(
				f"  [{mode}] 并行 jobs={jobs} over {len(files)} sessions ...",
				file=sys.stderr,
			)
			records = run_sessions_parallel(files, workers=jobs, **kw)
		else:
			records = []
			for i, f in enumerate(files):
				records.append(run_session(f, **kw))
				if (i + 1) % 25 == 0:
					print(f"  [{mode}] {i + 1}/{len(files)} ...", file=sys.stderr)
		all_records[mode] = records
		if getattr(args, "dump_turns", False):
			_dump_turns(Path(args.out), mode, records)
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

	det = _determinism_probe(files, jobs=jobs)
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
			# 并行度必须留痕：latency_ms 只有 jobs=1 时才是串行基线。
			"jobs": jobs,
			"latency_serial_baseline": jobs == 1,
			# 压缩口径必须留痕：legacy 与 adopted 的 L/H/成本/针**不可跨档相减**
			# （legacy 在未过闸回合发整段原文，adopted 发紧凑投影）。
			"compact_model": str(getattr(args, "compact_model", "legacy") or "legacy"),
			"fold_cadence": pset.fold_cadence,
			"fold_margin": pset.fold_margin,
			"fold_price_ratio": pset.fold_price_ratio,
			"path_index_limit": pset.path_index_limit,
			"path_index_budget_tokens": pset.path_index_budget_tokens,
			"trigger_ratio": float(os.environ.get("XEYO_WSC_TRIGGER_RATIO") or 0),
			"context_limit_tokens": int(os.environ.get("XEYO_WSC_CONTEXT_LIMIT") or 0),
			# 句柄形态必须留痕：`read` 形态的引用（含视图路径）比 `expand` 长，
			# 热层 token 因此不同 ⇒ 跨形态的成本数字不可混用。
			"handle_style": (os.environ.get("XEYO_WSC_HANDLE_STYLE", "") or "").strip() or "expand",
			"view_dir": (os.environ.get("XEYO_WSC_VIEW_DIR", "") or "").strip(),
			"view_ref_base": (os.environ.get("XEYO_WSC_VIEW_REF_BASE", "") or "").strip(),
		},
	)
	jp, mp = write_report(rep, Path(args.out))
	print(jp)
	print(mp)
	if args.md:
		print(render_markdown(rep))
	return 0


def _dump_turns(outdir: Path, mode: str, records: list) -> Path:
	"""逐回合明细落盘（针分母对齐/归因用）。

	为什么需要它：汇总层的 `needle_survival` 只在「该针有样本的回合」上取均值，
	不同触发口径下**样本群体本身就变了**（生产口径下短/中会话从未压缩 ⇒ 无样本 ⇒
	自动退出分母）。只看汇总会把"样本退出"读成"指标退化"（第七轮实测：汇总报 −10pp，
	同群体实为 −4.95pp）。有逐回合行才能按**同一批回合**严格对齐。
	"""
	outdir.mkdir(parents=True, exist_ok=True)
	path = outdir / f"turns_{mode}.jsonl"
	with path.open("w", encoding="utf-8") as fh:
		for rec in records:
			for t in rec.turns:
				row = t.as_row()
				row["session"] = rec.session
				row["mode"] = rec.mode
				fh.write(json.dumps(row, ensure_ascii=False) + "\n")
	print(f"  [{mode}] turns -> {path}", file=sys.stderr)
	return path


def _probe_one(path_str: str) -> dict:
	"""单会话确定性探测（**模块级** ⇒ 可 pickle 进进程池）。

	原先这段是 `_determinism_probe` 里的串行 for —— 16 核机器上跑 4 jobs 只拿到
	1.58x，尾巴就出在这里：模式循环已经并行完了，之后还要串行重放 5 个**最大**
	会话各两遍。抽成模块级函数即可并行，行为逐字节不变。
	"""
	f = Path(path_str)
	api = [_as_api_message(r) for r in load_jsonl(f)]
	if len(api) < 8:
		return {"session": f.stem, "checked": False}
	try:
		from engine.compact import keep_tail_cut
	except Exception:  # noqa: BLE001
		return {"session": f.stem, "checked": False, "error": "engine.compact unavailable"}
	region_end = keep_tail_cut(api)
	if region_end <= 1:
		return {"session": f.stem, "checked": False}
	p = default_params("Medium+")
	d1 = determinism_digest(project(api, region_end=region_end, params=p).result)
	d2 = determinism_digest(project(api, region_end=region_end, params=p).result)
	return {"session": f.stem, "checked": True, "identical": d1 == d2, "d1": d1, "d2": d2}


def _determinism_probe(files: list[Path], n: int = 5, jobs: int = 1) -> dict:
	"""确定性自检：同输入跑两次，比 digest。

从**最大的**几个会话里抽样——按文件名序取前几个会全是短会话，
探测等于没做（首轮实测 checked_sessions=1）。

``jobs > 1`` 时并行（每会话纯读 + 纯函数，不影响判定）。
	"""
	try:
		cands = sorted(files, key=lambda p: p.stat().st_size, reverse=True)[:n]
	except OSError:
		cands = files[:n]
	payload = [str(p) for p in cands]
	if jobs > 1 and len(payload) > 1:
		from concurrent.futures import ProcessPoolExecutor

		with ProcessPoolExecutor(max_workers=min(jobs, len(payload))) as ex:
			results = list(ex.map(_probe_one, payload, chunksize=1))
	else:
		results = [_probe_one(x) for x in payload]

	out: dict = {"checked_sessions": 0, "identical": 0, "mismatch": []}
	for r in results:
		if r.get("error"):
			return {"error": r["error"]}
		if not r.get("checked"):
			continue
		out["checked_sessions"] += 1
		if r.get("identical"):
			out["identical"] += 1
		else:
			out["mismatch"].append(
				{"session": r["session"], "d1": r.get("d1"), "d2": r.get("d2")}
			)
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
