"""诊断层定向测试夹具。

``tests/conftest.py`` 已把 XEYO_HOME / SESSIONS / USAGE 钉进 tmp 并复位审计单例；
这里只补诊断层自己的进程内缓存复位与审计文件构造。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from diagnostics import store


@pytest.fixture(autouse=True)
def _reset_diag_caches(monkeypatch, tmp_path):
	monkeypatch.setenv("XEYO_DIAGNOSTICS_DIR", str(tmp_path / "diag"))
	store.reset_store_caches()
	yield
	store.reset_store_caches()


@pytest.fixture
def audit_file(tmp_path) -> Path:
	return tmp_path / "audit.jsonl"


@pytest.fixture
def write_audit(audit_file):
	def _write(rows: list[dict[str, Any]]) -> Path:
		audit_file.write_text(
			"".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
			encoding="utf-8",
		)
		return audit_file

	return _write


@pytest.fixture
def collect(write_audit):
	"""写一批审计行再 collect，返回 RunEvidence。"""
	from diagnostics.collect import collect_run

	def _collect(rows: list[dict[str, Any]], *, turn_id: str = "t1", session_id: str = "s1"):
		path = write_audit(rows)
		return collect_run(session_id, turn_id, audit_path=path)

	return _collect
