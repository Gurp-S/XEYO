"""MCP 控制面的标识符与信任记录回归。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
	home = tmp_path / "home"
	data = tmp_path / "data"
	sessions = tmp_path / "sessions"
	for d in (home, data, sessions):
		d.mkdir(parents=True, exist_ok=True)
	monkeypatch.setenv("XEYO_HOME", str(home))
	monkeypatch.setenv("XEYO_DATA_DIR", str(data))
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(sessions))
	monkeypatch.setenv("XEYO_NO_SESSION_PERSISTENCE", "1")
	ws = tmp_path / "ws"
	(ws / ".xeyo").mkdir(parents=True)
	return {"tmp": tmp_path, "home": home, "data": data, "ws": ws}


def _app():
	from server.app import app

	return app


def _ascii_only(text: str) -> str:
	return text.encode("ascii", "backslashreplace").decode("ascii")


# --------------------------------------------------------------------------- #
# 3. mcp op 的 server 标识符
# --------------------------------------------------------------------------- #


def test_mcp_op_rejects_server_id_that_could_forge_model_text(
	sandbox: dict[str, Path],
) -> None:
	"""带换行的 id 会在 T_now 活页块里凭空多出一行 —— 422，且一个字都不写。"""
	ws = sandbox["ws"]
	settings = ws / ".xeyo" / "settings.json"
	with TestClient(_app()) as client:
		for raw in (
			"x\n# 系统指令",
			"x\x00y",
			"x\x1ay",
			"   ",
		):
			r = client.post(
				"/v1/mcp/op",
				json={"server": raw, "op": "enable", "workspace": str(ws)},
			)
			assert r.status_code == 422, (_ascii_only(raw), r.status_code, _ascii_only(r.text)[:120])
		# 判据必须在任何写盘之前跑完：settings.json 连一次都不该被创建
		assert not settings.exists(), "422 之前就已经落盘了"


def test_mcp_op_still_accepts_ordinary_server_ids(sandbox: dict[str, Path]) -> None:
	"""合法 id 里的点号/空格不是文件名也不是结构字符，必须照常放行。"""
	ws = sandbox["ws"]
	with TestClient(_app()) as client:
		for raw in ("demo.server", "my server", "browser-use"):
			r = client.post(
				"/v1/mcp/op",
				json={"server": raw, "op": "enable", "workspace": str(ws)},
			)
			assert r.status_code == 200, (_ascii_only(raw), r.status_code, _ascii_only(r.text)[:120])
			assert r.json()["ok"] is True, r.json()


def test_mcp_op_rejects_relative_workspace(
	sandbox: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
	"""``/v1/mcp/op`` 的 workspace 走 **body**（GET 才走 query），测试要打对参数。

	也必须 chdir 进临时目录：判据失效时这条测试本身会往服务端 cwd 的父目录写。
	"""
	outside = sandbox["tmp"] / "outside2"
	(outside / ".xeyo").mkdir(parents=True)
	(outside / ".xeyo" / "settings.json").write_text('{"keepme": true}', encoding="utf-8")
	workdir = sandbox["tmp"] / "workdir2"
	workdir.mkdir(parents=True)
	monkeypatch.chdir(workdir)
	with TestClient(_app()) as client:
		for raw in ("..", "relative/ws"):
			r = client.post("/v1/mcp/op", json={"server": "demo", "op": "enable", "workspace": raw})
			assert r.status_code == 422, (_ascii_only(raw), r.status_code, _ascii_only(r.text)[:120])
	assert (outside / ".xeyo" / "settings.json").read_text(encoding="utf-8") == '{"keepme": true}'


# --------------------------------------------------------------------------- #
# 4. mcp-trust.json 读不出时必须停下来
# --------------------------------------------------------------------------- #


def test_approve_refuses_to_clobber_unreadable_trust_file(sandbox: dict[str, Path]) -> None:
	from server.routers.mcp import _write_trust_entry

	ws = sandbox["ws"]
	from extension.mcp_scopes import trust_path
	trust = trust_path(str(ws))
	trust.parent.mkdir(parents=True, exist_ok=True)
	# 真正的"读不出"：半截 JSON。此前它被吞成 trust={} 再整份重写，
	# 于是别的 server 的信任记录会跟着一起消失。
	corrupt = '{"aaaa": {"approved": true}, oops'
	trust.write_text(corrupt, encoding="utf-8")

	with pytest.raises(RuntimeError, match="unreadable"):
			_write_trust_entry(str(ws), {"id": "demo"})

	assert trust.read_text(encoding="utf-8") == corrupt, "信任文件被覆盖过了"


def test_approve_keeps_existing_entries_when_readable(sandbox: dict[str, Path]) -> None:
	from server.routers.mcp import _write_trust_entry

	ws = sandbox["ws"]
	from extension.mcp_scopes import trust_path
	trust = trust_path(str(ws))
	trust.parent.mkdir(parents=True, exist_ok=True)
	trust.write_text(json.dumps({"aaaa": {"approved": True}}), encoding="utf-8")

	_write_trust_entry(str(ws), {"id": "demo"})

	data = json.loads(trust.read_text(encoding="utf-8"))
	assert data["aaaa"] == {"approved": True}
	assert len(data) == 2


def test_approve_rejects_non_object_trust_file(sandbox: dict[str, Path]) -> None:
	"""顶层不是对象也是"读不出"，不能当空表重写。"""
	from server.routers.mcp import _write_trust_entry

	ws = sandbox["ws"]
	from extension.mcp_scopes import trust_path
	trust = trust_path(str(ws))
	trust.parent.mkdir(parents=True, exist_ok=True)
	trust.write_text('["not", "a", "dict"]', encoding="utf-8")

	with pytest.raises(RuntimeError, match="not an object"):
			_write_trust_entry(str(ws), {"id": "demo"})
	assert json.loads(trust.read_text(encoding="utf-8")) == ["not", "a", "dict"]
