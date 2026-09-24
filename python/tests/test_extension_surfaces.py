"""三方代码面（skills / extensions / plugins）的路由边缘回归。

每条测试对应一个用 TestClient 实测过的缺陷（探针脚本先复现、后修）：

1. ``POST /v1/extensions/settings`` 落盘后的回读视图在 try 之外 → 500 逃出。
2. ``GET /v1/plugins/market`` 整条路由无兜底 → 控制字符 workspace 以
   ``ValueError: stat: embedded null character in path`` 逃出为 500。
3. ``POST /v1/plugins/remove`` 在 try 之外读锁文件 → 锁文件损坏时 500 逃出。
4. 相对 ``workspace``（``..`` / ``%2e%2e``）按**服务端进程 cwd**解析 → 把
   ``.xeyo/settings.json`` 写到调用者选的目录；现在一律 422 且零落盘。
5. ``source`` 含空白 / 控制字符 → 422（此前空白源返回 200 的模糊 message）。
6. 启停键（skill / plugin / mcp）为空白或 sanitizer 别名（``greeter.``）→ 422，
   且不留下半途生效的状态。
7. ``GET /v1/plugins/market``：市场目录缺文件 / 坏 JSON 都返回 ``sources: []``
   → 新增 ``registry`` 状态位区分「没有目录」与「目录读不出」。
8. ``POST /v1/plugins/update``：删旧-copy 新之后仍调 ``plugin_store.install``
   （同名即冲突）→ 磁盘已换体、账本留旧 hash，恒失败且 ``drift`` 从此常亮。

约定：只写 OS 临时目录（XEYO_HOME / XEYO_DATA_DIR / XEYO_SESSIONS_DIR 全量重定向），
断言里不打印中文、不输出 ¥（Windows GBK 控制台）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from server.plugin_market import market_registry_path


# --------------------------------------------------------------------------- #
# 夹具：数据根全部落到临时目录，绝不碰真实 ~/.xeyo
# --------------------------------------------------------------------------- #


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


def _enable_extensions(ws: Path, **extra: object) -> None:
	settings = ws / ".xeyo" / "settings.json"
	settings.write_text(json.dumps({"enabled_extensions": True, **extra}), encoding="utf-8")


def _mk_plugin(dir_path: Path, name: str) -> Path:
	"""合法插件目录（manifest 至少声明一项 skills/mcp/prompts/hooks）。"""
	dir_path.mkdir(parents=True, exist_ok=True)
	(dir_path / "plugin.json").write_text(
		json.dumps({"name": name, "version": "0.1.0", "skills": ["skills/a"]}),
		encoding="utf-8",
	)
	skill = dir_path / "skills" / "a"
	skill.mkdir(parents=True, exist_ok=True)
	(skill / "SKILL.md").write_text("---\ndescription: hi\n---\nbody\n", encoding="utf-8")
	return dir_path


def _ascii_only(text: str) -> str:
	return text.encode("ascii", "backslashreplace").decode("ascii")


# --------------------------------------------------------------------------- #
# 1. POST /v1/extensions/settings：回读视图失败不得以 500 逃出
# --------------------------------------------------------------------------- #


def _app():
	from server.app import app

	return app


def test_post_settings_survives_broken_view(sandbox: dict[str, Path]) -> None:
	ws = sandbox["ws"]
	_enable_extensions(ws, plugins=["not", "a", "dict"])
	with TestClient(_app()) as client:
		r = client.post(
			"/v1/extensions/settings",
			params={"workspace": str(ws)},
			json={"skills": {"keepme": {"enabled": True}}},
		)
	assert r.status_code == 200, r.text
	body = r.json()
	assert body["ok"] is False
	assert isinstance(body.get("message"), str)
	# 已生效的写入要如实回报，不能只留一个 500。
	assert body["applied"]["skills"] == [{"name": "keepme", "enabled": True}]
	settings = json.loads((ws / ".xeyo" / "settings.json").read_text(encoding="utf-8"))
	assert settings["skills"]["keepme"]["enabled"] is True


def test_post_settings_rejects_relative_workspace_without_writing(sandbox: dict[str, Path]) -> None:
	escaped = Path(os.getcwd()).parent / ".xeyo" / "settings.json"
	before = escaped.read_text(encoding="utf-8") if escaped.is_file() else None
	with TestClient(_app()) as client:
		for raw in ("..", "%2e%2e", ".", "relative/ws", "\x00", "a\nb", "a\x1ab"):
			r = client.post(
				"/v1/extensions/settings",
				params={"workspace": raw},
				json={"enabled_extensions": True},
			)
			assert r.status_code == 422, (raw, r.status_code, _ascii_only(r.text)[:120])
			assert r.json()["error"]["type"] == "invalid_request"
	after = escaped.read_text(encoding="utf-8") if escaped.is_file() else None
	assert after == before  # 服务端 cwd 之上没有被写入


def test_get_surfaces_reject_hostile_workspace(sandbox: dict[str, Path]) -> None:
	ws = sandbox["ws"]
	_enable_extensions(ws)
	cases = {
		"relative-dotdot": "..",
		"relative-encoded": "%2e%2e%2f",
		"nul": "x\x00y",
		"newline": "x\ny",
		"sub": "x\x1ay",
	}
	with TestClient(_app()) as client:
		for label, raw in cases.items():
			for path in ("/v1/skills", "/v1/extensions/settings", "/v1/plugins", "/v1/plugins/market"):
				r = client.get(path, params={"workspace": raw})
				assert r.status_code == 422, (label, path, r.status_code, _ascii_only(r.text)[:120])
		# 不存在但绝对的工作区：如实报错，不渲染成「什么都没装」
		r = client.get("/v1/skills", params={"workspace": str(ws / "nope")})
		assert r.status_code == 422
		# 合法绝对路径照常可用
		ok = client.get("/v1/skills", params={"workspace": str(ws)})
		assert ok.status_code == 200
		assert ok.json()["ok"] is True


def test_blank_workspace_still_falls_back_to_cwd(sandbox: dict[str, Path]) -> None:
	with TestClient(_app()) as client:
		for raw in ("", "   "):
			r = client.get("/v1/skills", params={"workspace": raw})
			assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- #
# 2. GET /v1/plugins/market：500 逃逸 + 「没有目录」vs「目录读不出」
# --------------------------------------------------------------------------- #


def test_market_control_char_workspace_no_longer_500(sandbox: dict[str, Path]) -> None:
	with TestClient(_app()) as client:
		r = client.get("/v1/plugins/market", params={"workspace": "x\x00y"})
	assert r.status_code == 422, (r.status_code, _ascii_only(r.text)[:120])


def test_market_registry_state_distinguishes_missing_from_broken(sandbox: dict[str, Path]) -> None:
	ws = sandbox["ws"]
	_enable_extensions(ws, plugin_market=True)
	home = sandbox["home"]
	reg = market_registry_path()
	assert Path(str(reg)).parent == home or str(home) in str(reg)
	with TestClient(_app()) as client:
		r_missing = client.get("/v1/plugins/market", params={"workspace": str(ws)})
		assert r_missing.status_code == 200, r_missing.text
		body_missing = r_missing.json()
		assert body_missing["enabled"] is True
		assert body_missing["sources"] == []
		assert body_missing["registry"] == "missing"

		reg.write_text("{oops", encoding="utf-8")
		r_broken = client.get("/v1/plugins/market", params={"workspace": str(ws)})
		assert r_broken.status_code == 200, r_broken.text
		body_broken = r_broken.json()
		assert body_broken["sources"] == []
		assert body_broken["registry"] == "invalid"
		assert body_broken["registry"] != body_missing["registry"]

		reg.write_text(json.dumps({"version": 1, "sources": [{"name": "x", "source": "github:a/b"}]}), encoding="utf-8")
		r_ok = client.get("/v1/plugins/market", params={"workspace": str(ws)}).json()
		assert r_ok["registry"] == "ok"
		assert isinstance(r_ok["sources"], list)


# --------------------------------------------------------------------------- #
# 3. POST /v1/plugins/remove：锁文件损坏不得以 500 逃出
# --------------------------------------------------------------------------- #


def test_remove_with_corrupt_lock_returns_ok_false(sandbox: dict[str, Path]) -> None:
	ws = sandbox["ws"]
	_enable_extensions(ws)
	lock = ws / ".xeyo" / "plugins-lock.json"
	lock.write_text("{broken", encoding="utf-8")
	with TestClient(_app()) as client:
		r = client.post("/v1/plugins/remove", params={"workspace": str(ws)}, json={"name": "demo"})
	assert r.status_code == 200, (r.status_code, _ascii_only(r.text)[:160])
	body = r.json()
	assert body["ok"] is False
	assert isinstance(body.get("message"), str)


def test_plugin_name_edge_validation(sandbox: dict[str, Path]) -> None:
	ws = sandbox["ws"]
	_enable_extensions(ws)
	bad = ["", "   ", ".", "..", "a/b", "a\\b", "x\x00y", "demo.", ".demo", "n" * 300]
	with TestClient(_app()) as client:
		for raw in bad:
			for path in ("/v1/plugins/update", "/v1/plugins/remove"):
				r = client.post(path, params={"workspace": str(ws)}, json={"name": raw})
				assert r.status_code == 422, (path, _ascii_only(raw), r.status_code)
		# 结构形状保持稳定：合法但未注册的插件名 → 200 + ok False（update）/ existed False（remove）
		good = client.post("/v1/plugins/update", params={"workspace": str(ws)}, json={"name": "ghost"})
		assert good.status_code == 200
		assert good.json()["ok"] is False


# --------------------------------------------------------------------------- #
# 4. install：源与 manifest 名的边缘
# --------------------------------------------------------------------------- #


def test_install_rejects_blank_and_control_source(sandbox: dict[str, Path]) -> None:
	ws = sandbox["ws"]
	_enable_extensions(ws)
	with TestClient(_app()) as client:
		for raw in ("   ", "x\x00y", "a\nb"):
			r = client.post("/v1/plugins/install", params={"workspace": str(ws)}, json={"source": raw})
			assert r.status_code == 422, (_ascii_only(raw), r.status_code, _ascii_only(r.text)[:120])


def test_install_rejects_dotdot_manifest_name_before_touching_state(sandbox: dict[str, Path]) -> None:
	"""manifest 名 ``..`` + allow_update 曾会 rmtree 掉整个 ``<ws>/.xeyo``（实测）。

	拦截点已下沉到扩展层：``manifest._name_ok`` 直接判名字非法，
	``plugin_fetcher._confined_plugin_dir`` 再挡一次越界落点。因此这里不再是
	路由边缘的 422，而是 200 + 如实点名原因 —— 关键是**任何写盘都没发生**。
	"""
	ws = sandbox["ws"]
	_enable_extensions(ws)
	canary = ws / ".xeyo" / "canary"
	canary.mkdir(parents=True)
	(canary / "k.txt").write_text("x", encoding="utf-8")
	lock = ws / ".xeyo" / "plugins-lock.json"
	evil = _mk_plugin(sandbox["tmp"] / "src-evil", "..")
	with TestClient(_app()) as client:
		r = client.post(
			"/v1/plugins/install",
			params={"workspace": str(ws)},
			json={"source": str(evil), "allow_update": True},
		)
		assert r.status_code == 200, (r.status_code, _ascii_only(r.text)[:140])
		body = r.json()
		assert body["ok"] is False
		assert "non-dot" in _ascii_only(str(body.get("message"))), body
	assert canary.is_dir(), "manifest/落点校验失效：`.xeyo` 目录被删了"
	assert (ws / ".xeyo").is_dir()
	assert not lock.exists()


def test_install_and_duplicate_registration_is_visible(sandbox: dict[str, Path]) -> None:
	"""同名重复安装：第二次必须显式失败，不能按调用方看不见的顺序静默覆盖。"""
	ws = sandbox["ws"]
	_enable_extensions(ws)
	src = _mk_plugin(ws.parent / "src-demo", "demo")
	with TestClient(_app()) as client:
		first = client.post("/v1/plugins/install", params={"workspace": str(ws)}, json={"source": str(src)})
		assert first.status_code == 200, first.text
		assert first.json()["ok"] is True, first.json()
		assert "demo" in first.json()["registered"]
		dup = client.post("/v1/plugins/install", params={"workspace": str(ws)}, json={"source": str(src)})
		assert dup.status_code == 200
		dup_body = dup.json()
		assert dup_body["ok"] is False
		assert "already" in _ascii_only(str(dup_body.get("message")))
		view = client.get("/v1/plugins", params={"workspace": str(ws)}).json()
		assert view["ok"] is True
		assert [p["name"] for p in view["plugins"]] == ["demo"]
		assert view["registered"] == ["demo"]
		removed = client.post("/v1/plugins/remove", params={"workspace": str(ws)}, json={"name": "demo"})
		assert removed.json()["existed"] is True
		again = client.post("/v1/plugins/remove", params={"workspace": str(ws)}, json={"name": "demo"})
		assert again.json()["existed"] is False


def test_duplicate_skill_registration_reports_single_winning_source(sandbox: dict[str, Path]) -> None:
	"""workspace 与 home 同名 skill：清单里只能有一条，且必须能看出胜出的是哪一源。"""
	ws = sandbox["ws"]
	home = sandbox["home"]
	_enable_extensions(ws)
	for root, marker in ((ws / ".xeyo" / "skills", "ws"), (home / "skills", "home")):
		d = root / "dup"
		d.mkdir(parents=True, exist_ok=True)
		(d / "SKILL.md").write_text(f"---\ndescription: {marker} skill\n---\nbody\n", encoding="utf-8")
	with TestClient(_app()) as client:
		body = client.get("/v1/skills", params={"workspace": str(ws)}).json()
	assert body["ok"] is True
	entries = [s for s in body["skills"] if s["name"] == "dup"]
	assert len(entries) == 1, entries
	assert entries[0]["source"], entries[0]


# --------------------------------------------------------------------------- #
# 5. 共用谓词本身
# --------------------------------------------------------------------------- #


def test_require_workspace_arg_predicate() -> None:
	from server.routers.extensions import require_workspace_arg, require_entry_name

	assert require_workspace_arg(None) == ""
	assert require_workspace_arg("  ") == ""
	for bad in ("..", "rel/ws", "x\x00y"):
		with pytest.raises(HTTPException) as exc:
			require_workspace_arg(bad)
		assert exc.value.status_code == 422
	for bad in ("", "  ", ".", "..", "a/b", "victim.", "x\x00y", "s" * 300):
		with pytest.raises(HTTPException) as exc:
			require_entry_name(bad, field="plugin name")
		assert exc.value.status_code == 422
	assert require_entry_name("demo", field="plugin name") == "demo"


# --------------------------------------------------------------------------- #
# 6. POST /v1/plugins/update：删旧-copy 新之后账本必须跟着换体
# --------------------------------------------------------------------------- #


def test_update_round_trips_and_leaves_no_drift(sandbox: dict[str, Path]) -> None:
	"""此前 update 恒失败且留下隐形伤害：文件已经换体、lockfile 仍是旧 hash。

	路由把 ``_plugins_view`` 的 ``drift`` 一起回给前端，所以"失败"之后面板会
	一直报漂移 —— 这不是干净的失败，而是把状态改坏了再说不。
	"""
	ws = sandbox["ws"]
	_enable_extensions(ws)
	src = _mk_plugin(sandbox["tmp"] / "src-demo", "demo")
	(src / "skills" / "a" / "SKILL.md").write_text("---\ndescription: hi\n---\nv1\n", encoding="utf-8")
	with TestClient(_app()) as client:
		installed = client.post(
			"/v1/plugins/install", params={"workspace": str(ws)}, json={"source": str(src)}
		)
		assert installed.status_code == 200, installed.text
		assert installed.json()["ok"] is True, installed.json()

		(src / "skills" / "a" / "SKILL.md").write_text("---\ndescription: hi\n---\nv2\n", encoding="utf-8")

		updated = client.post(
			"/v1/plugins/update", params={"workspace": str(ws)}, json={"name": "demo"}
		)
		assert updated.status_code == 200, updated.text
		body = updated.json()
		assert body["ok"] is True, body
		assert body["drift"] == [], body["drift"]
		assert body["updated"]["name"] == "demo"

		live = ws / ".xeyo" / "plugins" / "demo" / "skills" / "a" / "SKILL.md"
		assert live.read_text(encoding="utf-8").endswith("v2\n")
