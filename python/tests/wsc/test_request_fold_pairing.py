"""请求 ↔ 折叠配对契约（`usage/pairing.py` 的唯一取数口径）。

钉住的是**口径**，不是数值：之后任何"折叠当枪多付多少未命中"的数字都必须从这里出。
为什么需要这个文件：此前每条探针各写各的 ±2.5s 秒窗，而实测折叠→该枪请求的时差
median 2.85s / max 17.8s，相邻两次批准折叠间隔 p10 只有 7.2s ⇒ 秒窗既漏配又误配。
本契约改用「下一个批准锚点为界」，并把重试、一对多、未发送、被拒判定四类分开。
"""

from __future__ import annotations

import pytest

pytest.importorskip("usage.pairing")

from usage.pairing import (  # noqa: E402
	ROLE_FOLD_RETRY,
	ROLE_FOLD_SHOT,
	ROLE_POST_FOLD,
	ROLE_PRE_FOLD,
	fold_shot_extra_miss,
	pair_requests_to_folds,
)


def _req(ts: float, *, sid: str = "s1", prompt: int = 30_000, hit: int = 27_000,
         miss: int = 3_000, out: int = 400, cost: float = 0.006,
         rid: str = "", attempt: int = 1) -> dict:
	return {"ts": ts, "session_id": sid, "prompt_tokens": prompt, "cache_hit": hit,
	        "cache_miss": miss, "completion_tokens": out, "cost_cny": cost,
	        "request_id": rid, "attempt": attempt}


def _fold(ts: float, *, approved: bool = True, sid: str = "s1", **account) -> dict:
	row = {"ts": ts, "session_id": sid, "fold": approved}
	row.update(account)
	return row


def _roles(report) -> list[str]:
	return [r.role for r in report.requests]


def test_first_approved_fold_owns_the_next_request_regardless_of_gap() -> None:
	"""秒窗会漏掉的那一枪，按锚点为界必须仍算折叠枪。"""
	report = pair_requests_to_folds(
		[_req(10.0), _req(11.0), _req(40.0)],
		[_fold(32.0)],
	)
	assert _roles(report) == [ROLE_PRE_FOLD, ROLE_PRE_FOLD, ROLE_FOLD_SHOT]
	assert report.fold_without_request == 0


def test_request_between_two_anchors_attributes_to_the_latest_one() -> None:
	"""夹在两个锚点之间的请求属于**前**一个锚点；锚点之前的那枪仍是 pre_fold。"""
	report = pair_requests_to_folds(
		[_req(10.0), _req(15.0), _req(50.0)],
		[_fold(12.0), _fold(45.0)],
	)
	assert _roles(report) == [ROLE_PRE_FOLD, ROLE_FOLD_SHOT, ROLE_FOLD_SHOT]
	assert report.requests[0].anchor_ts is None
	assert report.requests[1].anchor_ts == 12.0
	assert report.requests[2].anchor_ts == 45.0
	assert report.fold_without_request == 0


def test_retry_of_the_fold_shot_is_not_counted_as_a_second_fold_shot() -> None:
	"""重试会把同一次发射重复计费 ⇒ 必须单列，且不得抢走折叠枪身份。"""
	report = pair_requests_to_folds(
		[_req(20.0, rid="call-a", attempt=1), _req(21.0, rid="call-a", attempt=2),
		 _req(30.0, rid="call-b")],
		[_fold(19.0)],
	)
	assert _roles(report) == [ROLE_FOLD_SHOT, ROLE_FOLD_RETRY, ROLE_POST_FOLD]


def test_attempt_gt_one_alone_is_treated_as_a_retry() -> None:
	"""``request_id`` 缺失（账本里约 40% 的行为空）时，attempt 是唯一的重试信号。"""
	report = pair_requests_to_folds(
		[_req(20.0), _req(21.0, attempt=3), _req(30.0)],
		[_fold(19.0)],
	)
	assert _roles(report) == [ROLE_FOLD_SHOT, ROLE_FOLD_RETRY, ROLE_POST_FOLD]


def test_approved_fold_with_no_following_request_is_reported_not_silently_dropped() -> None:
	"""投影建好却没发出（会话结束/发送前失败）⇒ 显式计数，不许被吞。"""
	report = pair_requests_to_folds([_req(10.0), _req(20.0)], [_fold(15.0), _fold(99.0)])
	assert _roles(report) == [ROLE_PRE_FOLD, ROLE_FOLD_SHOT]
	assert report.fold_without_request == 1


def test_rejected_judgment_is_an_assessment_but_never_an_anchor() -> None:
	"""裁定：评估枪号与成功折叠枪号分开记。被拒不能冒充折叠。"""
	report = pair_requests_to_folds(
		[_req(10.0), _req(20.0)],
		[_fold(5.0, approved=False, reason="pays_back_too_slow")],
	)
	assert _roles(report) == [ROLE_PRE_FOLD, ROLE_PRE_FOLD]
	assert report.anchors == 0
	assert report.assessments == 1
	assert report.rejections == 1


def test_pairing_never_crosses_sessions() -> None:
	report = pair_requests_to_folds(
		[_req(10.0, sid="a"), _req(20.0, sid="b")],
		[_fold(5.0, sid="a")],
	)
	by_sid = {r.session_id: r.role for r in report.requests}
	assert by_sid == {"a": ROLE_FOLD_SHOT, "b": ROLE_PRE_FOLD}


def test_unbilled_rows_stay_present_but_are_flagged() -> None:
	"""失败/未计费请求不能被当成一次实付；保留行本身，交给读侧按 ``billed`` 过滤。"""
	report = pair_requests_to_folds([_req(10.0, cost=0.0), _req(20.0, cost=0.006)], [])
	assert [r.billed for r in report.requests] == [False, True]


def test_extra_miss_allows_a_negative_delta_and_ignores_retries() -> None:
	"""未命中增量允许为负（裁定要求）；``pre_fold`` / ``fold_retry`` 不进这个数。"""
	report = pair_requests_to_folds(
		[_req(20.0, miss=5_000), _req(21.0, miss=5_000, attempt=2), _req(30.0, miss=3_000),
		 _req(40.0, miss=3_000)],
		[_fold(19.0)],
	)
	stat = fold_shot_extra_miss(report)
	assert stat["fold_shot_n"] == 1 and stat["post_fold_n"] == 2
	assert stat["extra_miss_median"] == 2_000
	assert stat["fold_shot_miss_median"] == 5_000

	inverted = pair_requests_to_folds(
		[_req(20.0, miss=1_000), _req(30.0, miss=4_000)],
		[_fold(19.0)],
	)
	assert fold_shot_extra_miss(inverted)["extra_miss_median"] < 0


def test_empty_inputs_produce_an_empty_but_wellformed_report() -> None:
	report = pair_requests_to_folds([], [])
	assert report.requests == ()
	assert report.by_role()[ROLE_FOLD_SHOT] == 0
	assert fold_shot_extra_miss(report)["fold_shot_n"] == 0
