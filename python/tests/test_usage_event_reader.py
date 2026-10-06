from __future__ import annotations

import json
from pathlib import Path

from usage import ledger
from usage.event_reader import read_ledger


def test_ledger_keeps_newest_event_beyond_old_limit(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	monkeypatch.setattr(ledger, "_events_cache", None)
	path = ledger.events_path()
	path.write_text('{"request_id":"old"}\n' * 80_000 + '{"request_id":"newest"}', encoding="utf-8")
	rows = ledger._read_events()
	assert len(rows) == 80_001
	assert rows[-1]["request_id"] == "newest"
	status = ledger.local_store_status()
	assert status["rows_read"] == status["store_raw_lines"] == 80_001
	assert status["truncated_by_read_limit"] is False


def test_rows_and_status_share_one_scan_and_invalidate_on_append(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	monkeypatch.setattr(ledger, "_events_cache", None)
	path = ledger.events_path()
	path.write_bytes(b'{"id":1}\n\n{bad}\n[]\n\xff\n{"id":2}')
	reads = []
	actual = ledger.read_ledger
	def tracked(path):
		reads.append(path)
		return actual(path)
	monkeypatch.setattr(ledger, "read_ledger", tracked)
	assert [r["id"] for r in ledger._read_events()] == [1, 2]
	status = ledger.local_store_status()
	assert len(reads) == 1
	assert status["store_raw_lines"] == 6
	assert status["store_blank_lines"] == 1
	assert status["store_unparsable_lines"] == 3
	with path.open("ab") as stream:
		stream.write(b'\n{"id":3}\n')
	assert ledger._read_events()[-1]["id"] == 3
	assert len(reads) == 2
	assert ledger.local_store_status()["store_raw_lines"] == 7
	assert len(reads) == 2


def test_missing_empty_and_unreadable_are_distinct(tmp_path, monkeypatch):
	path = tmp_path / "events.jsonl"
	assert read_ledger(path).store == "missing_store"
	path.write_text("", encoding="utf-8")
	assert read_ledger(path).store == "empty_store"
	def denied(*args, **kwargs):
		raise PermissionError("denied")
	monkeypatch.setattr(Path, "open", denied)
	assert read_ledger(path).store == "unreadable_store"


def test_truncate_and_replace_invalidate_cached_rows(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	monkeypatch.setattr(ledger, "_events_cache", None)
	path = ledger.events_path()
	path.write_text('{"id":1}\n{"id":2}\n', encoding="utf-8")
	assert len(ledger._read_events()) == 2
	path.write_text('{"id":3}\n', encoding="utf-8")
	assert ledger._read_events() == [{"id": 3}]
	path.unlink()
	assert ledger._read_events() == []
	assert ledger.local_store_status()["store"] == "missing_store"
