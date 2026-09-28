"""A3 报告数据面 ``GET /v1/settings/memory/report/data`` 的契约测试。

这条路由存在的唯一理由：用量页原来只能贴 10 MB 的报告网页（iframe），因为生成器内嵌的
``window.__A3__`` payload 没有任何路由交给前端。于是回归判据也全围绕它设计：

1. 报告不在 = 结构化 404（界面才能诚实地说"还没生成"，而不是白屏）；
2. ``total`` 那份重复明细（≈5 MB）**确实没下发**；
3. 账本里的二进制残骸（``key_fp`` 的 U+FFFD / 控制符）**不会**原样回给前端；
4. ``accepted`` 是验收判据，逐字节透传，后端不许重算、前端更不许重算。

运行：``py -3.11 -m pytest tests/test_memory_report_data.py -q``
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import app

_LAN = ("203.0.113.9", 55555)

#: 乱码原型：真实账本里 key_fp 就是这个形态（解码残骸 + 末 4 位）。
_DIRTY_KEY_FP = "\ufffd\ufffd6962"
#: 真实 blob 里出现过的另一种残骸（"bsxy" 是二进制串掉进 UTF-8 解码后的可见碎片）。
_DIRTY_KEY_FP_BSXY = "\ufffd\ufffdbsxy"


def _payload(**over) -> dict:
	"""一份**贴近真实形态**的 payload：每天既在 day 行上有 by_*，又在 ``total`` 里重嵌一份。

	生成器（``scripts/memory_stack_eval``）就是把这个 detail 字典整个塞进 ``total``，
	所以 ``by_turn`` 在文件里存在两次——裁剪函数要砍掉的就是它，故 fixture 必须保留这个
	重复形态，否则"去重"这条断言会空跑。
	"""
	turn_events = [
		{
			# 故意与轮次 first_ts 不同值：这样"摘要/明细里都不该出现枪记录时间戳"
			# 才是可证伪的断言，而不是恰好被同值遮蔽。
			"ts": 1_788_672_400.111,
			"provider": "deepseek",
			"model": "deepseek-v4-flash",
			"key_fp": _DIRTY_KEY_FP if i % 2 else _DIRTY_KEY_FP_BSXY,
			"prompt_tokens": 8000,
			"cache_hit": 7000,
			"cache_miss": 1000,
			"output": 321,
			"cost_cny": 0.0102,
		}
		for i in range(6)
	]
	detail = {
		"day": "2026-09-22",
		"requests": 42,
		"prompt_tokens": 120_000,
		"cache_hit": 96_000,
		"cache_miss": 24_000,
		"hit_rate": 0.8,
		"c2_count": 3,
		"output": 4567,
		"cost_cny": 0.5123,
		#: 服务端绝对路径：界面用不上，也不该被反射回前端。
		"ledger_dir": "C:\\Users\\someone\\.xeyo\\usage",
		"by_model": [
			{
				"provider": "deepseek",
				"model": "deepseek-v4-flash",
				"requests": 42,
				"prompt_tokens": 120_000,
				"cache_hit": 96_000,
				"cache_miss": 24_000,
				"hit_rate": 0.8,
				"output": 4567,
				"cost_cny": 0.5123,
			}
		],
		"by_session": [
			{
				#: 会话身份里混控制符：上屏就是乱码，必须清洗但不能静默改写成另一个身份。
				"session_id": "pov-ray__Wk2DcsZ__agent\x00\x07",
				"requests": 20,
				"prompt_tokens": 60_000,
				"cache_hit": 48_000,
				"cache_miss": 12_000,
				"hit_rate": 0.8,
				"output": 2000,
				"cost_cny": 0.25,
			}
		],
		"by_turn": [
			{
				"session_id": "pov-ray__52qKAhM__agent",
				"label": "构建 POV-Ray 2.2\t找到并下载" + "x" * 300,
				"model": "deepseek-v4-flash",
				"requests": 6,
				"cache_hit": 9088,
				"cache_miss": 3360,
				"hit_rate": 0.7301,
				"output": 1052,
				"cost_cny": 0.010228,
				"first_ts": 1_788_672_364.839,
				#: 原始枪记录：轮次体积的主体，前端只要条数。
				"events": turn_events,
				#: 乱码指纹挂在轮次行上也要一起验（真实数据里它在 events 内）。
				"key_fp": _DIRTY_KEY_FP,
			}
		],
	}
	day = {"day": "2026-09-22", "total": detail, **{k: v for k, v in detail.items() if k.startswith("by_")}}
	#: ``accepted`` 是真值判据：故意给非 bool 的 truthy 值，验证透传成 True 而不是被重算。
	return {"generated_at": "2026-09-27T18:31:19.658759+00:00", "days": [day], **over}


def _write_report(path: Path, payload: dict) -> int:
	"""按生成器的内嵌形态写一份报告 HTML（前面垫 CSS，payload 在后面）。

	垫 CSS 不是为了好看：真实报告前 16 KB 是样式块，且它把"响应 ≪ 文件"这个比值钉在
	一个稳定量级上，裁剪一旦失效（有人把 ``total`` 原样塞回去）体积断言立刻会红。
	"""
	blob = json.dumps(payload, ensure_ascii=False, allow_nan=True).replace("</", "<\\/")
	html = (
		"<!doctype html><style>"
		+ (".a{color:#123456}" * 20_000)
		+ f"</style><script>window.__A3__={blob}</script>"
	)
	path.write_text(html, encoding="utf-8")
	return len(html.encode("utf-8"))


@pytest.fixture
def report(tmp_path: Path, monkeypatch) -> Path:
	import scripts.memory_stack_eval as M

	report_path = tmp_path / "A3-monitor.html"
	monkeypatch.setattr(M, "A3_HTML", report_path)
	return report_path


# ---- 报告不存在：必须给结构化错误，界面才有"诚实说没有"的依据 ----

def test_data_missing_report_is_structured_404(report: Path) -> None:
	with TestClient(app) as c:
		r = c.get("/v1/settings/memory/report/data")

	assert r.status_code == 404, r.text
	body = r.json()["error"]
	assert body["type"] == "not_found"
	assert "not generated" in body["message"]


def test_data_rejected_from_lan(report: Path) -> None:
	"""与 ``/report`` ``/report/view`` 同一道本机门禁——数据面不能成为绕过的口子。"""
	with TestClient(app, client=_LAN) as c:
		r = c.get("/v1/settings/memory/report/data")
		assert r.status_code == 403, r.text
		assert c.get("/v1/settings/memory/report/data?day=2026-09-22").status_code == 403

	assert r.json()["error"]["type"] == "permission_error"


def test_data_path_is_never_caller_supplied(report: Path) -> None:
	"""``?day=`` 只接受 YYYY-MM-DD：任何带路径分隔符 / .. 的值都进不了文件系统。

	这条是"路径严格性"的等价保险：路由只读生成器常量 ``A3_HTML``，调用方能影响的只有
	这个受正则约束的日字符串。
	"""
	report.write_text("x", encoding="utf-8")
	evil_days = (
		"..%2F..%2Fetc%2Fpasswd",
		"../../windows/system32",
		"2026-09-22/../view",
		"9999-99-999",
		"2026-9-22",
		"2026-09-22x",
	)
	with TestClient(app) as c:
		for evil in evil_days:
			r = c.get("/v1/settings/memory/report/data", params={"day": evil})
			assert r.status_code == 404, (evil, r.text)
			assert r.json()["error"]["type"] == "not_found"


# ---- 报告存在：摘要形状 + total 去重 ----

def test_data_summary_shape(report: Path) -> None:
	size = _write_report(report, _payload())

	with TestClient(app) as c:
		r = c.get("/v1/settings/memory/report/data")

	assert r.status_code == 200, r.text
	assert r.headers.get("cache-control") == "no-store"
	body = r.json()
	assert body["ok"] is True
	assert body["generated_at"] == "2026-09-27T18:31:19.658759+00:00"
	assert body["day_count"] == 1
	assert body["source"] == {
		"path": str(report),
		"bytes": size,
		"mtime": pytest.approx(report.stat().st_mtime, abs=1),
	}
	(day,) = body["days"]
	assert day["day"] == "2026-09-22"
	for k, v in {
		"requests": 42,
		"prompt_tokens": 120_000,
		"cache_hit": 96_000,
		"cache_miss": 24_000,
		"hit_rate": 0.8,
		"c2_count": 3,
		"output": 4567,
		"cost_cny": 0.5123,
	}.items():
		assert day[k] == v, k
	# 报告 payload 的 detail 里没有 sessions/turns 字段（旧网页"会话数"恒为 0）：给真值。
	assert day["sessions"] == 1
	assert day["turns"] == 1
	assert day["by_model"][0]["model"] == "deepseek-v4-flash"
	assert len(day["hour_counts"]) == 24
	assert day["hour_unknown"] == 0


def test_data_drops_duplicated_total_payload(report: Path) -> None:
	"""``total`` / ``by_session`` / ``by_turn`` / ``events`` / ``ledger_dir`` 都不许出现在摘要里。

	去重要可证伪：fixture 里同一份 ``by_turn`` 在文件里存了两遍，摘要只留它的**条数**，
	于是那些只存在于明细里的特征串（轮次 session_id、枪记录时间戳）必须从摘要响应里消失；
	而下钻 ``?day=`` 时它们又要回来。裁剪失效时这两条会一起红。
	"""
	payload = _payload()
	size = _write_report(report, payload)
	detail = payload["days"][0]["total"]
	turn_session_id = detail["by_turn"][0]["session_id"]
	event_ts = str(detail["by_turn"][0]["events"][0]["ts"])

	with TestClient(app) as c:
		summary = c.get("/v1/settings/memory/report/data")
		down = c.get("/v1/settings/memory/report/data?day=2026-09-22")

	text = summary.text
	for gone in ('"total"', '"events"', '"by_session"', '"by_turn"', '"ledger_dir"', '"key_fp"'):
		assert gone not in text, gone
	assert turn_session_id not in text
	assert event_ts not in text
	# 摘要**不**包含被重复的那两份明细；体积因此要比原文件小两个数量级。
	assert len(text.encode("utf-8")) < size / 50

	# 下钻只取那一天，明细回来但 events 仍然换成条数。
	body = down.json()
	assert [t["session_id"] for t in body["turns"]] == [turn_session_id]
	assert event_ts not in down.text
	assert body["turns"][0]["event_count"] == 6
	assert len(down.text.encode("utf-8")) < size / 50


def test_data_day_detail_replaces_events_with_count(report: Path) -> None:
	_write_report(report, _payload())

	with TestClient(app) as c:
		r = c.get("/v1/settings/memory/report/data?day=2026-09-22")

	assert r.status_code == 200, r.text
	assert r.headers.get("cache-control") == "no-store"
	body = r.json()
	assert body["day"] == "2026-09-22"
	assert body["summary"]["day"] == "2026-09-22"
	(turn,) = body["turns"]
	assert "events" not in turn
	assert turn["event_count"] == 6
	assert len(body["sessions"]) == 1
	assert body["sessions"][0]["requests"] == 20
	# 明细里也不许出现服务端绝对路径。
	assert "ledger_dir" not in r.text
	assert ".xeyo" not in r.text


def test_data_day_detail_unknown_day_is_404(report: Path) -> None:
	_write_report(report, _payload())
	with TestClient(app) as c:
		r = c.get("/v1/settings/memory/report/data?day=2026-01-01")
	assert r.status_code == 404
	assert r.json()["error"]["type"] == "not_found"


# ---- 乱码 / 二进制残骸 ----

def test_data_sanitises_binary_and_control_bytes(report: Path) -> None:
	_write_report(report, _payload())

	with TestClient(app) as c:
		summary = c.get("/v1/settings/memory/report/data").text
		detail = c.get("/v1/settings/memory/report/data?day=2026-09-22").json()

	for name, text in (("summary", summary), ("detail", json.dumps(detail, ensure_ascii=False))):
		assert "\ufffd" not in text, f"{name}: U+FFFD 漏到前端"
		assert "bsxy" not in text
		assert not any(ord(ch) < 0x20 for ch in text), f"{name}: 控制符漏到前端"
		assert not any(0x7F <= ord(ch) <= 0x9F for ch in text)

	# key_fp：解码残骸压成"…<尾 4 位>"，仍是可对齐的指纹形态。
	(turn,) = detail["turns"]
	assert turn["key_fp"] == "…6962", turn["key_fp"]
	# 会话身份里的控制符被删掉，其余字符一个不动（不静默改写身份）。
	assert detail["sessions"][0]["session_id"] == "pov-ray__Wk2DcsZ__agent"
	# 中文标签原样保留（清洗只动控制符，不动 CJK），长标签截断加省略号。
	assert "构建 POV-Ray 2.2" in turn["label"]
	assert "\t" not in turn["label"]
	assert turn["label"].endswith("…")


def test_data_key_fp_without_clean_tail_is_hex(report: Path) -> None:
	payload = _payload()
	#: 残骸多到没有可信字母数字尾：给 hex: 形态，而不是空串或乱码。
	payload["days"][0]["total"]["by_turn"][0]["key_fp"] = "\ufffd\ufffd"
	_write_report(report, payload)

	with TestClient(app) as c:
		body = c.get("/v1/settings/memory/report/data?day=2026-09-22").json()

	(turn,) = body["turns"]
	assert turn["key_fp"].startswith("hex:")
	assert all(ch in "0123456789abcdef" for ch in turn["key_fp"][4:])


def test_data_non_finite_numbers_become_null(report: Path) -> None:
	payload = _payload()
	detail = payload["days"][0]["total"]
	detail["cost_cny"] = float("nan")
	detail["by_model"][0]["requests"] = float("inf")
	_write_report(report, payload)

	with TestClient(app) as c:
		r = c.get("/v1/settings/memory/report/data")

	assert r.status_code == 200, r.text
	assert "NaN" not in r.text and "Infinity" not in r.text
	(day,) = r.json()["days"]
	#: 非有限值变 null：界面据此说"数据里没有"，而不是渲染出 NaN 或补 0。
	assert day["cost_cny"] is None
	assert day["by_model"][0]["requests"] is None


# ---- accepted：逐字透传，不许任何一端重算 ----

def test_data_passes_accepted_verbatim(report: Path) -> None:
	payload = _payload()
	day_row = payload["days"][0]
	#: 报告给的是非 bool 的 truthy 判据；透传的含义是"照它的值表态"，不是"我另算一个"。
	day_row["accepted"] = "pass"
	_write_report(report, payload)

	with TestClient(app) as c:
		body = c.get("/v1/settings/memory/report/data").json()
		detail = c.get("/v1/settings/memory/report/data?day=2026-09-22").json()

	assert body["days"][0]["accepted"] is True
	assert detail["summary"]["accepted"] is True

	payload["days"][0]["accepted"] = 0
	_write_report(report, payload)
	with TestClient(app) as c:
		assert c.get("/v1/settings/memory/report/data").json()["days"][0]["accepted"] is False


def test_data_keeps_other_days_accepted_flags_independent(report: Path) -> None:
	payload = _payload()
	first = payload["days"][0]["total"]
	second = json.loads(json.dumps(first))
	second["day"] = "2026-09-23"
	payload["days"].append(
		{"day": "2026-09-23", "total": second, "accepted": True, "by_model": [], "by_session": [], "by_turn": []}
	)
	payload["days"][0]["accepted"] = False
	_write_report(report, payload)

	with TestClient(app) as c:
		body = c.get("/v1/settings/memory/report/data").json()

	assert [d["accepted"] for d in body["days"]] == [False, True]
	assert [d["day"] for d in body["days"]] == ["2026-09-22", "2026-09-23"]


# ---- 报告存在却读不出 / 内嵌形态变了：不能谎报成"尚未生成" ----

def test_data_unparsable_payload_is_500_not_404(report: Path) -> None:
	report.write_text(
		"<!doctype html><script>window.__A3__={not json}</script>",
		encoding="utf-8",
	)
	with TestClient(app) as c:
		r = c.get("/v1/settings/memory/report/data")

	assert r.status_code == 500, r.text
	assert r.json()["error"]["type"] == "memory_report_unparsable"


def test_data_missing_marker_is_unparsable(report: Path) -> None:
	report.write_text("<!doctype html><p>报告里没有内嵌数据</p>", encoding="utf-8")
	with TestClient(app) as c:
		r = c.get("/v1/settings/memory/report/data")
	assert r.status_code == 500
	assert r.json()["error"]["type"] == "memory_report_unparsable"


def test_data_payload_shape_drift_is_unparsable(report: Path) -> None:
	"""生成器哪天把 ``days`` 改名 / 换成 dict，界面要听到 500 而不是拿到空列表当"没有报告"。"""
	report.write_text(
		'<script>window.__A3__={"generated_at": "x", "days": {"2026-09-22": {}}}</script>',
		encoding="utf-8",
	)
	with TestClient(app) as c:
		r = c.get("/v1/settings/memory/report/data")
	assert r.status_code == 500
	assert r.json()["error"]["type"] == "memory_report_unparsable"
