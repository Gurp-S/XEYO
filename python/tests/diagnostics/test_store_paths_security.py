"""请求参数不得决定诊断产物的落点：id 净化、越界读写、空白身份。

回归的是 2026-09-24 真实数据普查里最贵的一类缺陷——同一族 ``/f"{id}.json"``
拼法既能删掉数据目录外的任意文件，也能读出 ``gui/package.json``；而空白
session_id 会被下游当成「不按该字段过滤」，把整会话端点变成越权列表。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from diagnostics import store
from diagnostics.capture import resolve_capture
from diagnostics.pins import delete_pin
from server.app import app

_OK_IDS = [
	"pin_0123456789abcdef",
	"rep_0123456789abcdef",
	"exp_0123456789abcdef",
	"a" * 64,
	"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
	"a-b_c",
]

_BAD_IDS = [
	"",
	"   ",
	"..",
	"../outside",
	"a/../b",
	"a\\b",
	"a/b",
	"C:\\Users\\other\\victim",
	"/etc/passwd",
	"pin_0123456789abcdef.json",
	"a-b_c.d",
	"小写中文",
	"a" * 200,
	"pin_x\x00",
	"pin x",
]


@pytest.fixture
def client():
	yield TestClient(app)


@pytest.fixture
def dig_root(tmp_path, monkeypatch):
	"""诊断产物写进临时根，权威数据目录逐字节不动。"""
	root = tmp_path / "dig"
	monkeypatch.setenv("XEYO_DIAGNOSTICS_DIR", str(root))
	store.ensure_dirs()
	store.reset_store_caches()
	yield root
	store.reset_store_caches()


def test_safe_ident_accepts_generated_shapes() -> None:
	for ident in _OK_IDS:
		assert store.safe_ident(ident) == ident


@pytest.mark.parametrize("ident", _BAD_IDS)
def test_safe_ident_rejects_anything_that_could_move(ident: str) -> None:
	with pytest.raises(store.InvalidIdentifier):
		store.safe_ident(ident)


def test_artifact_path_stays_inside_root(tmp_path) -> None:
	base = tmp_path / "reports"
	base.mkdir()
	inside = base / "rep_0123456789abcdef.json"
	inside.write_text("{}", encoding="utf-8")
	assert store.artifact_path(base, "rep_0123456789abcdef", suffix=".json").samefile(inside)
	with pytest.raises(store.InvalidIdentifier):
		store.artifact_path(base, "..\\escape", suffix=".json")


def test_body_hash_path_requires_64_hex(tmp_path) -> None:
	clean = "a" * 64
	path = store.body_hash_path(tmp_path, clean)
	assert path.parent == tmp_path / "aa"
	assert path.name == f"{clean}.json.gz"
	for bad in ("", "unserializable_0123456789abcdef", "g" * 64, clean[:63]):
		with pytest.raises(store.InvalidIdentifier):
			store.body_hash_path(tmp_path, bad)


def test_delete_pin_cannot_reach_outside_the_pin_dir(dig_root, tmp_path) -> None:
	victim = tmp_path / "victim.json"
	victim.write_text('{"keep":1}', encoding="utf-8")
	escaped = str(victim.with_suffix(""))  # 无扩展名的绝对路径
	with pytest.raises(store.InvalidIdentifier):
		delete_pin(escaped, "sess-x")
	with pytest.raises(store.InvalidIdentifier):
		delete_pin("..\\..\\victim", "sess-x")
	assert victim.is_file(), "越界删除必须在拼路径之前就被拒绝"
	assert delete_pin("pin_0123456789abcdef", "sess-x") is False


def test_report_load_cannot_read_outside_reports_dir(dig_root, tmp_path) -> None:
	from diagnostics.report import load_report

	other = tmp_path / "package.json"
	other.write_text('{"name":"not-a-report"}', encoding="utf-8")
	with pytest.raises(store.InvalidIdentifier):
		load_report(str(other.with_suffix("")))


def test_resolve_capture_never_reads_a_non_hex_hash(tmp_path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_DIAGNOSTICS_DIR", str(tmp_path / "dig"))
	store.reset_store_caches()
	planted = tmp_path / "planted.json.gz"
	planted.write_bytes(b'{"secret":"outside"}')
	out = resolve_capture(str(planted.with_suffix("")))
	assert out["state"] == "not_captured"
	assert "body_hash" in out["error"] or "非法" in out["error"]
	assert "body" not in out
	store.reset_store_caches()


def test_router_rejects_traversal_ids(client, dig_root, tmp_path) -> None:
	victim = tmp_path / "victim.json"
	victim.write_text('{"keep":1}', encoding="utf-8")
	res = client.delete(
		"/v1/diagnostics/pins/" + str(victim.with_suffix("")), params={"session_id": "s1"}
	)
	assert res.status_code == 422
	assert victim.is_file()

	foreign = tmp_path / "package.json"
	foreign.write_text('{"name":"gui"}', encoding="utf-8")
	res = client.get("/v1/diagnostics/reports/" + str(foreign.with_suffix("")))
	assert res.status_code == 422
	assert "gui" not in res.text

	res = client.get("/v1/diagnostics/experiments/" + "..%5C..%5Canything")
	assert res.status_code == 422


@pytest.mark.parametrize("blank", [" ", "\t", "  \n "])
def test_router_rejects_blank_session_identity(client, dig_root, blank: str) -> None:
	res = client.request("GET", "/v1/diagnostics/runs", params={"session_id": blank})
	assert res.status_code == 422, "空白会话号不得退化为「不过滤」"
	res = client.request("GET", "/v1/diagnostics/runs/t1", params={"session_id": blank})
	assert res.status_code == 422
	res = client.request(
		"GET", "/v1/diagnostics/runs/t1/fact", params={"session_id": blank, "needle": "x"}
	)
	assert res.status_code == 422


def test_router_rejects_percent_encoded_blank_session(client, dig_root) -> None:
	"""查询串里的 %20 解码后是空格——上游按「不过滤」处理过一次，这里必须拦住。"""
	res = client.get("/v1/diagnostics/runs?session_id=%20")
	assert res.status_code == 422
	assert res.json().get("runs") is None


def test_router_rejects_blank_turn_identity(client, dig_root) -> None:
	res = client.get("/v1/diagnostics/runs/%20", params={"session_id": "s1"})
	assert res.status_code == 422
	res = client.get("/v1/diagnostics/runs/%09/report.md", params={"session_id": "s1"})
	assert res.status_code == 422


def test_router_rejects_blank_needle(client, dig_root) -> None:
	res = client.get(
		"/v1/diagnostics/runs/t1/fact", params={"session_id": "s1", "needle": "   "}
	)
	assert res.status_code == 422


def test_experiments_list_survives_an_index_entry(client, dig_root) -> None:
	"""索引里一旦有认领记录，列表端点不得因为未导入的名字炸成 500。"""
	index = dig_root / "experiments" / "index.json"
	index.parent.mkdir(parents=True, exist_ok=True)
	index.write_text(
		json.dumps({"schema": 1, "by_key": {"idem-1": "exp_0123456789abcdef"}}),
		encoding="utf-8",
	)
	res = client.get("/v1/diagnostics/experiments")
	assert res.status_code == 200
	rows = res.json()["experiments"]
	assert rows == [{"idempotency_key": "idem-1", "experiment_id": "exp_0123456789abcdef"}]


def test_missing_cold_blob_is_reported_not_returned_empty(tmp_path, monkeypatch) -> None:
	"""冷层正文丢失时必须说 missing_blob，不能拿空串冒充一次成功回读。"""
	from session.persistence import safe_session_filename

	sid = "sess-blob-probe"
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	monkeypatch.setenv("XEYO_DIAGNOSTICS_DIR", str(tmp_path / "dig"))
	store.reset_store_caches()
	row = {
		"id": "m1",
		"role": "tool",
		"ts": 1.0,
		"content": None,
		"content_ref": "gone.json",
		"content_hash": "sha256:abc",
	}
	(tmp_path / f"{safe_session_filename(sid)}.jsonl").write_text(
		json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8"
	)
	client = TestClient(app)
	res = client.get("/v1/diagnostics/messages/m1", params={"session_id": sid})
	assert res.status_code == 200
	body = res.json()
	assert body["ok"] is False
	assert body["body_state"] == "missing_blob"
	assert body["content_hash"] == "sha256:abc"
	store.reset_store_caches()


def test_capture_disk_size_declares_its_scope(client, dig_root) -> None:
	res = client.get("/v1/diagnostics/capture", params={"session_id": "s1"})
	assert res.status_code == 200
	assert res.json()["disk_scope"] == "captures_dir"


def test_pins_and_reports_directories_are_the_only_writable_roots(dig_root) -> None:
	assert store.pins_dir().is_relative_to(store.diagnostics_root())
	assert store.reports_dir().is_relative_to(store.diagnostics_root())
	target = store.artifact_path(store.pins_dir() / "sess-a", "pin_deadbeef", suffix=".json")
	assert target.is_relative_to(store.diagnostics_root())
	assert not target.exists()
