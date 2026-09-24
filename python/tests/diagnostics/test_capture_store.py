"""可复现记录与固定证据的语义：开关零影响、缺 blob 不谎报、配额不删钉住的东西。"""

from __future__ import annotations

import gzip
import json

import pytest

from diagnostics import capture as cap
from diagnostics import pins as pins_mod
from diagnostics import store
from diagnostics.identity import COMPLETE, PARTIAL, REDACTED


def _body() -> dict:
	return {"model": "deepseek-chat", "messages": [{"role": "user", "content": "把测试跑一遍"}], "stream": True}


def test_disabled_capture_writes_nothing() -> None:
	assert cap.capture_enabled("s1") is False
	out = cap.capture_request(session_id="s1", body=_body(), model_request_id="r1", attempt=1)
	assert out is None
	assert store.dir_size(store.captures_dir()) == 0


def test_enabled_capture_round_trips_and_hash_matches() -> None:
	cap.set_capture_enabled("s1", True)
	assert cap.capture_enabled("s1") is True
	row = cap.capture_request(
		session_id="s1", turn_id="t1", model_request_id="r1", attempt=1, provider="deepseek", model="m", body=_body()
	)
	assert row and row["state"] == COMPLETE
	doc = cap.resolve_capture(row["body_hash"])
	assert doc["hash_matches"] is True
	assert doc["body"]["messages"][0]["content"] == "把测试跑一遍"
	assert doc["request_body_hash"] == row["body_hash"]
	# 正文不得原封不动躺在非 gzip 的明文文件里
	assert row["body_hash"] not in [p.name for p in store.captures_dir().glob("*.json")]


def test_duplicate_body_is_deduped_but_indexed_per_attempt() -> None:
	cap.set_capture_enabled("s2", True)
	a = cap.capture_request(session_id="s2", model_request_id="r9", attempt=1, body=_body())
	b = cap.capture_request(session_id="s2", model_request_id="r9", attempt=2, body=_body())
	assert a["body_hash"] == b["body_hash"]
	assert b["deduped"] is True
	rows = cap.captures_for_run("s2")
	assert len(rows) == 2
	assert {r["attempt"] for r in rows} == {1, 2}
	assert store.dir_size(store.captures_dir()) < 2 * 1024 * 1024


def test_credentials_are_never_stored() -> None:
	cap.set_capture_enabled("s3", True)
	body = _body() | {
		"api_key": "sk-secret-abcdef123456",
		"messages": [{"role": "user", "content": "Authorization: Bearer supersecrettoken123"}],
		"headers_echo": "Bearer abcDEF123456789",
	}
	row = cap.capture_request(session_id="s3", model_request_id="r1", attempt=1, body=body)
	assert row["state"] == REDACTED
	raw = gzip.open(cap._capture_locator(row["body_hash"]), "rb").read().decode("utf-8")
	for secret in ("supersecrettoken123", "sk-secret", "abcDEF123456789"):
		assert secret not in raw, secret
	# 原 body 不被观察者改动
	assert body["api_key"] == "sk-secret-abcdef123456"


def test_unserializable_body_is_partial_not_invented() -> None:
	cap.set_capture_enabled("s4", True)
	row = cap.capture_request(session_id="s4", model_request_id="r1", attempt=1, body={"x": {1, 2}})
	assert row["state"] == PARTIAL
	assert row["body_hash"].startswith("unserializable_")
	assert cap.resolve_capture(row["body_hash"])["state"] != COMPLETE


def test_capture_never_raises_on_write_failure(monkeypatch) -> None:
	cap.set_capture_enabled("s5", True)

	def _boom(*_a, **_k):
		raise OSError("disk full")

	monkeypatch.setattr(cap.os, "replace", _boom)
	row = cap.capture_request(session_id="s5", model_request_id="r1", attempt=1, body=_body())
	assert row["state"] == PARTIAL
	assert "写入失败" in row["note"]
	# 失败残片不得留下永久占盘的 .tmp（配额清理也不该把它当权威产物）
	assert list(store.captures_dir().rglob("*.tmp")) == []


def test_effective_params_survive_and_are_derived() -> None:
	cap.set_capture_enabled("s10", True)
	body = _body() | {"max_tokens": 4096, "temperature": 0.2, "stream_options": {"include_usage": True}}
	row = cap.capture_request(session_id="s10", model_request_id="r1", attempt=1, body=body)
	# max_tokens 不是凭证：子串匹配把它打码会让每次捕获都变 redacted
	assert row["state"] == COMPLETE
	doc = cap.resolve_capture(row["body_hash"])
	assert doc["body"]["max_tokens"] == 4096
	assert doc["effective_params"]["temperature"] == 0.2
	assert doc["effective_params"]["max_tokens"] == 4096
	assert "messages" not in doc["effective_params"]
	assert doc["effective_params_source"] == "derived_from_body"


def test_quota_recovers_stale_tmp_files() -> None:
	store.ensure_dirs()
	stale = store.captures_dir() / "abc123.json.gz.tmp"
	stale.write_bytes(b"z" * 2048)
	used = store.dir_size(store.diagnostics_root())
	out = store.enforce_quota(target=max(1, used // 2))
	assert not stale.exists()
	assert out["freed_bytes"] >= 2048


def test_resolve_missing_blob_reports_not_captured() -> None:
	doc = cap.resolve_capture("0" * 64)
	assert doc["state"] == "not_captured"
	assert doc["error"]


def test_response_identity_joins_onto_attempt() -> None:
	cap.set_capture_enabled("s6", True)
	row = cap.capture_request(session_id="s6", turn_id="t1", model_request_id="r1", attempt=1, body=_body())
	cap.record_response(session_id="s6", model_request_id="r1", attempt=1, body_hash=row["body_hash"], provider_request_id="req-abc", http_status=200, usage={"total_tokens": 3})
	joined = cap.captures_for_run("s6", "t1")[0]
	assert joined["provider_request_id"] == "req-abc"
	assert joined["http_status"] == 200


def test_env_enable_makes_experiment_processes_independent(monkeypatch) -> None:
	monkeypatch.setenv("XEYO_DIAGNOSTICS_CAPTURE_SESSIONS", "s7, s8")
	assert cap.capture_enabled("s7") is True
	assert cap.capture_enabled("s8") is True
	assert cap.capture_enabled("s9") is False


# ---------- 固定证据与基线 ----------


def test_pin_roundtrip_and_verifier_keeps_none_exit_code() -> None:
	doc = pins_mod.pin_run("s1", "t1", note="结果不对", expected="应该先跑测试")
	assert doc["pin_id"].startswith("pin_")
	ver = pins_mod.record_verifier("s1", "t1", name="pytest P0", command="pytest -m p0")
	assert ver["exit_code"] is None
	rows = pins_mod.pins_for_run("s1", "t1")
	assert {r["kind"] for r in rows} == {"run_mark", "verifier"}
	assert all(r["exit_code"] is None for r in rows if r["kind"] == "verifier")
	assert pins_mod.delete_pin(ver["pin_id"], "s1") is True
	assert len(pins_mod.pins_for_run("s1", "t1")) == 1


def test_verifier_zero_and_none_are_different_things() -> None:
	zero = pins_mod.record_verifier("s2", "t1", name="t", exit_code=0)
	two = pins_mod.record_verifier("s2", "t1", name="t", exit_code=2)
	assert zero["exit_code"] == 0 and two["exit_code"] == 2


def test_baseline_compare_states() -> None:
	assert pins_mod.compare_baseline("nope", {"a": 1})["state"] == "no_baseline"
	pins_mod.set_baseline("instr", {"system/identity": "x", "tools/Read": "y"})
	same = pins_mod.compare_baseline("instr", {"system/identity": "x", "tools/Read": "y"})
	assert same["state"] == "same"
	drift = pins_mod.compare_baseline("instr", {"system/identity": "changed", "tools/Glob": "z"})
	assert drift["state"] == "drift"
	assert [c["key"] for c in drift["changed"]] == ["system/identity"]
	assert drift["added"] == ["tools/Glob"] and drift["removed"] == ["tools/Read"]


# ---------- 配额 ----------


def test_quota_cleanup_spares_pinned_evidence() -> None:
	store.ensure_dirs()
	junk = store.reports_dir() / "junk.json"
	store.write_json(junk, {"a": "x" * 4000})
	keep = store.captures_dir() / "keep.gz"
	keep.parent.mkdir(parents=True, exist_ok=True)
	keep.write_bytes(b"y" * 4000)
	pins_mod.pin_run("s9", "t9", note="钉住这次故障的证据", pinned_files=[str(keep)])
	used = store.dir_size(store.diagnostics_root())
	out = store.enforce_quota(target=max(1, used // 4))
	assert keep.is_file(), "固定证据不得被配额清理掉"
	assert out["freed_bytes"] > 0
	assert out["shortfall"] >= 0


def test_report_saved_and_loaded() -> None:
	from diagnostics.collect import collect_run
	from diagnostics.report import build_report, load_report, report_id, save_report, to_markdown

	store.ensure_dirs()
	path = store.runs_dir() / "empty-audit.jsonl"
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text("", encoding="utf-8")
	doc = build_report(collect_run("s1", "t1", audit_path=path))
	file_path = save_report(doc)
	assert load_report(report_id(doc))["session_id"] == "s1"
	assert file_path.endswith(".json")
	md = to_markdown(doc)
	assert "不等于任务正确" in md or "已确认" in md
	assert "覆盖缺口" in md


def test_env_bytes_rejects_too_small_and_garbage(monkeypatch) -> None:
	import diagnostics.collect as c

	monkeypatch.setenv("XEYO_DIAGNOSTICS_AUDIT_BYTES", "garbage")
	assert c._env_bytes("XEYO_DIAGNOSTICS_AUDIT_BYTES", 4096) == 4096
	monkeypatch.setenv("XEYO_DIAGNOSTICS_AUDIT_BYTES", "10")
	assert c._env_bytes("XEYO_DIAGNOSTICS_AUDIT_BYTES", 4096) == 4096


def test_collect_requires_session_id() -> None:
	from diagnostics.collect import collect_run

	with pytest.raises(ValueError):
		collect_run("", "t1")


def test_read_helpers_survive_corrupt_rows(tmp_path) -> None:
	path = tmp_path / "x.jsonl"
	path.write_text('{"a":1}\nnot json\n[1,2]\n\n{"b":2}\n', encoding="utf-8")
	assert store.read_jsonl(path) == [{"a": 1}, {"b": 2}]
	assert store.read_jsonl(tmp_path / "missing.jsonl") == []
	assert store.read_json(tmp_path / "missing.json") is None
	bad = tmp_path / "bad.json"
	bad.write_text("{oops", encoding="utf-8")
	assert store.read_json(bad) is None


def test_write_json_is_atomic_and_sorted(tmp_path) -> None:
	target = tmp_path / "nested" / "doc.json"
	store.write_json(target, {"b": 2, "a": 1})
	assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1, "b": 2}
	assert list(target.parent.glob("*.tmp")) == []
