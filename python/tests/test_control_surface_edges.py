"""``server/routers/control.py`` 路由边缘回归（13 条路线逐条走查）。

复用的既有谓词（不另立判据）：

- ``extensions.require_workspace_arg`` —— ``workspace`` / ``scope`` 这类会被
  ``Path(...).resolve()`` / ``os.path.abspath()`` **二次取根**的调用方字符串。
- ``sessions._require_stable_id``（经 ``control._require_store_id`` 薄封装）——
  进 store 当句柄的 id。``PermissionGrantStore.revoke`` 自己 ``strip()``，
  所以修复前 ``" <id>"`` 与 ``"<id>"`` 打到同一条 grant。

修复前实测到的 before：

* ``POST /v1/settings/memory?workspace=../../../escape`` → 200，并在服务端 cwd
  之外真的建出 ``escape/.xeyo/settings.json``。
* ``DELETE /v1/permissions/grants/%20<id>`` → 200 ok:true，那条真实 grant 消失。
* ``POST /v1/permission/resolve {approved:true, outcome:"deny-all", remember:true}``
  → 200 ok:true，item 变成 allow，并落了永久 always-allow grant。
* ``GET /v1/permissions/grants?scope=ws`` / ``?scope=%20%20`` → 200 + ``grants: []``。
* ``PUT /v1/settings/rewind-gc {keep_recent:0}`` → 200 + ok:false（GUI 只看 res.ok，
  于是渲染成"保存成功"）；父路径被占位时 ``FileExistsError`` 裸逃出 500。

可写根全部只在夹具里用 monkeypatch.setenv 重定向到 OS 临时目录；断言消息一律 ASCII。
``POST /v1/settings/memory/snapshot`` 会真起 120s 子进程，只做静态断言。
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import permissions.store as permissions_store
from memory.memory_switches import MEMORY_SWITCHES
from permissions.ask_store import PendingAskStore
from server.routers.control import router as control_router

_SWITCH_KEY = MEMORY_SWITCHES[0][0]


@pytest.fixture()
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
	"""可写根全指 tmp，进程 cwd 挪到 ``tmp/srv/a/b``。

	cwd 挪深是有意义的：修复前的相对 ``workspace=../../../escape`` 正是按**服务端
	进程 cwd**取根，于是落到 ``tmp/escape``——谁都没登记过的目录。
	"""
	home = tmp_path / "home"
	srv = tmp_path / "srv" / "a" / "b"
	ws = tmp_path / "ws"
	for d in (home, srv, ws, tmp_path / "data", tmp_path / "sessions"):
		d.mkdir(parents=True, exist_ok=True)
	(ws / ".xeyo").mkdir(parents=True, exist_ok=True)
	monkeypatch.setenv("XEYO_HOME", str(home))
	monkeypatch.setenv("XEYO_DATA_DIR", str(tmp_path / "data"))
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
	monkeypatch.setenv("XEYO_DIAGNOSTICS_DIR", str(tmp_path / "diag"))
	monkeypatch.setenv("XEYO_GRANT_STORE", str(tmp_path / "grants.json"))
	monkeypatch.setenv("XEYO_GRANT_PERSIST", "off")
	monkeypatch.setenv("XEYO_REWIND_GC_CONFIG", str(tmp_path / "gc" / "rewind_gc.json"))
	monkeypatch.setenv("XEYO_NO_SESSION_PERSISTENCE", "1")
	monkeypatch.chdir(srv)
	monkeypatch.setattr(
		permissions_store,
		"_default_grant_store",
		permissions_store.PermissionGrantStore(persist=False),
	)
	monkeypatch.setattr(
		permissions_store,
		"_default_store",
		permissions_store.PendingPermissionStore(ttl_seconds=0),
	)
	monkeypatch.setattr(
		"permissions.ask_store._default_ask_store", PendingAskStore(), raising=False
	)
	app = FastAPI()
	app.include_router(control_router)
	return {
		"tmp": tmp_path,
		"srv": srv,
		"ws": ws,
		"gc": tmp_path / "gc" / "rewind_gc.json",
		"client": TestClient(app, raise_server_exceptions=False),
	}


def _ascii_only(text: str) -> str:
	return text.encode("ascii", "backslashreplace").decode("ascii")


def _body(r: Any) -> str:
	return _ascii_only(f"{r.status_code} {r.text}")


def _grants() -> list[str]:
	return [g.grant_id for g in permissions_store.default_grant_store().list()]


def _seed_grant(scope: str, fingerprint: str) -> str:
	grant = permissions_store.default_grant_store().add(
		tool_name="Bash", fingerprint=fingerprint, scope=scope, actor="desktop"
	)
	assert grant is not None
	return grant.grant_id


def _seed_permission(request_id: str) -> None:
	permissions_store.default_permission_store().create(
		session_id="sess-edge",
		turn_id="turn-edge",
		tool_name="Bash",
		tool_input={"command": "npm install left-pad"},
		reason="needs_confirmation",
		prompt="Allow Bash?",
		request_id=request_id,
		matched_rule="bash_policy_ask",
	)


# --------------------------------------------------------------------------- #
# 1. GET/POST /v1/settings/memory —— 相对 workspace 二次取根
# --------------------------------------------------------------------------- #


def test_relative_workspace_post_never_escapes_server_cwd(sandbox: dict[str, Any]) -> None:
	c = sandbox["client"]
	escaped = sandbox["tmp"] / "escape" / ".xeyo" / "settings.json"
	r = c.post(
		"/v1/settings/memory",
		params={"workspace": "../../../escape"},
		json={"updates": {_SWITCH_KEY: "1"}},
	)
	assert r.status_code == 422, _body(r)
	assert not escaped.exists(), "relative workspace still wrote outside the server cwd"


def test_relative_workspace_get_and_body_field_blocked(sandbox: dict[str, Any]) -> None:
	c = sandbox["client"]
	r = c.get("/v1/settings/memory", params={"workspace": "../.."})
	assert r.status_code == 422, _body(r)
	r = c.post("/v1/settings/memory", json={"workspace": "../../x", "updates": {}})
	assert r.status_code == 422, _body(r)


def test_control_char_workspace_is_422_not_200(sandbox: dict[str, Any]) -> None:
	# 修复前：200 + ok:false，detail 是 "stat: embedded null character in path"。
	c = sandbox["client"]
	r = c.get("/v1/settings/memory", params={"workspace": "..\u0000x"})
	assert r.status_code == 422, _body(r)
	r = c.post("/v1/settings/memory", params={"workspace": "a/b"}, json={"updates": {}})
	assert r.status_code == 422, _body(r)


def test_abs_workspace_still_returns_200(sandbox: dict[str, Any]) -> None:
	"""不过窄：真实存在的绝对工作区读写照常 200。"""
	c = sandbox["client"]
	ws = str(sandbox["ws"])
	r = c.get("/v1/settings/memory", params={"workspace": ws})
	assert r.status_code == 200, _body(r)
	assert r.json()["ok"] is True
	r = c.post(
		"/v1/settings/memory", params={"workspace": ws}, json={"updates": {_SWITCH_KEY: "1"}}
	)
	assert r.status_code == 200, _body(r)
	assert r.json()["memory"][_SWITCH_KEY] == "1"
	assert (sandbox["ws"] / ".xeyo" / "settings.json").is_file()


def test_unknown_switch_receipt_contract_kept(sandbox: dict[str, Any]) -> None:
	# 本路由族钉死的取值回执（test_memory_switches）：未知键仍是 200 + ok:false。
	c = sandbox["client"]
	r = c.post(
		"/v1/settings/memory",
		params={"workspace": str(sandbox["ws"])},
		json={"updates": {"XEYO_NOPE_SUCH_SWITCH": "1"}},
	)
	assert r.status_code == 200, _body(r)
	assert r.json()["ok"] is False


# --------------------------------------------------------------------------- #
# 2. DELETE /v1/permissions/grants/{grant_id} —— revoke() 的 strip() 换错身份
# --------------------------------------------------------------------------- #


def test_grant_revoke_whitespace_alias_blocked(sandbox: dict[str, Any]) -> None:
	c = sandbox["client"]
	gid = _seed_grant(str(sandbox["ws"]), "v2:aaa111")
	r = c.delete(f"/v1/permissions/grants/%20{gid}")
	assert r.status_code == 422, _body(r)
	assert _grants() == [gid], "whitespace-prefixed id revoked the real grant"
	r = c.delete(f"/v1/permissions/grants/{gid}%20")
	assert r.status_code == 422, _body(r)
	assert _grants() == [gid]


def test_grant_revoke_traversal_and_overlong_blocked(sandbox: dict[str, Any]) -> None:
	c = sandbox["client"]
	gid = _seed_grant(str(sandbox["ws"]), "v2:eee555")
	for raw in ("%2e%2e", "%2e", "f" * 3000):
		r = c.delete(f"/v1/permissions/grants/{raw}")
		assert r.status_code == 422, f"{raw} -> {_body(r)}"
	r = c.delete("/v1/permissions/grants/a/b")
	assert r.status_code == 404, _body(r)
	assert _grants() == [gid]


def test_grant_revoke_legit_id_still_works(sandbox: dict[str, Any]) -> None:
	c = sandbox["client"]
	gid = _seed_grant(str(sandbox["ws"]), "v2:bbb222")
	r = c.delete(f"/v1/permissions/grants/{gid}")
	assert r.status_code == 200, _body(r)
	assert r.json()["ok"] is True
	assert _grants() == []
	# 未知但形态合法的 id 仍是 200 + ok:false（既有用例钉死的 not-found 回执）。
	# reason 也钉住：客户端靠它把"这条已不在台账"和"撤销失败请重试"分开说。
	r = c.delete("/v1/permissions/grants/deadbeefdeadbeef")
	assert r.status_code == 200, _body(r)
	assert r.json()["ok"] is False
	assert r.json()["reason"] == "grant_not_found", _body(r)


# --------------------------------------------------------------------------- #
# 3. GET /v1/permissions/grants?scope= —— 相对/空白 scope 谎报「没有授权」
# --------------------------------------------------------------------------- #


def test_grants_list_scope_must_be_absolute_dir(sandbox: dict[str, Any]) -> None:
	c = sandbox["client"]
	gid = _seed_grant(str(sandbox["ws"]), "v2:ccc333")
	r = c.get("/v1/permissions/grants", params={"scope": str(sandbox["ws"])})
	assert r.status_code == 200, _body(r)
	assert [g["grant_id"] for g in r.json()["grants"]] == [gid], "filter broke legit dirs"
	for bad in ("ws", "  ", "", "..\u0000z", "a/b"):
		r = c.get("/v1/permissions/grants", params={"scope": bad})
		assert r.status_code == 422, f"scope={bad!r} -> {_body(r)}"
	r = c.get("/v1/permissions/grants")
	assert r.status_code == 200, _body(r)
	assert len(r.json()["grants"]) == 1


def test_grants_list_missing_dir_is_422_not_empty_ok(sandbox: dict[str, Any]) -> None:
	c = sandbox["client"]
	_seed_grant(str(sandbox["ws"]), "v2:ddd444")
	r = c.get("/v1/permissions/grants", params={"scope": str(sandbox["tmp"] / "nope")})
	assert r.status_code == 422, _body(r)


# --------------------------------------------------------------------------- #
# 4. POST /v1/permission/resolve —— 拼错的 outcome 不得静默改写裁决
# --------------------------------------------------------------------------- #


def test_resolve_ambiguous_outcome_is_refused(sandbox: dict[str, Any]) -> None:
	c = sandbox["client"]
	_seed_permission("edgereq1")
	before = len(_grants())
	r = c.post(
		"/v1/permission/resolve",
		json={"request_id": "edgereq1", "approved": True, "outcome": "deny-all", "remember": True},
	)
	assert r.status_code == 422, _body(r)
	item = permissions_store.default_permission_store().get("edgereq1")
	assert item is not None
	# 修复前：resolved=True / approved=True / user_choice="allow" + 永久 grant。
	assert item.resolved is False
	assert item.user_choice == ""
	assert len(_grants()) == before


def test_resolve_legit_outcomes_still_work(sandbox: dict[str, Any]) -> None:
	c = sandbox["client"]
	_seed_permission("edgereq2")
	r = c.post(
		"/v1/permission/resolve",
		json={"request_id": "edgereq2", "approved": True, "outcome": "ALLOW", "remember": True},
	)
	assert r.status_code == 200, _body(r)
	assert r.json()["ok"] is True
	assert r.json()["grant_id"]
	# 兼容旧客户端：不发 outcome 时按 approved 推导。
	_seed_permission("edgereq3")
	r = c.post("/v1/permission/resolve", json={"request_id": "edgereq3", "approved": False})
	assert r.status_code == 200, _body(r)
	assert r.json()["ok"] is True
	assert permissions_store.default_permission_store().get("edgereq3").approved is False
	r = c.post("/v1/permission/resolve", json={"request_id": "nosuchid", "approved": True})
	assert r.status_code == 200, _body(r)
	assert r.json()["ok"] is False


def test_resolve_rejects_ambiguous_request_id(sandbox: dict[str, Any]) -> None:
	c = sandbox["client"]
	_seed_permission("edgereq4")
	for bad in ("", "   ", "a/b", "x" * 300, "edgereq4 "):
		r = c.post("/v1/permission/resolve", json={"request_id": bad, "approved": True})
		assert r.status_code == 422, _body(r)
	assert permissions_store.default_permission_store().get("edgereq4").resolved is False


# --------------------------------------------------------------------------- #
# 5. POST /v1/ask/resolve —— 作答文本进模型注意力，长度要有上界
# --------------------------------------------------------------------------- #


def test_ask_answer_length_bound(sandbox: dict[str, Any]) -> None:
	c = sandbox["client"]
	from permissions.ask_store import default_ask_store

	ask = default_ask_store()
	ask.create(question="q", session_id="s", turn_id="t", request_id="edgeask1", options=[])
	r = c.post("/v1/ask/resolve", json={"request_id": "edgeask1", "answer": "z" * 250_000})
	assert r.status_code == 422, _body(r)
	assert ask.get("edgeask1").resolved is False
	r = c.post(
		"/v1/ask/resolve",
		json={"request_id": "edgeask1", "answer": "use the temp dir", "actor": "desktop"},
	)
	assert r.status_code == 200, _body(r)
	assert r.json()["ok"] is True


def test_ask_rejects_ambiguous_ids(sandbox: dict[str, Any]) -> None:
	c = sandbox["client"]
	r = c.post("/v1/ask/resolve", json={"request_id": "  edgeask2", "answer": "hi"})
	assert r.status_code == 422, _body(r)
	r = c.post(
		"/v1/ask/resolve",
		json={"request_id": "other-id", "answer": "hi", "actor": "a" * 4096},
	)
	assert r.status_code == 422, _body(r)
	r = c.post("/v1/ask/resolve", json={"request_id": "other-id", "answer": "hi"})
	assert r.status_code == 200, _body(r)
	assert r.json()["ok"] is False


# --------------------------------------------------------------------------- #
# 6. PUT/GET /v1/settings/rewind-gc —— 非法值不再谎报成功，写失败不再裸 500
# --------------------------------------------------------------------------- #


def test_rewind_gc_negative_rejected_as_4xx(sandbox: dict[str, Any]) -> None:
	c = sandbox["client"]
	r = c.put("/v1/settings/rewind-gc", json={"keep_recent": 0})
	assert r.status_code == 422, _body(r)
	assert not sandbox["gc"].exists(), "rejected value still wrote the config"
	r = c.put("/v1/settings/rewind-gc", json={"max_bytes": -5})
	assert r.status_code == 422, _body(r)


def test_rewind_gc_valid_roundtrip_still_200(sandbox: dict[str, Any]) -> None:
	c = sandbox["client"]
	r = c.put("/v1/settings/rewind-gc", json={"keep_recent": 3, "max_bytes": 4096})
	assert r.status_code == 200, _body(r)
	assert r.json()["keep_recent"] == 3
	r = c.get("/v1/settings/rewind-gc")
	assert r.status_code == 200, _body(r)
	assert r.json()["max_bytes"] == 4096
	assert "defaults" in r.json()


def test_rewind_gc_distinguishes_corrupt_config_from_unset(sandbox: dict[str, Any]) -> None:
	"""损坏的配置文件不许讲成"没设置过"。

	``read_rewind_gc_config`` 对"缺文件 / 解不动 / 顶层不是对象"一律回同一份空默认
	——GC 继续按默认档跑是刻意的，但控制面必须能把"你的设置其实早就读不出来了"
	区分开，否则调用方以为自己写过的值仍然生效。
	"""
	c = sandbox["client"]
	gc = sandbox["gc"]
	gc.parent.mkdir(parents=True, exist_ok=True)

	assert c.get("/v1/settings/rewind-gc").json()["config_state"] == "absent"

	gc.write_text('{"keep_recent": 5}', encoding="utf-8")
	body = c.get("/v1/settings/rewind-gc").json()
	assert body["config_state"] == "ok", body
	assert body["keep_recent"] == 5

	gc.write_text("{oops", encoding="utf-8")
	body = c.get("/v1/settings/rewind-gc").json()
	assert body["config_state"] == "unreadable", body
	assert body["keep_recent"] is None, "读不出时不许继续沿用上一个值"

	gc.write_text('["not", "a", "dict"]', encoding="utf-8")
	assert c.get("/v1/settings/rewind-gc").json()["config_state"] == "invalid"


def test_rewind_gc_write_failure_is_structured_500(
	sandbox: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
	# 修复前：write_rewind_gc_config 的 mkdir 抛 FileExistsError，裸逃出路由。
	c = sandbox["client"]
	blocker = sandbox["tmp"] / "blocker"
	blocker.write_text("not a dir", encoding="utf-8")
	monkeypatch.setenv("XEYO_REWIND_GC_CONFIG", str(blocker / "sub" / "rewind_gc.json"))
	r = c.put("/v1/settings/rewind-gc", json={"keep_recent": 3})
	assert r.status_code == 500, _body(r)
	assert "rewind_gc_write_failed" in _ascii_only(r.text), _body(r)


# --------------------------------------------------------------------------- #
# 7. POST /v1/plan/{turn_id}/approve —— turn_id 是 store 句柄
# --------------------------------------------------------------------------- #


def test_plan_approve_id_edges(sandbox: dict[str, Any]) -> None:
	c = sandbox["client"]
	for raw in ("%20abc", "%2e%2e", "t" * 3000):
		r = c.post(f"/v1/plan/{raw}/approve", json={"approved": True})
		assert r.status_code == 422, f"{raw} -> {_body(r)}"
	from engine.plan import default_plan_engine

	default_plan_engine().create(session_id="s", turn_id="plangedge1", plan="p")
	r = c.post("/v1/plan/plangedge1/approve", json={"approved": True, "actor": "desktop"})
	assert r.status_code == 200, _body(r)
	assert r.json()["ok"] is True
	r = c.post("/v1/plan/no-such-turn-xyz/approve", json={"approved": True})
	assert r.status_code == 200, _body(r)
	assert r.json()["ok"] is False


# --------------------------------------------------------------------------- #
# 8. 固定路径 / 固定 argv 的三条：确认没有调用方参数入口（不执行子进程）
# --------------------------------------------------------------------------- #


def test_fixed_path_routes_take_no_caller_params(sandbox: dict[str, Any]) -> None:
	from server.routers import control

	for name in ("memory_report", "memory_report_view", "run_memory_snapshot"):
		fn = getattr(control, name)
		assert set(inspect.signature(fn).parameters) == {"request"}, name


def test_report_view_serves_only_the_generated_file(sandbox: dict[str, Any]) -> None:
	c = sandbox["client"]
	from scripts.memory_stack_eval import A3_HTML

	plain = c.get("/v1/settings/memory/report/view")
	with_foreign = c.get(
		"/v1/settings/memory/report/view", params={"path": str(sandbox["srv"])}
	)
	assert with_foreign.status_code == plain.status_code, _body(with_foreign)
	assert with_foreign.content == plain.content
	target = Path(A3_HTML)
	if target.is_file():
		assert plain.status_code == 200, _body(plain)
		assert plain.content == target.read_bytes()
	else:
		assert plain.status_code == 404, _body(plain)
	meta = c.get("/v1/settings/memory/report")
	assert meta.status_code == 200, _body(meta)
	assert "exists" in meta.json()


def test_interrupt_id_bound_and_idempotent_contract(sandbox: dict[str, Any]) -> None:
	c = sandbox["client"]
	# 既有用例钉死的幂等 stop 契约：未知 / 带空白的 id 都是 200 ok:true——
	# SessionPool / TurnRunner 全是精确键的进程内字典（无 strip、无文件名派生）。
	for sid in ("never-seen-sess", "victim ", "victim."):
		r = c.post("/v1/interrupt", json={"session_id": sid})
		assert r.status_code == 200, _body(r)
		assert r.json()["ok"] is True
	r = c.post("/v1/interrupt", json={"session_id": "z" * 300_000})
	assert r.status_code == 422, _body(r)
