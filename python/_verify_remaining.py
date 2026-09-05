"""Detached verifier: nightshift one-by-one + remaining batches + failure extract.

Designed to be launched via Start-Process so Cursor shell SIGINT cannot kill it.
"""
from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable
OUT = ROOT / "_p4_verify"


def run_pytest(args: list[str], log: Path, timeout: int | None = None) -> int:
	cmd = [PY, "-m", "pytest", *args]
	try:
		proc = subprocess.run(
			cmd,
			cwd=str(ROOT),
			capture_output=True,
			text=True,
			encoding="utf-8",
			errors="replace",
			timeout=timeout,
		)
		code = int(proc.returncode)
		body = (proc.stdout or "") + (proc.stderr or "")
	except subprocess.TimeoutExpired as e:
		code = 124
		body = (e.stdout or "") + (e.stderr or "") + "\nTIMEOUT\n"
	if body and not body.endswith("\n"):
		body += "\n"
	log.write_text(body + f"EXIT={code}\n", encoding="utf-8")
	return code


def parse_junit(path: Path) -> tuple[int, int, int, int, list[str]]:
	if not path.exists():
		return 0, 0, 0, 0, []
	root = ET.parse(path).getroot()
	suites = [root] if root.tag == "testsuite" else list(root)
	total = failures = errors = skipped = 0
	fails: list[str] = []
	for s in suites:
		total += int(s.attrib.get("tests", 0) or 0)
		failures += int(s.attrib.get("failures", 0) or 0)
		errors += int(s.attrib.get("errors", 0) or 0)
		skipped += int(s.attrib.get("skipped", 0) or 0)
		for case in s.findall("testcase"):
			node = case.find("failure")
			if node is None:
				node = case.find("error")
			if node is None:
				continue
			cls = case.attrib.get("classname", "")
			name = case.attrib.get("name", "")
			msg = (node.attrib.get("message") or (node.text or "")).splitlines()
			msg0 = (msg[0] if msg else "")[:180]
			fails.append(f"{cls}::{name} :: {msg0}")
	return total, failures, errors, skipped, fails


def main() -> int:
	OUT.mkdir(exist_ok=True)
	summary: dict = {"steps": []}

	# 1) nightshift one-by-one
	ns_tests = [
		"test_no_lock_skips",
		"test_forget_not_resurrected",
		"test_should_run_not_gated_on_session_count",
		"test_should_run_when_promotable_within_24h",
		"test_agent_harvest_promotes",
		"test_stale_lock_reclaimed",
		"test_run_only_proposes_never_writes_xeyo",
		"test_maybe_schedule_after_stop_only",
	]
	ns_fail: list[str] = []
	for t in ns_tests:
		log = OUT / f"ns_{t}.log"
		code = run_pytest(
			[f"tests/test_nightshift.py::{t}", "-q", "--tb=line", "--timeout=60"],
			log,
			timeout=90,
		)
		summary["steps"].append({"step": f"ns::{t}", "exit": code})
		if code != 0:
			ns_fail.append(t)
	(OUT / "nightshift_result.json").write_text(
		json.dumps({"failed": ns_fail, "ok": len(ns_tests) - len(ns_fail)}, indent=2),
		encoding="utf-8",
	)

	# 2) alphabetical batch 9
	b9 = [
		"tests/test_string_utils.py",
		"tests/test_subagent_memory.py",
		"tests/test_subagent_meta.py",
		"tests/test_system_date.py",
		"tests/test_task_state.py",
		"tests/test_todo_restore.py",
		"tests/test_todo_write_tool.py",
		"tests/test_tool_orchestration.py",
		"tests/test_tool_perf.py",
		"tests/test_tool_progress.py",
		"tests/test_transcript_blobs.py",
		"tests/test_transcript_rotation.py",
		"tests/test_turn_detach_reattach.py",
		"tests/test_usage_combine.py",
		"tests/test_usage_ledger.py",
	]
	code = run_pytest(
		[*b9, "-q", "--tb=line", "--timeout=60", "--junitxml", str(OUT / "b9_junit.xml")],
		OUT / "b9.log",
		timeout=600,
	)
	summary["steps"].append({"step": "batch9", "exit": code})

	# 3) alphabetical batch 10
	b10 = [
		"tests/test_vendor_models.py",
		"tests/test_vendor_usage.py",
		"tests/test_web_tools.py",
		"tests/test_workspace_fs.py",
		"tests/test_workspace_git.py",
		"tests/test_workspace_lock.py",
		"tests/test_workspace_restore_scoped_perf.py",
		"tests/test_workspace_restore.py",
		"tests/test_workspace_revision.py",
		"tests/test_workspace_scope.py",
		"tests/test_write_policy.py",
		"tests/test_xeyo_ui_policy.py",
		"tests/test_xeyo_ui_tool.py",
		"tests/test_xml_tool_call.py",
	]
	code = run_pytest(
		[*b10, "-q", "--tb=line", "--timeout=60", "--junitxml", str(OUT / "b10_junit.xml")],
		OUT / "b10.log",
		timeout=600,
	)
	summary["steps"].append({"step": "batch10", "exit": code})

	# 4) full suite for failure inventory (ignore simulator live probe)
	code = run_pytest(
		[
			"tests",
			"-q",
			"--tb=line",
			"--timeout=60",
			"--ignore=tests/simulator",
			"--junitxml",
			str(OUT / "full_junit.xml"),
		],
		OUT / "full.log",
		timeout=1200,
	)
	summary["steps"].append({"step": "full", "exit": code})

	# aggregate failures
	all_fails: list[str] = []
	stats = {}
	for label, junit in [
		("b9", OUT / "b9_junit.xml"),
		("b10", OUT / "b10_junit.xml"),
		("full", OUT / "full_junit.xml"),
	]:
		total, failures, errors, skipped, fails = parse_junit(junit)
		stats[label] = {
			"tests": total,
			"failures": failures,
			"errors": errors,
			"skipped": skipped,
		}
		for f in fails:
			if f not in all_fails:
				all_fails.append(f)

	report = {
		"nightshift_failed": ns_fail,
		"stats": stats,
		"failures": all_fails,
		"steps": summary["steps"],
	}
	(OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
	(OUT / "DONE").write_text("ok\n", encoding="utf-8")
	return 0 if not all_fails and not ns_fail else 1


if __name__ == "__main__":
	raise SystemExit(main())
