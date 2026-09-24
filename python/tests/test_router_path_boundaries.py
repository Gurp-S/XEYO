"""文件系统边界回归（workspace / references / media / memory 四个 router）。

口径：请求参数**不得**决定服务端去哪儿读 / 写 / 删文件。每条用例都对应一次
真实探针（``TestClient`` + 系统临时目录里的数据根），探针曾观察到的缺陷形态：

1. NUL / 控制字符路径 → ``Path.resolve()`` 抛 ``ValueError`` → HTTP 500
   （已修：边缘 422，中性结果型措辞）；
2. ``GET /v1/references/files?workspace=``（纯空白）→ ``os.path.realpath(" ")``
   归一成**服务端进程 CWD** 并把那里的文件名发给调用方（静默换根，已修：422）；
3. ``POST /v1/files`` 先把整个请求体读进内存再判 2 MiB 上限（实测 200 MB 也照读，
   已修：读满 limit+1 即停 + 413 + 正文截断置 ``truncated`` 旗标）。

其余路由（绝对路径 / ``..`` / ``%2e%2e`` / ``vic/tim`` / UNC / junction）经探针
验证**已经**被 ``server.workspace_fs.resolve_in_workspace`` 的 realpath 包含检查
挡住（403），这里作为回归锁住，防止以后有人换掉那层。

注意：本机控制台是 GBK，用例断言消息一律 ASCII。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
	sys.path.insert(0, str(_ROOT))

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from server.routers import media as media_router
from server.app import app
from server.deps import _pool

SECRET_MARK = "TOP-SECRET-OUTSIDE-DO-NOT-READ"
NUL = "\x00"


def _client() -> TestClient:
	return TestClient(app, raise_server_exceptions=False)


def _layout(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
	"""ws（工作区）+ outside（禁区：secret.txt / victim.json），并把 cwd 钉到 ws。"""
	ws = tmp_path / "ws"
	ws.mkdir()
	(ws / "ok.txt").write_text("inside-ok", encoding="utf-8")
	outside = tmp_path / "outside"
	outside.mkdir()
	secret = outside / "secret.txt"
	secret.write_text(SECRET_MARK, encoding="utf-8")
	victim = outside / "victim.json"
	victim.write_text('{"k": 1}', encoding="utf-8")
	_pool.set_cwd(str(ws))
	return ws, outside, secret, victim


# ── 1. 控制字符：曾经 500，现在必须 422 ─────────────────────────────

def _workspace_path_calls() -> list[tuple[str, Callable[[], object]]]:
	client = _client()
	nul = f"a{NUL}b.txt"
	return [
		("entries", lambda: client.get("/v1/workspace/entries", params={"path": nul})),
		("file_get", lambda: client.get("/v1/workspace/file", params={"path": nul})),
		("file_stat", lambda: client.get("/v1/workspace/file/stat", params={"path": nul})),
		(
			"file_put",
			lambda: client.put("/v1/workspace/file", json={"path": nul, "text": "x"}),
		),
		("file_delete", lambda: client.delete("/v1/workspace/file", params={"path": nul})),
		("outline", lambda: client.get("/v1/workspace/outline", params={"path": nul})),
		("file_diff", lambda: client.get("/v1/workspace/file/diff", params={"path": nul})),
		("map_explain", lambda: client.post("/v1/workspace/map/explain", json={"id": nul})),
	]


_PATH_CALLS = _workspace_path_calls()


@pytest.mark.parametrize(
	"label,call", _PATH_CALLS, ids=[c[0] for c in _PATH_CALLS]
)
def test_workspace_control_char_path_is_422_not_500(label: str, call) -> None:
	r = call()
	assert r.status_code == 422, (label, r.status_code, r.text[:200])
	body = r.json()
	assert body["error"]["type"] == "invalid_request"
	assert "U+0000" in body["error"]["message"]


@pytest.mark.parametrize("ch", ["\n", "\t", "\x1a"])
def test_workspace_path_any_control_char_rejected(tmp_path: Path, ch: str) -> None:
	_layout(tmp_path)
	r = _client().get("/v1/workspace/file", params={"path": f"ok.txt{ch}"})
	assert r.status_code == 422
	assert r.json()["error"]["type"] == "invalid_request"


# ── 2. 越界写法：已经被包含检查挡住（回归锁 + 不泄漏） ──────────────

def _hostile_values() -> list[tuple[str, str]]:
	return [
		("abs_win", "C:\\users\\public\\secret.txt"),
		("abs_forward", "C:/users/public/secret.txt"),
		("dotdot", "../outside/secret.txt"),
		("dotdot_deep", "../../../..//outside/secret.txt"),
		("pct_encoded", "%2e%2e/outside/secret.txt"),
		("nested", "vic/tim"),
		("unc_slash", "//127.0.0.1/C$/Windows/win.ini"),
		("unc_backslash", "\\\\127.0.0.1\\C$\\Windows\\win.ini"),
		("drive_root", "C:" + os.sep + "Windows/win.ini"),
		("empty", ""),
		("blank", "   "),
		("dot", "."),
		("dot_dir", ".."),
	]


@pytest.mark.parametrize("label,value", _hostile_values())
def test_workspace_file_read_never_leaves_outside(
	tmp_path: Path, label: str, value: str
) -> None:
	_layout(tmp_path)
	client = _client()
	if label == "pct_encoded":
		# 字面 %2e%2e（真·编码穿越）必须走 raw URL，params 会被再编码一次。
		r = client.get("/v1/workspace/file?path=%2e%2e/outside/secret.txt")
	else:
		r = client.get("/v1/workspace/file", params={"path": value})
	assert r.status_code != 500, (label, r.text[:200])
	assert SECRET_MARK not in r.text, label
	assert r.status_code in (400, 403, 404, 422), (label, r.status_code, r.text[:160])


@pytest.mark.parametrize("label,value", _hostile_values())
def test_workspace_entries_never_lists_outside(
	tmp_path: Path, label: str, value: str
) -> None:
	_layout(tmp_path)
	r = _client().get("/v1/workspace/entries", params={"path": value})
	assert r.status_code != 500, (label, r.text[:200])
	names: list[str] = []
	if r.status_code == 200:
		names = [e["name"] for e in r.json()["entries"]]
	assert SECRET_MARK not in r.text, label
	assert "secret.txt" not in names and "victim.json" not in names, label


def test_workspace_delete_cannot_touch_json_outside(
	tmp_path: Path, monkeypatch
) -> None:
	"""pin_id 事故同型：一次请求删掉机器上任意 ``*.json``。写通道开启下也必须 403。"""
	monkeypatch.setenv("XEYO_WORKSPACE_FS_WRITABLE", "1")
	_ws, _outside, _secret, victim = _layout(tmp_path)
	client = _client()
	for value in (str(victim), "../outside/victim.json", f"a{NUL}b.json"):
		r = client.delete("/v1/workspace/file", params={"path": value})
		assert r.status_code in (403, 422), (value, r.status_code, r.text[:160])
		assert victim.is_file(), value
	assert victim.read_text(encoding="utf-8") == '{"k": 1}'


def test_workspace_write_cannot_create_file_outside(
	tmp_path: Path, monkeypatch
) -> None:
	monkeypatch.setenv("XEYO_WORKSPACE_FS_WRITABLE", "1")
	_ws, outside, _secret, _victim = _layout(tmp_path)
	pwn = outside / "pwn.txt"
	r = _client().put("/v1/workspace/file", json={"path": str(pwn), "text": "x"})
	assert r.status_code == 403
	assert not pwn.exists()


# ── 3. junction（Windows 无需管理员）不得成为逃出工作区的门 ─────────

def _make_junction(link: Path, target: Path) -> bool:
	try:
		proc = subprocess.run(
			["cmd", "/c", "mklink", "/J", str(link), str(target)],
			capture_output=True,
			text=True,
		)
	except OSError:
		return False
	return proc.returncode == 0 and link.is_dir()


def test_workspace_junction_to_outside_is_denied(tmp_path: Path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_WORKSPACE_FS_WRITABLE", "1")
	ws, outside, secret, _victim = _layout(tmp_path)
	link = ws / "link"
	if not _make_junction(link, outside):
		pytest.skip("junction creation needs cmd/mklink (Windows only)")
	# junction 不是 symlink：Path.is_symlink() 为 False，只能靠 realpath 包含检查。
	assert not link.is_symlink()
	client = _client()
	for r in (
		client.get("/v1/workspace/file", params={"path": "link/secret.txt"}),
		client.get("/v1/workspace/file/stat", params={"path": "link/secret.txt"}),
		client.get("/v1/workspace/entries", params={"path": "link"}),
		client.get("/v1/workspace/outline", params={"path": "link/secret.txt"}),
		client.delete("/v1/workspace/file", params={"path": "link/secret.txt"}),
		client.put("/v1/workspace/file", json={"path": "link/pwn.txt", "text": "x"}),
	):
		assert r.status_code == 403, (r.status_code, r.text[:160])
		assert SECRET_MARK not in r.text
	assert secret.is_file()
	assert not (outside / "pwn.txt").exists()
	entries = client.get("/v1/workspace/entries", params={"path": ""}).json()["entries"]
	assert "secret.txt" not in [e["name"] for e in entries]


# ── 4. references：绝对路径按设计允许，空白值不得静默换根 ────────────

@pytest.mark.parametrize("value", ["", " ", "   ", f"a{NUL}b", "\t"])
def test_references_blank_workspace_is_422(tmp_path: Path, value: str) -> None:
	"""曾观察到：纯空白 workspace 被 realpath 归一成服务端进程 CWD 并列出其文件名。"""
	_layout(tmp_path)
	r = _client().get("/v1/references/files", params={"workspace": value})
	assert r.status_code == 422, (repr(value), r.status_code, r.text[:160])
	assert SECRET_MARK not in r.text
	# "" 由 FastAPI 的 min_length 兜（detail 形状）；纯空白必须是路由边缘 422。
	body = r.json()
	if isinstance(body, dict) and "error" in body:
		assert body["error"]["type"] == "invalid_request"


def test_references_arbitrary_workspace_allowed_by_design(tmp_path: Path) -> None:
	"""桌面 app 的 space 由用户自选：绝对路径是合法输入，只受 loopback 门禁约束。"""
	_ws, outside, _secret, _victim = _layout(tmp_path)
	client = _client()
	r = client.get("/v1/references/files", params={"workspace": str(outside)})
	assert r.status_code == 200
	body = r.json()
	assert body["ok"] is True
	assert sorted(body["files"]) == ["secret.txt", "victim.json"]
	# limit 仍是硬顶，扫描规模不随目录失控。
	r2 = client.get(
		"/v1/references/files", params={"workspace": str(outside), "limit": 1}
	)
	assert len(r2.json()["files"]) == 1


def test_references_missing_param_is_422(tmp_path: Path) -> None:
	_layout(tmp_path)
	assert _client().get("/v1/references/files").status_code == 422


# ── 5. media：digest 必须是 64 hex；上传文件名不得决定落点 ──────────

@pytest.mark.parametrize(
	"raw",
	["..%2f..%2foutside%2fsecret.txt", "%00" + "a" * 64, "a" * 63, "a" * 65, "zzzz"],
)
def test_media_digest_never_resolves_outside(tmp_path: Path, raw: str) -> None:
	_layout(tmp_path)
	r = _client().get(f"/v1/media/{raw}")
	assert r.status_code in (404, 422), (raw, r.status_code, r.text[:160])
	assert SECRET_MARK not in r.text


def test_upload_file_name_cannot_escape_upload_dir(tmp_path: Path, monkeypatch) -> None:
	uploads = tmp_path / "uploads"
	uploads.mkdir()
	monkeypatch.setattr(media_router, "UPLOAD_DIR", uploads)
	r = _client().post(
		"/v1/files", files={"file": ("../../../../evil.txt", b"hello", "text/plain")}
	)
	assert r.status_code == 200, r.text[:200]
	body = r.json()
	assert "/" not in body["id"] and "\\" not in body["id"]
	assert Path(body["path"]).parent == uploads
	assert list(uploads.iterdir())
	assert not any(tmp_path.rglob("evil.txt"))
	# 既有键不变，新增 truncated（GUI 只读 filename / text，多余键安全）。
	assert {"id", "filename", "bytes", "text", "path"} <= set(body)
	assert body["truncated"] is False


def test_upload_file_reads_are_bounded(tmp_path: Path, monkeypatch) -> None:
	"""曾观察到：200 MB 请求体整份读进内存之后才判 2 MiB 上限。"""
	uploads = tmp_path / "uploads"
	uploads.mkdir()
	monkeypatch.setattr(media_router, "UPLOAD_DIR", uploads)
	consumed = {"bytes": 0}
	real_read = UploadFile.read

	async def counting_read(self, size: int = -1) -> bytes:
		chunk = await real_read(self, size)
		consumed["bytes"] += len(chunk)
		return chunk

	monkeypatch.setattr(UploadFile, "read", counting_read)
	r = _client().post(
		"/v1/files",
		files={"file": ("big.txt", b"a" * (6 * 1024 * 1024), "text/plain")},
	)
	assert r.status_code == 413, r.text[:200]
	assert r.json()["error"]["type"] == "invalid_request"
	assert consumed["bytes"] <= media_router._MAX_FILE_BYTES + 1, consumed
	assert not list(uploads.iterdir())


def test_upload_text_truncation_is_visible(tmp_path: Path, monkeypatch) -> None:
	uploads = tmp_path / "uploads"
	uploads.mkdir()
	monkeypatch.setattr(media_router, "UPLOAD_DIR", uploads)
	monkeypatch.setattr(media_router, "_MAX_INLINE_CHARS", 16)
	r = _client().post(
		"/v1/files", files={"file": ("note.txt", b"0123456789" * 5, "text/plain")}
	)
	assert r.status_code == 200
	body = r.json()
	assert body["truncated"] is True
	assert body["bytes"] == 50
	assert body["text"].endswith("[truncated]")


# ── 6. memory：scope / session_id 是查询值，永不进路径（回归锁） ─────

@pytest.mark.parametrize(
	"value", ["../..", "user", "", "   ", f"a{NUL}b", "\\\\127.0.0.1\\C$", "C:\\users"]
)
def test_memory_notes_scope_never_selects_a_directory(tmp_path: Path, value: str) -> None:
	ws, _outside, secret, _victim = _layout(tmp_path)
	before = sorted(p.name for p in ws.iterdir())
	r = _client().get("/v1/memory/notes", params={"scope": value})
	assert r.status_code == 200, (value, r.status_code, r.text[:160])
	body = r.json()
	assert set(body) == {"workspace_id", "notes"}
	assert isinstance(body["workspace_id"], str) and "/" not in body["workspace_id"]
	assert SECRET_MARK not in r.text
	assert sorted(p.name for p in ws.iterdir()) == before


@pytest.mark.parametrize(
	"value", ["../..", "..", f"a{NUL}b", "\\\\127.0.0.1\\C$\\share", "session", "   "]
)
def test_memory_compact_unknown_session_is_404_not_fs_touch(
	tmp_path: Path, value: str
) -> None:
	ws, _outside, _secret, victim = _layout(tmp_path)
	r = _client().post("/v1/memory/compact", json={"session_id": value})
	assert r.status_code in (404, 422), (value, r.status_code, r.text[:160])
	assert victim.is_file()
	assert sorted(p.name for p in ws.iterdir()) == ["ok.txt"]


def test_resolve_in_workspace_never_leaks_a_bare_valueerror(tmp_path: Path) -> None:
	"""必经点自己吞掉底层异常：控制字符要变成拒绝事实，不是每个入口一个 500。"""
	from server.workspace_fs import resolve_in_workspace

	ws = tmp_path / "ws"
	ws.mkdir()
	for bad in (f"a{NUL}b", f"a{NUL}/b", f"{NUL}"):
		try:
			resolve_in_workspace(str(ws), bad)
		except PermissionError:
			continue
		raise AssertionError(f"{bad!r} 未转成 PermissionError")
	# 越界仍是拒绝，普通路径照常解析——收紧不能把好的那侧一起打死。
	try:
		resolve_in_workspace(str(ws), "../outside")
	except PermissionError:
		pass
	else:
		raise AssertionError("../outside 未被拒绝")
	assert resolve_in_workspace(str(ws), "notes.txt").name == "notes.txt"
	assert resolve_in_workspace(str(ws), ".") == ws.resolve()
