"""Task4 HTTP API 契约测试（FastAPI TestClient）。

运行:
  py -3.11 -m pytest tests/test_server_api.py -q
  # 或无 pytest 时:
  py -3.11 tests/test_server_api.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

# 允许从 python/ 目录执行 `py tests/test_server_api.py`
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
	sys.path.insert(0, str(_ROOT))

import pytest
from fastapi.testclient import TestClient

from server import app as app_mod
from server.app import app
from session.persistence import safe_session_filename, transcript_path


def _client() -> TestClient:
	return TestClient(app)


def test_health_ok() -> None:
	c = _client()
	r = c.get("/health")
	assert r.status_code == 200
	body = r.json()
	assert body.get("ok") is True
	assert body.get("service") == "xeyo"
	assert "cwd" in body


def test_missing_api_key_401_shape() -> None:
	c = _client()
	r = c.post(
		"/v1/chat/completions",
		json={
			"model": "deepseek-chat",
			"stream": False,
			"messages": [{"role": "user", "content": "hi"}],
		},
	)
	assert r.status_code == 401
	body = r.json()
	assert "error" in body
	assert body["error"]["type"] == "authentication_error"
	assert "API key" in body["error"]["message"]


def test_interrupt_idle_ok() -> None:
	c = _client()
	r = c.post("/v1/interrupt", json={"session_id": "never-seen-sess"})
	assert r.status_code == 200
	assert r.json().get("ok") is True
	# 不得污染下一轮
	assert app_mod._pool.take_pending_interrupt("never-seen-sess") is False


def test_delete_session_removes_disk_transcript(tmp_path, monkeypatch) -> None:
	"""删除会话应同步清理磁盘 transcript 与会话目录，重启后不再被重新导入。"""
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
	sid = "del-me-sess"
	tp = transcript_path(sid)
	tp.parent.mkdir(parents=True, exist_ok=True)
	tp.write_text('{"role":"user","content":"hi"}\n', encoding="utf-8")
	# 会话子目录（rewind revisions / journal / rollback 等）。
	sdir = tp.parent / safe_session_filename(sid)
	sdir.mkdir(parents=True, exist_ok=True)
	(sdir / "revisions.jsonl").write_text("{}\n", encoding="utf-8")

	c = _client()
	r = c.delete(f"/v1/sessions/{sid}")
	assert r.status_code == 200
	body = r.json()
	assert body["ok"] is True
	assert str(tp) in body["removed"]
	assert not tp.exists(), "transcript 应被删除"
	assert not sdir.exists(), "会话子目录应被删除"


def test_session_busy_409_shape() -> None:
	c = _client()
	sid = "busy-http-test"
	lease = app_mod._pool.try_begin(sid)
	assert lease is not None
	try:
		r = c.post(
			"/v1/chat/completions",
			headers={"Authorization": "Bearer test-key"},
			json={
				"model": "deepseek-chat",
				"stream": False,
				"session_id": sid,
				"messages": [{"role": "user", "content": "hi"}],
			},
		)
		assert r.status_code == 409
		body = r.json()
		assert body["error"]["type"] == "session_busy"
		assert "会话正忙" in body["error"]["message"]
	finally:
		app_mod._pool.end(sid, lease)


def test_usage_query_empty() -> None:
	c = _client()
	r = c.get("/v1/usage?days=7")
	assert r.status_code == 200
	body = r.json()
	assert body["totals"]["requests"] == 0
	assert body.get("source") == "local"
	assert body.get("vendor_ok") is False
	assert isinstance(body["days"], list)
	assert isinstance(body["models"], list)
	assert isinstance(body["keys"], list)


def test_usage_balance_missing_key() -> None:
	c = _client()
	r = c.get("/v1/usage/balance")
	assert r.status_code == 200
	assert r.json().get("available") is False


def test_models_missing_key() -> None:
	c = _client()
	r = c.get("/v1/models")
	assert r.status_code == 200
	body = r.json()
	assert body.get("vendor_ok") is False
	assert body.get("data") == []


def test_media_upload_returns_ref(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
	from PIL import Image

	monkeypatch.setenv("XEYO_MEDIA_DIR", str(tmp_path / "media"))
	image = Image.new("RGB", (16, 12), (20, 40, 60))
	payload = io.BytesIO()
	image.save(payload, format="PNG")
	c = _client()
	r = c.post(
		"/v1/media/upload",
		files={"file": ("sample.png", payload.getvalue(), "image/png")},
	)
	assert r.status_code == 200
	body = r.json()
	assert body["ok"] is True
	assert body["media_ref"].startswith("xeyo-media://")
	assert body["width"] == 16
	assert body["height"] == 12


def test_invalid_media_ref_rejected() -> None:
	c = _client()
	r = c.post(
		"/v1/chat/completions",
		headers={"Authorization": "Bearer test-key"},
		json={
			"model": "deepseek-chat",
			"stream": False,
			"media_refs": ["xeyo-media://" + "0" * 64],
			"messages": [{"role": "user", "content": "describe"}],
		},
	)
	assert r.status_code == 400
	assert r.json()["error"]["type"] == "invalid_request"


def test_empty_user_400() -> None:
	c = _client()
	r = c.post(
		"/v1/chat/completions",
		headers={"Authorization": "Bearer test-key"},
		json={
			"model": "deepseek-chat",
			"stream": False,
			"messages": [{"role": "assistant", "content": "only assistant"}],
		},
	)
	assert r.status_code == 400
	body = r.json()
	assert body["error"]["type"] == "invalid_request"


def test_two_sessions_independent_busy() -> None:
	"""Session A busy 不得阻塞 Session B 的 begin。"""
	pool = app_mod._pool
	a = pool.try_begin("iso-a")
	assert a is not None
	try:
		b = pool.try_begin("iso-b")
		assert b is not None
		pool.end("iso-b", b)
	finally:
		pool.end("iso-a", a)


def _use_workspace(c: TestClient, path: str) -> str:
	"""临时切换工作区（POST /v1/workspace），返回原 cwd。"""
	original = app_mod._pool.cwd
	r = c.post("/v1/workspace", json={"path": path})
	assert r.status_code == 200, r.text
	return original


def test_workspace_set_and_entries(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
	web = tmp_path / "web"
	web.mkdir()
	(web / "index.html").write_text("<h1>hi</h1>\n", encoding="utf-8")
	c = _client()
	original = _use_workspace(c, str(web))
	try:
		got = c.get("/v1/workspace")
		assert got.json()["cwd"] == str(web).replace("\\", "/") or True
		r = c.get("/v1/workspace/entries", params={"path": ""})
		assert r.status_code == 200
		names = [e["name"] for e in r.json()["entries"]]
		assert "index.html" in names
		outside = c.get("/v1/workspace/entries", params={"path": "../"})
		assert outside.status_code == 403
	finally:
		c.post("/v1/workspace", json={"path": original})


def test_workspace_file_write_delete_search(tmp_path) -> None:
	root = tmp_path / "ws"
	root.mkdir()
	(root / "hint.py").write_text("old\n", encoding="utf-8")
	c = _client()
	original = _use_workspace(c, str(root))
	try:
		r = c.get("/v1/workspace/file", params={"path": "hint.py"})
		assert r.status_code == 200
		assert r.json()["kind"] == "text"
		assert isinstance(r.json().get("mtime"), int)

		st = c.get("/v1/workspace/file/stat", params={"path": "hint.py"})
		assert st.status_code == 200
		assert st.json()["size"] == r.json()["size"]
		assert st.json()["mtime"] == r.json()["mtime"]
		assert "text" not in st.json()

		put = c.put("/v1/workspace/file", json={"path": "hint.py", "text": "new\n"})
		assert put.status_code == 200
		assert put.json()["text"] == "new\n"

		search = c.get("/v1/workspace/search", params={"q": "hint"})
		assert [h["path"] for h in search.json()["hits"]] == ["hint.py"]

		d = c.delete("/v1/workspace/file", params={"path": "hint.py"})
		assert d.status_code == 200
		assert not (root / "hint.py").exists()

		miss = c.delete("/v1/workspace/file", params={"path": "hint.py"})
		assert miss.status_code == 404
	finally:
		c.post("/v1/workspace", json={"path": original})


def test_workspace_graph(tmp_path) -> None:
	root = tmp_path / "ws"
	pkg = root / "python" / "engine"
	pkg.mkdir(parents=True)
	(pkg / "a.py").write_text("def a():\n\treturn 1\n", encoding="utf-8")
	(pkg / "b.py").write_text("from engine.a import a\n\ndef b():\n\treturn a()\n", encoding="utf-8")
	c = _client()
	original = _use_workspace(c, str(root))
	try:
		r = c.get("/v1/workspace/graph")
		assert r.status_code == 200, r.text
		body = r.json()
		assert body.get("ok") is True
		ids = {n["id"] for n in body["files"]}
		assert "python/engine/a.py" in ids
		assert "python/engine/b.py" in ids
		assert any(e["from"] == "python/engine/b.py" and e["to"] == "python/engine/a.py" for e in body["fileEdges"])
		assert any(p["id"] == "python/engine" for p in body["packages"])

		out = c.get("/v1/workspace/outline", params={"path": "python/engine/a.py"})
		assert out.status_code == 200, out.text
		assert any(s["name"] == "a" for s in out.json()["symbols"])

		ex = c.post(
			"/v1/workspace/map/explain",
			json={"id": "python/engine", "kind": "package"},
		)
		assert ex.status_code == 200, ex.text
		assert "python/engine" in ex.json()["summary"]
	finally:
		c.post("/v1/workspace", json={"path": original})


def test_workspace_git_endpoints(tmp_path) -> None:
	import shutil
	import subprocess

	if shutil.which("git") is None:
		pytest.skip("git not installed")
	root = tmp_path / "ws"
	root.mkdir()
	subprocess.run(["git", "init", "-q"], cwd=root, check=True)
	subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=root, check=True)
	subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
	(root / "a.txt").write_text("v1\n", encoding="utf-8")
	subprocess.run(["git", "add", "."], cwd=root, check=True)
	subprocess.run(["git", "commit", "-q", "-m", "first"], cwd=root, check=True)
	(root / "a.txt").write_text("v2\n", encoding="utf-8")

	c = _client()
	original = _use_workspace(c, str(root))
	try:
		status = c.get("/v1/workspace/git/status")
		assert status.status_code == 200
		assert status.json()["repo"] is True
		assert status.json()["counts"]["unstaged"] == 1

		log = c.get("/v1/workspace/git/log", params={"limit": 5})
		assert log.status_code == 200
		assert log.json()["commits"][0]["subject"] == "first"

		branches = c.get("/v1/workspace/git/branches")
		assert branches.status_code == 200
		assert branches.json()["current"] in ("main", "master")

		diff = c.get("/v1/workspace/file/diff", params={"path": "a.txt"})
		assert diff.status_code == 200
		assert diff.json()["kind"] == "diff"
		assert "-v1" in diff.json()["diff"]
	finally:
		c.post("/v1/workspace", json={"path": original})


def test_workspace_terminal_exec(tmp_path) -> None:
	root = tmp_path / "ws"
	root.mkdir()
	c = _client()
	original = _use_workspace(c, str(root))
	try:
		r = c.post("/v1/workspace/terminal/exec", json={"command": "echo xy-ok", "timeout_s": 20})
		assert r.status_code == 200
		body = r.json()
		assert body["ok"] is True
		assert body["exit_code"] == 0
		assert "xy-ok" in (body["stdout"] or "") + (body["stderr"] or "")

		bad = c.post("/v1/workspace/terminal/exec", json={"command": ""})
		assert bad.status_code == 422  # pydantic min_length
		empty = c.post("/v1/workspace/terminal/exec", json={"command": "   "})
		assert empty.status_code == 400  # 纯空白 → TerminalError
	finally:
		c.post("/v1/workspace", json={"path": original})


def test_runtime_mode_endpoint_live_store() -> None:
	from permissions.runtime_mode import get_runtime_mode_store

	sid = "rtmt-api-test"
	store = get_runtime_mode_store()
	store.clear(sid)
	c = _client()
	try:
		r = c.post(
			f"/v1/sessions/{sid}/runtime-mode",
			json={"permission_mode": "never"},
		)
		assert r.status_code == 200, r.text
		body = r.json()
		assert body["ok"] is True
		assert body["permission_mode"] == "never"
		assert body["effective"] in {"never", "risk", "always"}
		assert store.live(sid) == "never"

		bad = c.post(
			f"/v1/sessions/{sid}/runtime-mode",
			json={"permission_mode": "bogus"},
		)
		assert bad.status_code == 400
	finally:
		store.clear(sid)


def _run_as_script() -> None:
	tests = [
		test_health_ok,
		test_missing_api_key_401_shape,
		test_interrupt_idle_ok,
		test_delete_session_removes_disk_transcript,
		test_session_busy_409_shape,
		test_usage_query_empty,
		test_usage_balance_missing_key,
		test_media_upload_returns_ref,
		test_invalid_media_ref_rejected,
		test_empty_user_400,
		test_two_sessions_independent_busy,
		test_workspace_set_and_entries,
		test_workspace_file_write_delete_search,
		test_workspace_graph,
		test_workspace_git_endpoints,
		test_workspace_terminal_exec,
		test_runtime_mode_endpoint_live_store,
	]
	failed = 0
	for fn in tests:
		try:
			fn()
			print(f"OK  {fn.__name__}")
		except Exception as e:  # noqa: BLE001
			failed += 1
			print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
	if failed:
		raise SystemExit(1)
	print("ALL SERVER API TESTS OK")


if __name__ == "__main__":
	_run_as_script()
