"""``GET /v1/usage/report`` —— 用量页实时数据面的契约测试。

这条路由存在的唯一理由：用量页原来只吃 A3 快照报告，而快照是 schtasks 每天一次的
离线证据 ⇒ 界面上"今天"永远是空的，除非手动点一次「立即快照」。所以回归判据围绕
两件事设计：

1. **实时**：账本追加一行，下一次读数必须立刻包含它（缓存按文件状态失效，不是按 TTL、
   不是按快照）；
2. **口径没跑偏**：同一份冻结账本，本模块的日合计 / 分模型必须与生成器
   ``_a3_snapshot_one_day`` 逐字段相等 —— 否则用量页与表D 会各说一套。

外加三条这条通路自己的硬账：不出网（厂商通路一行都不碰）、不占事件循环（同步 ``def``）、
不全盘扫会话目录（只读账本点过名的会话）。

运行：``py -3.11 -m pytest tests/test_usage_live_report.py -q``
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import app
from usage import ledger as _ledger
from usage import live_report as lr


@pytest.fixture(autouse=True)
def _reset_caches(monkeypatch: pytest.MonkeyPatch):
	"""两个缓存都必须复位：上一个用例的文件状态可能撞键。"""
	lr.reset_caches_for_tests()
	monkeypatch.setattr(_ledger, "_events_cache", None)
	yield
	lr.reset_caches_for_tests()
	_ledger._events_cache = None


@pytest.fixture()
def client() -> TestClient:
	return TestClient(app)


# ── 夹具：贴近真实形态的账本行与会话文件 ──────────────────────────────────────


def _event(**over) -> dict:
	"""一行账本事件（字段形态与 ``usage.ledger.record_from_openai_usage`` 一致）。"""
	row = {
		"ts": 1_790_000_000.0,
		"day": "2026-09-22",
		"provider": "deepseek",
		"vendor": "deepseek",
		"model": "deepseek-v4-flash",
		"session_id": "sess_a",
		"key_fp": "…a1b2",
		"prompt_tokens": 8000,
		"completion_tokens": 321,
		"cache_hit": 7000,
		"cache_miss": 1000,
		"output": 321,
		"tokens": 8321,
		"cost_cny": 0.0102,
		"cost_source": "estimate",
		"request_id": "req-1",
		"attempt": 1,
		"kind": "turn",
	}
	row.update(over)
	return row


def _write_ledger(rows: list[dict]) -> Path:
	path = _ledger.events_path()
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(
		"".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
		encoding="utf-8",
	)
	return path


def _write_c2(rows: list[dict]) -> None:
	path = _ledger.c2_events_path()
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(
		"".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
		encoding="utf-8",
	)


def _session(sid: str, messages: list[tuple[float, str]], *, junk: int = 3) -> Path:
	"""一个会话转录：user 行 + 若干非 user 行（assistant/tool 也要有，形状筛才被测到）。"""
	from session.persistence import transcript_path

	path = transcript_path(sid)
	path.parent.mkdir(parents=True, exist_ok=True)
	lines = []
	for ts, content in messages:
		lines.append(json.dumps({"role": "user", "ts": ts, "content": content}, ensure_ascii=False))
		for i in range(junk):
			lines.append(
				json.dumps(
					{"role": "assistant", "ts": ts + i, "content": f"reply {i} " + "x" * 200},
					ensure_ascii=False,
				)
			)
	path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
	return path


BASE_TS = 1_790_000_000.0  # 2026-09-22（北京时间）


# ── 1. 实时性：账本一变，读数就变（这条特性的全部意义）────────────────────────


def test_appended_ledger_row_is_visible_on_the_next_call(client: TestClient) -> None:
	_write_ledger([_event(request_id="r1"), _event(request_id="r2")])
	_session("sess_a", [(BASE_TS - 10, "第一个任务")])

	first = client.get("/v1/usage/report").json()
	assert first["days"][0]["requests"] == 2

	_write_ledger([_event(request_id="r1"), _event(request_id="r2"), _event(request_id="r3")])
	second = client.get("/v1/usage/report").json()
	assert second["days"][0]["requests"] == 3, "缓存把新账本行藏住了：界面就退回「必须先点快照」"
	assert second["source"]["rows"] == 3


def test_repeated_call_without_change_is_served_from_cache(client: TestClient) -> None:
	_write_ledger([_event()])
	_session("sess_a", [(BASE_TS - 10, "任务")])
	a = client.get("/v1/usage/report").json()
	b = client.get("/v1/usage/report").json()
	# 同一份文件状态 ⇒ 同一份日行对象（generated_at 每次重新取，不参与判据）。
	assert a["days"] == b["days"]
	assert a["source"]["mtime"] == b["source"]["mtime"]


# ── 2. 口径对账：与生成器逐字段相等（同一份冻结账本）─────────────────────────


def test_day_and_model_rows_match_the_snapshot_generator(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
	"""同一份账本：实时日合计 / 分模型 == 快照报告的 detail（表D 与用量页不许各说一套）。"""
	rows = [
		_event(request_id="r1", ts=BASE_TS, cache_hit=7000, cache_miss=1000, output=321),
		_event(request_id="r2", ts=BASE_TS + 60, cache_hit=6000, cache_miss=2000, output=120),
		_event(
			request_id="r3",
			ts=BASE_TS + 120,
			provider="zhipu",
			model="glm-4.6v",
			session_id="sess_b",
			cost_cny=None,
			cost_source="unpriced",
			cache_hit=0,
			cache_miss=900,
			output=40,
		),
	]
	_write_ledger(rows)
	_write_c2([{"ts": BASE_TS + 1, "day": "2026-09-22", "type": "c2", "session_id": "sess_a", "cursor": 3}])
	_session("sess_a", [(BASE_TS - 10, "改一下压缩器"), (BASE_TS + 30, "再跑一遍门")])
	_session("sess_b", [(BASE_TS - 5, "另一件事")])

	from scripts import memory_stack_eval as gen

	# 生成器会把行 upsert 进仓库里的 quality_validation.json —— 钉进 tmp，别污染现场。
	monkeypatch.setattr(gen, "QUALITY_JSON", tmp_path / "quality.json")
	assert gen._a3_snapshot_one_day("2026-09-22", render=False) == 0
	snap = gen.load_quality_rows()["deploy_project_mode_2026-09-22"]["detail"]

	mine = lr.report_day("2026-09-22")["summary"]
	for field in (
		"requests",
		"prompt_tokens",
		"cache_hit",
		"cache_miss",
		"output",
		"cost_cny",
		"cost_unknown_requests",
		"c2_count",
		"hit_rate",
	):
		assert mine[field] == pytest.approx(snap[field]), field

	snap_models = {(m["provider"], m["model"]): m for m in snap["by_model"]}
	mine_models = {(m["provider"], m["model"]): m for m in mine["by_model"]}
	assert set(snap_models) == set(mine_models)
	for key in snap_models:
		for field in ("requests", "cache_hit", "cache_miss", "output", "cost_cny"):
			assert mine_models[key][field] == pytest.approx(snap_models[key][field]), (key, field)

	# 分会话：生成器把无归属的行塞进 "(none)"，本模块同样有这一行（只是另给计数）。
	snap_sessions = {s["session_id"] for s in snap["by_session"]}
	mine_sessions = {s["session_id"] for s in lr.report_day("2026-09-22")["sessions"]}
	assert snap_sessions == mine_sessions


def test_turn_labels_match_the_generator(monkeypatch: pytest.MonkeyPatch) -> None:
	"""轮次归属：与生成器 ``_turn_label_for`` 同式（同一 ts 数组、同一条消息）。

	只比**归属**（哪一轮）与真实消息标题；"未归类"那几种措辞是有意的不同
	（本模块把「会话里没有真实用户消息」与「早于第一条消息」分开说，措辞更长），
	不属于口径。
	"""
	from scripts import memory_stack_eval as gen

	messages = [(BASE_TS - 10, "第一件"), (BASE_TS + 5, "第二件")]
	_session("sess_a", messages)
	ts_arr, lbl_arr = lr._user_turns("sess_a")
	assert ts_arr == [m[0] for m in messages]

	for ts in (BASE_TS - 99, BASE_TS - 1, BASE_TS + 6, BASE_TS + 999):
		mine = lr._turn_of((ts_arr, lbl_arr), ts)
		theirs = gen._turn_label_for({"sess_a": (ts_arr, lbl_arr)}, "sess_a", ts)
		assert mine[0] == theirs[0], ts
		if not theirs[1].startswith("未归类"):
			assert mine[1] == theirs[1], ts


def test_injected_prefixes_and_text_sanitizer_match_their_sources() -> None:
	"""两处口径与它们各自对齐的源逐字相等（搬家/改名会让断言变红，而不是静默失去覆盖面）。"""
	from scripts import memory_stack_eval as gen

	assert lr._INJECTED_PREFIXES == gen._INJECTED_PREFIXES

	from server.routers import control

	nasty = [
		"\ufffd\ufffd6962",
		"a\tb\x00c",
		"x" * 400,
		"",
		None,
		123,
		"中文 \x1b[31mANSI\u2028行分隔符",
	]
	for value in nasty:
		assert lr._text(value) == control._a3_text(value), repr(value)


def test_quality_json_points_at_the_generators_file() -> None:
	from scripts import memory_stack_eval as gen

	assert Path(lr.QUALITY_JSON).resolve() == Path(gen.QUALITY_JSON).resolve()


# ── 3. 诚实性：没有 / 空 / 读不出 是三件事 ───────────────────────────────────


def test_missing_ledger_is_a_positive_answer(client: TestClient) -> None:
	r = client.get("/v1/usage/report")
	assert r.status_code == 200
	body = r.json()
	assert body["source"]["store"] == "missing_store"
	assert body["days"] == [] and body["day_count"] == 0


def test_empty_ledger_is_not_reported_as_missing(client: TestClient) -> None:
	path = _write_ledger([])
	assert path.is_file()
	body = client.get("/v1/usage/report").json()
	assert body["source"]["store"] == "empty_store"
	assert body["days"] == []


def test_unreadable_ledger_is_a_500_with_a_structured_type(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	from usage.event_reader import LedgerRead

	monkeypatch.setattr(
		_ledger, "_read_snapshot", lambda: LedgerRead(store="unreadable_store")
	)
	r = client.get("/v1/usage/report")
	assert r.status_code == 500
	assert r.json()["error"]["type"] == "usage_ledger_unreadable"
	assert client.get("/v1/usage/report?day=2026-09-22").status_code == 500


def test_day_without_rows_is_200_missing_not_404(client: TestClient) -> None:
	_write_ledger([_event(day="2026-09-22")])
	body = client.get("/v1/usage/report?day=2026-01-01").json()
	assert body["missing"] is True
	assert body["summary"] is None
	assert body["turns"] == []


@pytest.mark.parametrize("raw", ["%20", "2026-9-2", "../etc", "2026-09-22%00"])
def test_malformed_day_is_422(client: TestClient, raw: str) -> None:
	_write_ledger([_event()])
	r = client.get(f"/v1/usage/report?day={raw}")
	assert r.status_code == 422, r.text
	assert r.json()["error"]["type"] == "invalid_request_error"


# ── 4. 金额：无价目 ≠ 0 ─────────────────────────────────────────────────────


def test_unpriced_rows_never_become_zero_cost(client: TestClient) -> None:
	_write_ledger(
		[
			_event(request_id="a", cost_cny=None, cost_source="unpriced"),
			_event(request_id="b", cost_cny=None, cost_source="unpriced"),
		]
	)
	_session("sess_a", [(BASE_TS - 1, "任务")])
	day = client.get("/v1/usage/report").json()["days"][0]
	# 一行有价都没有 ⇒ null（"费用未知"），不是 0（"免费"）。
	assert day["cost_cny"] is None
	assert day["cost_unknown_requests"] == 2

	_write_ledger([_event(request_id="a", cost_cny=None), _event(request_id="b", cost_cny=0.5)])
	day = client.get("/v1/usage/report").json()["days"][0]
	assert day["cost_cny"] == pytest.approx(0.5)
	assert day["cost_unknown_requests"] == 1, "合计不完整必须自报，否则读成完整合计"


# ── 5. 轮次 / 小时 / 无会话归属 ──────────────────────────────────────────────


def test_injected_user_lines_do_not_create_turns(client: TestClient) -> None:
	_write_ledger([_event(request_id=f"r{i}", ts=BASE_TS + i) for i in range(4)])
	_session(
		"sess_a",
		[
			(BASE_TS - 10, "真实用户消息"),
			(BASE_TS - 5, "[Resume] 继续"),
			(BASE_TS - 4, "<system-reminder>通报片段</system-reminder>"),
			(BASE_TS - 3, "[Background jobs] 后台任务"),
			(BASE_TS - 2, "   "),
		],
	)
	day = client.get("/v1/usage/report").json()["days"][0]
	assert day["turns"] == 1, "注入块也算轮次 ⇒ 轮数与标题一起虚高"
	assert day["hour_counts"][_hour(BASE_TS - 10)] == 1


def _hour(ts: float) -> int:
	from datetime import datetime

	from usage.pricing import BJ

	return datetime.fromtimestamp(ts, tz=BJ).hour


def test_hour_buckets_are_per_turn_and_unknown_is_reported(client: TestClient) -> None:
	# 两轮：一早在 08 点前、一在下午；外加一笔 ts 读不出。
	early = BASE_TS - 6 * 3600
	late = BASE_TS + 5 * 3600
	_write_ledger(
		[
			_event(request_id="e1", ts=early),
			_event(request_id="e2", ts=early + 30),
			_event(request_id="l1", ts=late),
			_event(request_id="l2", ts="not-a-number"),
		]
	)
	_session("sess_a", [(early - 1, "早上的任务"), (late - 1, "下午的任务")])
	day = client.get("/v1/usage/report").json()["days"][0]
	# 真不变量：能分桶的 + 不能分桶的 = 轮次总数（一笔都不许静默丢）。
	assert sum(day["hour_counts"]) + day["hour_unknown"] == day["turns"] == 3
	assert day["hour_counts"][_hour(early)] == 1
	assert day["hour_counts"][_hour(late)] == 1
	assert day["hour_unknown"] == 1, "分不了桶的轮次要报数，不许静默丢"


def test_rows_without_session_id_are_grouped_not_guessed(client: TestClient) -> None:
	_write_ledger(
		[
			_event(request_id="k1", session_id=""),
			_event(request_id="k2"),  # 有会话
		]
	)
	_session("sess_a", [(BASE_TS - 1, "有归属的任务")])
	day = client.get("/v1/usage/report").json()["days"][0]
	assert day["sessions"] == 1
	assert day["unattributed_requests"] == 1
	detail = client.get("/v1/usage/report?day=2026-09-22").json()
	labels = {t["label"] for t in detail["turns"]}
	assert lr.UNATTRIBUTED_LABEL in labels
	assert all(t["label"] for t in detail["turns"]), "不许出现空标题"
	# 分会话表里那一行的 id 是哨兵值，不是空串——空串会被界面渲染成空白行。
	assert lr.UNATTRIBUTED_SID in {s["session_id"] for s in detail["sessions"]}


def test_hostile_session_id_cannot_escape_the_sessions_dir(client: TestClient) -> None:
	_write_ledger([_event(request_id="a", session_id="../../etc/passwd")])
	body = client.get("/v1/usage/report?day=2026-09-22").json()
	assert body["summary"]["unattributed_requests"] == 1
	assert body["sessions"][0]["session_id"] == lr.UNATTRIBUTED_SID


# ── 6. 下钻：每枪一行 + 上界 ────────────────────────────────────────────────


def test_detail_carries_one_row_per_model_call(client: TestClient) -> None:
	_write_ledger(
		[
			_event(request_id="r1", ts=BASE_TS, attempt=1),
			_event(request_id="r1", ts=BASE_TS + 5, attempt=2, cache_hit=1, cache_miss=2, output=3),
		]
	)
	_session("sess_a", [(BASE_TS - 1, "重试也要各留一行")])
	turn = client.get("/v1/usage/report?day=2026-09-22").json()["turns"][0]
	assert turn["requests"] == 2 and turn["event_count"] == 2
	assert [e["attempt"] for e in turn["events"]] == [1, 2]
	assert {e["request_id"] for e in turn["events"]} == {"r1"}
	assert turn["events"][0]["cost_source"] == "estimate"


def test_event_budget_keeps_the_newest_turns_and_still_reports_totals(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	_write_ledger(
		[
			_event(request_id="o1", ts=BASE_TS - 100),
			_event(request_id="o2", ts=BASE_TS - 90),
			_event(request_id="n1", ts=BASE_TS + 10),
		]
	)
	_session("sess_a", [(BASE_TS - 110, "旧任务"), (BASE_TS + 5, "新任务")])
	monkeypatch.setattr(lr, "_MAX_DETAIL_EVENT_ROWS", 1)
	body = lr.report_day("2026-09-22")
	assert body["summary"]["requests"] == 3, "截断只削原文行，绝不削合计"
	assert body["events_truncated"] == 2
	# 额度给最新的轮次：旧任务只剩摘要，新任务保留原文。
	by_label = {t["label"]: t for t in body["turns"]}
	assert by_label["新任务"]["events"] and by_label["新任务"]["events_truncated"] == 0
	assert by_label["旧任务"]["events"] == []
	assert by_label["旧任务"]["events_truncated"] == 2


# ── 7. 验收判据三态（快照降级后界面还要能区分）────────────────────────────────


def test_accepted_is_three_valued(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
	_write_ledger([_event(day="2026-09-22"), _event(day="2026-09-23")])
	_session("sess_a", [(BASE_TS - 1, "任务")])
	monkeypatch.setattr(lr, "QUALITY_JSON", tmp_path / "absent.json")
	assert all(d["accepted"] is None and d["snapshot"] is False for d in lr.report_summary()["days"])

	monkeypatch.setattr(
		lr,
		"QUALITY_JSON",
		_tmp_quality(tmp_path, {"deploy_project_mode_2026-09-22": {"accepted": True}}),
	)
	lr.reset_caches_for_tests()
	by_day = {d["day"]: d for d in lr.report_summary()["days"]}
	assert by_day["2026-09-22"]["accepted"] is True
	assert by_day["2026-09-22"]["snapshot"] is True
	# 快照过但未验收 ⇒ false（不是 null）；从没快照过 ⇒ null（不是 false）。
	assert by_day["2026-09-23"]["accepted"] is None


def _tmp_quality(tmp_path: Path, rows: dict) -> Path:
	path = tmp_path / "quality.json"
	path.write_text(json.dumps({"rows": rows, "ab": {}}), encoding="utf-8")
	return path


# ── 8. 通路边界：不出网、不占事件循环、不扫全目录 ─────────────────────────────


def test_report_route_is_a_sync_handler() -> None:
	"""同步 ``def`` ⇒ FastAPI 丢线程池。写成 async 会把 1 秒级聚合压到事件循环上，
	聊天流式（同一个 loop）就会被它卡住。这条断言把"不影响聊天"钉成结构判据。"""
	from server.routers import usage as usage_router

	assert not inspect.iscoroutinefunction(usage_router.get_usage_report)


def test_report_never_touches_the_vendor_path(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	_write_ledger([_event()])
	_session("sess_a", [(BASE_TS - 1, "任务")])

	def _boom(*_a, **_k):  # pragma: no cover - 被调用即失败
		raise AssertionError("实时报表不许碰厂商通路")

	monkeypatch.setattr("usage.vendor.fetch_vendor_usage", _boom)
	assert client.get("/v1/usage/report").status_code == 200
	assert client.get("/v1/usage/report?day=2026-09-22").status_code == 200


def test_only_sessions_named_by_the_ledger_are_read(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	"""生成器那版要全盘扫 1,991 个会话文件 / 243 MB；这条通路只许读账本点过名的。"""
	_write_ledger([_event(request_id="a", session_id="sess_real")])
	_session("sess_real", [(BASE_TS - 1, "真会话")])
	for i in range(50):  # 目录里堆 50 个账本没提的会话
		_session(f"sess_noise_{i}", [(BASE_TS - 1, f"噪声{i}")])

	seen: list[str] = []
	real = lr._user_turns

	def spy(sid: str):
		seen.append(sid)
		return real(sid)

	monkeypatch.setattr(lr, "_user_turns", spy)
	lr.reset_caches_for_tests()
	assert client.get("/v1/usage/report").status_code == 200
	assert set(seen) == {"sess_real"}, f"扫了账本之外的会话：{set(seen)}"


def test_tokens_field_feeds_the_heatmap(client: TestClient) -> None:
	"""热力图指标 = 账本自己的 ``tokens``（厂商 total_tokens 语义），不是界面把输入输出相加。"""
	_write_ledger(
		[
			_event(request_id="a", tokens=8321),
			_event(request_id="b", tokens=1000),
			_event(request_id="c", day="2026-09-23", tokens=7),
		]
	)
	_session("sess_a", [(BASE_TS - 1, "任务")])
	days = {d["day"]: d for d in client.get("/v1/usage/report").json()["days"]}
	assert days["2026-09-22"]["tokens"] == 9321
	assert days["2026-09-23"]["tokens"] == 7
	# 三分类仍然分列：tokens 不参与 hit/miss/output 的任何求和。
	assert days["2026-09-22"]["cache_hit"] + days["2026-09-22"]["cache_miss"] == 16000
