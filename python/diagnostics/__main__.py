"""``py -3.11 -m diagnostics`` —— 无 GUI 的查询与导出入口。

只读诊断产物与既有账本；除 ``pin`` / ``verifier`` / ``capture`` 外不写任何东西，
也不发模型请求。
"""

from __future__ import annotations

import argparse
import json
import sys

from diagnostics import store
from diagnostics.capture import capture_enabled, set_capture_enabled
from diagnostics.collect import collect_run, list_runs
from diagnostics.identity import Finding
from diagnostics.loss_chain import trace_fact
from diagnostics.pins import pin_run, record_verifier
from diagnostics.report import build_report, save_report, to_markdown
from diagnostics.rules import evaluate_run


def _emit(text: str) -> None:
	# Windows 控制台默认 GBK，中文与货币符号会直接抛 UnicodeEncodeError。
	try:
		sys.stdout.write(text + "\n")
	except UnicodeEncodeError:
		sys.stdout.buffer.write((text + "\n").encode("utf-8", "replace"))


def _findings_rows(findings: list[Finding]) -> list[str]:
	label = {"confirmed_fault": "已确认", "suspected_cause": "疑似", "unknown": "未定"}
	return [
		"[{}] {}｜边界={}｜归属={}｜证据={}｜规则={}".format(
			label.get(f.status, f.status),
			f.phenomenon,
			f.boundary,
			f.component,
			"; ".join(f"{e.source}:{e.ref_id}" for e in f.evidence[:3]) or "无",
			f.rule_id,
		)
		for f in findings
	]


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(prog="python -m diagnostics", description="XEYO 诊断中心")
	sub = parser.add_subparsers(dest="cmd", required=True)

	runs = sub.add_parser("runs", help="列出会话内的运行")
	runs.add_argument("--session", required=True)
	runs.add_argument("--limit", type=int, default=30)

	report = sub.add_parser("report", help="一次运行的诊断报告")
	report.add_argument("--session", required=True)
	report.add_argument("--turn", default="")
	report.add_argument("--format", choices=("text", "json", "md"), default="text")
	report.add_argument("--save", action="store_true", help="同时落一份 JSON 到 reports/")

	fact = sub.add_parser("fact", help="信息丢失定位链")
	fact.add_argument("--session", required=True)
	fact.add_argument("--turn", default="")
	fact.add_argument("--needle", required=True)

	mark = sub.add_parser("pin", help="标记这轮结果不对并固定证据")
	mark.add_argument("--session", required=True)
	mark.add_argument("--turn", required=True)
	mark.add_argument("--note", required=True)
	mark.add_argument("--expected", default="")
	mark.add_argument("--file", action="append", default=[], help="固定住的证据文件，可重复")

	ver = sub.add_parser("verifier", help="记录一次验收结果")
	ver.add_argument("--session", required=True)
	ver.add_argument("--turn", required=True)
	ver.add_argument("--name", required=True)
	ver.add_argument("--command", default="")
	ver.add_argument("--exit-code", dest="exit_code", type=int, default=None)

	cap = sub.add_parser("capture", help="按会话开关可复现记录")
	cap.add_argument("--session", required=True)
	cap.add_argument("--on", action="store_true")
	cap.add_argument("--off", action="store_true")

	sub.add_parser("disk", help="诊断产物占盘与配额")

	args = parser.parse_args(argv)

	if args.cmd == "runs":
		for row in list_runs(args.session, limit=args.limit):
			_emit(
				"{}  {:>19}  模型{}次 工具{}次  边界={}".format(
					row["turn_id"] or "(无轮次)",
					row["last_ts"],
					row["model_request_count"],
					row["tool_call_count"],
					",".join(row["boundaries"]),
				)
			)
			if row["coverage_note"]:
				_emit(f"    ! {row['coverage_note']}")
		return 0

	if args.cmd == "report":
		run = collect_run(args.session, args.turn)
		doc = build_report(run)
		if args.save:
			_emit(f"已保存：{save_report(doc)}")
		if args.format == "json":
			_emit(json.dumps(doc, ensure_ascii=False, indent=2))
		elif args.format == "md":
			_emit(to_markdown(doc))
		else:
			fault = doc.get("fault") or {}
			_emit(
				"归属：{}｜任务结局：{}".format(
					fault.get("responsibility_label", "无法归因"),
					fault.get("task_outcome_label", "无法判定"),
				)
			)
			_emit(f"为什么：{fault.get('why', '')}")
			_emit(doc["attribution"]["statement"])
			for line in _findings_rows(evaluate_run(run)):
				_emit(line)
			_emit(f"用量：{doc['usage_summary']['statement']} 估算 {doc['usage_summary']['estimated_total_cny']}")
			for item in fault.get("missing_evidence") or []:
				_emit(f"改判还缺：{item}")
			for gap in doc["gaps"]:
				_emit(f"缺项 {gap['boundary']}: {gap['reason']} {gap['detail']}")
		return 0

	if args.cmd == "fact":
		doc = trace_fact(collect_run(args.session, args.turn), args.needle)
		for stage in doc["stages"]:
			_emit(f"{stage['label']}: {stage['state']} — {stage['note']}")
		_emit(f"结论：{doc['verdict']}")
		_emit(doc["statement"])
		_emit(doc["caveat"])
		return 0

	if args.cmd == "pin":
		doc = pin_run(
			args.session, args.turn, note=args.note, expected=args.expected, pinned_files=args.file
		)
		_emit(f"已固定：{doc['pin_id']}（不触发任何付费实验）")
		return 0

	if args.cmd == "verifier":
		doc = record_verifier(
			args.session, args.turn, name=args.name, command=args.command, exit_code=args.exit_code
		)
		_emit(
			"已记录验收：{}（退出码 {}）".format(
				doc["pin_id"], "未运行" if doc["exit_code"] is None else doc["exit_code"]
			)
		)
		return 0

	if args.cmd == "capture":
		if args.on == args.off:
			_emit("当前状态：" + ("开" if capture_enabled(args.session) else "关"))
		else:
			set_capture_enabled(args.session, args.on)
			_emit("已" + ("开启" if args.on else "关闭") + "（只影响是否落盘，不改变发射形状）")
		return 0

	_emit(f"产物：{store.diagnostics_root()}  已用 {store.dir_size(store.diagnostics_root())} 字节 / 配额 {store.quota_bytes()}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
