"""GET /v1/references/files 契约测试（@ 文件引用候选源）。

覆盖：顶层枚举、q 子串过滤、重目录剪枝、排序（深度→字典序）、limit、
坏 workspace、loopback 门禁（TestClient host=testclient 直接放行）。
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
	sys.path.insert(0, str(_ROOT))

from fastapi.testclient import TestClient

from server.app import app


def _make_ws(tmp_path: Path) -> Path:
	(tmp_path / "src" / "deep").mkdir(parents=True)
	(tmp_path / "README.md").write_text("hi", encoding="utf-8")
	(tmp_path / "src" / "main.py").write_text("print(1)", encoding="utf-8")
	(tmp_path / "src" / "deep" / "util.py").write_text("x = 1", encoding="utf-8")
	# 重目录应被整棵剪枝
	(tmp_path / "node_modules" / "pkg").mkdir(parents=True)
	(tmp_path / "node_modules" / "pkg" / "index.js").write_text(";", encoding="utf-8")
	return tmp_path


def _client() -> TestClient:
	return TestClient(app)


def test_references_files_top_level(tmp_path) -> None:
	ws = _make_ws(tmp_path)
	r = _client().get("/v1/references/files", params={"workspace": str(ws)})
	assert r.status_code == 200
	body = r.json()
	assert body["ok"] is True
	# 空查询只列文件（目录不进结果），node_modules 剪枝
	assert body["files"] == ["README.md", "src/main.py", "src/deep/util.py"]


def test_references_files_query_filter_and_order(tmp_path) -> None:
	ws = _make_ws(tmp_path)
	r = _client().get("/v1/references/files", params={"workspace": str(ws), "q": "PY"})
	assert r.status_code == 200
	# 大小写不敏感；深度浅的在前
	assert r.json()["files"] == ["src/main.py", "src/deep/util.py"]


def test_references_files_limit(tmp_path) -> None:
	ws = _make_ws(tmp_path)
	r = _client().get(
		"/v1/references/files", params={"workspace": str(ws), "limit": 2}
	)
	assert r.status_code == 200
	assert len(r.json()["files"]) == 2


def test_references_files_bad_workspace(tmp_path) -> None:
	r = _client().get(
		"/v1/references/files", params={"workspace": str(tmp_path / "nope")}
	)
	assert r.status_code == 200
	body = r.json()
	assert body["ok"] is False
	assert body["files"] == []


def test_references_files_requires_params() -> None:
	r = _client().get("/v1/references/files")
	assert r.status_code == 422  # FastAPI 校验：workspace 必填
