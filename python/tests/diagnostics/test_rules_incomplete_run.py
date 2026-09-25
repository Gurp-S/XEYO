"""R9「未完成执行」的三条分支与误报边界。

这条规则此前没有任何测试引用（rule_id 在全仓 tests/ 里出现 0 次）：
它既会因"开始/结束不成对"报，也会因后台任务状态报，而后者**合法长任务与卡死同形**。
所以真正要钉住的是"什么时候不许报"，以及证据必须只指向没配对上的那几条记录。
"""

from __future__ import annotations

from typing import Any

from diagnostics.collect import collect_run
from diagnostics.identity import CONFIRMED_FAULT, UNKNOWN
from diagnostics.rules import check_incomplete_run, evaluate_run


def _run_with_jobs(write_audit, jobs: list[dict[str, Any]]):
	"""一条最小的审计链 + 外部喂进来的 job 快照（job 不来自审计行）。"""
	path = write_audit(
		[{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1}]
	)
	return collect_run("s1", "t1", audit_path=path, jobs=jobs)


def test_unpaired_start_is_reported_as_unknown(collect) -> None:
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
			{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
			{"ts": 1.2, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 2},
		]
	)
	findings = [f for f in evaluate_run(run) if f.rule_id == "incomplete_run"]
	assert len(findings) == 1
	f = findings[0]
	assert f.status == UNKNOWN
	assert "2 次开始、1 次结束" in f.phenomenon
	# 结束记录缺失不能证明进程已死 —— 措辞必须停在"不成对"这一层。
	assert "不能证明进程已死" in f.coverage_gap
	assert f.allowed_conclusion == "只能说记录不成对。"


def test_evidence_points_only_at_the_unpaired_start(collect) -> None:
	"""重试场景 2 开始 / 1 结束是常态：证据不能把已经正常结束的那次也列进去。"""
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
			{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
			{"ts": 1.2, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 2},
		]
	)
	f = next(x for x in evaluate_run(run) if x.rule_id == "incomplete_run")
	# 审计行号：第 3 行（第二次 model.started）才是没配上结束记录的那次开始。
	assert [e.ref_id for e in f.evidence] == ["L3"]


def test_balanced_attempts_are_not_reported(collect) -> None:
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
			{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
			{"ts": 1.2, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 2},
			{"ts": 1.3, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 2},
		]
	)
	assert [f for f in evaluate_run(run) if f.rule_id == "incomplete_run"] == []


def test_other_turns_do_not_leak_in(collect) -> None:
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t9", "model_request_id": "r9", "attempt": 1},
		],
		turn_id="t1",
	)
	assert check_incomplete_run(run) == []


def test_more_finishes_than_starts_does_not_crash(collect) -> None:
	"""异常数据（结束多于开始）：不该报"未完成"，也不该崩。"""
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
			{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
			{"ts": 1.2, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 2},
		]
	)
	assert [f for f in evaluate_run(run) if f.rule_id == "incomplete_run"] == []


# ---------- 后台任务分支 ----------


def _job(status: str, **over: Any) -> dict[str, Any]:
	job: dict[str, Any] = {
		"job_id": "bash-1",
		"status": status,
		"detail": "",
		"locator": "jobs:bash-1",
	}
	job.update(over)
	return job


def test_running_job_is_not_blamed_as_deadlock(write_audit) -> None:
	run = _run_with_jobs(write_audit, [_job("running")])
	f = next(x for x in check_incomplete_run(run) if x.boundary == "background_job")
	assert f.status == UNKNOWN
	assert "不能据此判死锁" in f.impact
	assert "无退出码" in f.coverage_gap
	assert f.allowed_conclusion == "只能说明当前状态。"


def test_failed_job_is_a_confirmed_fault_without_cause_claim(write_audit) -> None:
	run = _run_with_jobs(write_audit, [_job("failed", detail="进程退出码 137")])
	f = next(x for x in check_incomplete_run(run) if x.boundary == "background_job")
	assert f.status == CONFIRMED_FAULT
	assert "进程退出码 137" in f.phenomenon
	assert "不可推断失败原因" in f.allowed_conclusion


def test_finished_jobs_are_silent(write_audit) -> None:
	for status in ("succeeded", "cancelled", "done"):
		run = _run_with_jobs(write_audit, [_job(status)])
		assert [f for f in check_incomplete_run(run) if f.boundary == "background_job"] == [], status
