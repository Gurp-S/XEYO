"""T10：grant store（always-allow）+ 权限 preset（readonly/workspace-write/full）。

- 同类操作（tool, 规则指纹, workspace）第二次不再 ASK；可撤销、有 TTL、事件化审计。
- grant 只能 ASK→ALLOW：worker 写作用域 / 远程会话 / permission_mode=always 跳过；
  DENY 永不触碰（impl 先返回）。
- preset 会话创建时 pin：切换不溯及；readonly 收紧只读门禁，full 放宽写确认。
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from engine.workspace_context import WorkspaceContext, set_workspace_context
from permissions.policy import (
	evaluate_policy,
	permission_mode,
	readonly_gate,
	session_permission_profile,
	set_permission_mode,
)
from permissions.presets import normalize_preset
from permissions.store import (
	PermissionGrantStore,
	default_permission_store,
	grant_fingerprint,
)


@pytest.fixture(autouse=True)
def _clean_policy_ctx(monkeypatch):
	monkeypatch.delenv("XEYO_PERMISSION_MODE", raising=False)
	monkeypatch.delenv("XEYO_GRANT_TTL_SEC", raising=False)
	set_permission_mode(None)
	set_workspace_context(None)
	# 每个测试独立的 grant 存储
	import permissions.store as st

	fresh = PermissionGrantStore()
	monkeypatch.setattr(st, "_default_grant_store", fresh)
	yield
	set_permission_mode(None)
	set_workspace_context(None)


# ---------------------------------------------------------------------------
# grant_fingerprint
# ---------------------------------------------------------------------------


def test_grant_fingerprint_bash_prefix():
	assert (
		grant_fingerprint("Bash", {"command": "npm install left-pad"})
		== "npm install"
	)
	assert grant_fingerprint("Bash", {"command": "python"}) == "python"
	assert grant_fingerprint("Bash", {"command": "   "}) == ""
	# 非 Bash：matched_rule 聚合
	assert (
		grant_fingerprint("WebFetch", {}, matched_rule="outbound_ask")
		== "outbound_ask"
	)


# ---------------------------------------------------------------------------
# grant store 基础行为
# ---------------------------------------------------------------------------


def test_grant_store_add_match_revoke(tmp_path):
	store = PermissionGrantStore()
	g = store.add(
		tool_name="Bash",
		fingerprint="npm install",
		scope=str(tmp_path),
		actor="desktop",
	)
	assert g is not None and g.grant_id
	assert store.match(
		tool_name="Bash", fingerprint="npm install", scope=str(tmp_path)
	) is g
	# 列表可见；撤销后不再命中
	assert len(store.list()) == 1
	assert store.revoke(g.grant_id) is True
	assert store.revoke(g.grant_id) is False
	assert store.match(
		tool_name="Bash", fingerprint="npm install", scope=str(tmp_path)
	) is None
	assert store.list() == []


def test_grant_store_ttl_expiry(tmp_path):
	store = PermissionGrantStore(default_ttl=0.05)
	store.add(tool_name="Bash", fingerprint="git fetch", scope=str(tmp_path))
	assert store.match(
		tool_name="Bash", fingerprint="git fetch", scope=str(tmp_path)
	)
	time.sleep(0.12)
	assert (
		store.match(tool_name="Bash", fingerprint="git fetch", scope=str(tmp_path))
		is None
	)


def test_grant_store_scope_binding(tmp_path, tmp_path_factory):
	other = tmp_path_factory.mktemp("other_ws")
	store = PermissionGrantStore()
	store.add(tool_name="Bash", fingerprint="cargo build", scope=str(tmp_path))
	assert (
		store.match(tool_name="Bash", fingerprint="cargo build", scope=str(other))
		is None
	)
	# Windows 路径大小写不敏感
	assert (
		store.match(
			tool_name="Bash",
			fingerprint="cargo build",
			scope=str(tmp_path).upper(),
		)
		is not None
	)


# ---------------------------------------------------------------------------
# policy 集成：ASK → grant → ALLOW
# ---------------------------------------------------------------------------


def _ask_decision(cwd):
	return evaluate_policy("Bash", {"command": "npm install left-pad"}, cwd=str(cwd))


def test_policy_second_ask_auto_allows(tmp_path):
	d1 = _ask_decision(tmp_path)
	assert d1.decision.value == "ask"
	# 用户勾选「不再询问」→ 记 grant
	import permissions.store as st

	st._default_grant_store.add(
		tool_name="Bash",
		fingerprint=grant_fingerprint("Bash", {"command": "npm install left-pad"}),
		scope=str(tmp_path),
	)
	d2 = _ask_decision(tmp_path)
	assert d2.decision.value == "allow"
	assert d2.matched_rule == "grant_store"
	# 不同前缀仍要问
	d3 = evaluate_policy("Bash", {"command": "npm publish"}, cwd=str(tmp_path))
	assert d3.decision.value == "ask"


def test_policy_worker_scope_skips_grant(tmp_path, monkeypatch):
	import permissions.store as st

	st._default_grant_store.add(
		tool_name="Bash",
		fingerprint="npm install",
		scope=str(tmp_path),
	)
	from permissions.write_scope import set_write_scope

	set_write_scope(("sub",))
	try:
		# worker 作用域：grant 不得放行（这里该命令直接 DENY，比 ASK 更严）。
		assert _ask_decision(tmp_path).decision.value != "allow"
	finally:
		set_write_scope(None)


def test_policy_remote_session_skips_grant(tmp_path):
	import permissions.store as st

	st._default_grant_store.add(
		tool_name="Bash", fingerprint="npm install", scope=str(tmp_path)
	)
	set_workspace_context(
		WorkspaceContext(session_id="ilink:wx1", cwd=str(tmp_path))
	)
	assert _ask_decision(tmp_path).decision.value == "ask"


def test_policy_always_mode_skips_grant(tmp_path):
	import permissions.store as st

	st._default_grant_store.add(
		tool_name="Bash", fingerprint="npm install", scope=str(tmp_path)
	)
	set_permission_mode("always")
	assert _ask_decision(tmp_path).decision.value == "ask"


# ---------------------------------------------------------------------------
# resolve 端点：remember=True 记 grant
# ---------------------------------------------------------------------------


def test_resolve_endpoint_remember_records_grant(tmp_path, monkeypatch):
	import permissions.store as st

	pending_store = st.PendingPermissionStore(ttl_seconds=60)
	monkeypatch.setattr(st, "_default_store", pending_store)
	set_workspace_context(
		WorkspaceContext(session_id="sess-grant", cwd=str(tmp_path))
	)
	item = pending_store.create(
		session_id="sess-grant",
		turn_id="t1",
		tool_name="Bash",
		tool_input={"command": "npm install left-pad"},
		reason="needs_confirmation",
		prompt="Allow Bash?",
		matched_rule="bash_policy_ask",
	)
	from server.app import app

	c = TestClient(app)
	r = c.post(
		"/v1/permission/resolve",
		json={"request_id": item.request_id, "approved": True, "remember": True},
	)
	assert r.status_code == 200
	body = r.json()
	assert body["ok"] is True
	assert body["grant_id"]
	grants = st._default_grant_store.list()
	assert len(grants) == 1
	assert grants[0].fingerprint == "npm install"
	assert grants[0].tool_name == "Bash"
	# 第二次同类操作直接放行
	d = evaluate_policy("Bash", {"command": "npm install left-pad"}, cwd=str(tmp_path))
	assert d.decision.value == "allow"


# ---------------------------------------------------------------------------
# preset
# ---------------------------------------------------------------------------


def test_normalize_preset():
	assert normalize_preset("readonly") == "readonly"
	assert normalize_preset("workspace_write") == "workspace-write"
	assert normalize_preset("FULL") == "full"
	assert normalize_preset(None) == "workspace-write"
	assert normalize_preset("nonsense") == "workspace-write"


def test_preset_readonly_gate(tmp_path):
	set_workspace_context(
		WorkspaceContext(
			session_id="s", cwd=str(tmp_path), permission_profile="readonly"
		)
	)
	assert session_permission_profile() == "readonly"
	assert readonly_gate("Read") is None
	assert readonly_gate("Write") == "readonly_mode_deny"


def test_preset_full_relaxes_write_confirm(tmp_path):
	set_workspace_context(
		WorkspaceContext(
			session_id="s", cwd=str(tmp_path), permission_profile="full"
		)
	)
	assert permission_mode() == "never"
	# 请求级显式 mode 优先于 preset
	set_permission_mode("always")
	assert permission_mode() == "always"


def test_pool_pins_preset(tmp_path, monkeypatch):
	from server.session_pool import ModelConfig, SessionPool

	class _StubEngine:
		def __init__(self) -> None:
			self.profile = ""
			self.mutable_messages = []

		def hydrate_if_empty(self, messages):  # noqa: ANN001
			return False

		def set_permission_profile(self, profile: str) -> None:
			self.profile = profile

	pool = SessionPool(cwd=str(tmp_path))
	cfg = ModelConfig(provider="x", api_key="k", base_url="http://x", model="m")
	monkeypatch.setattr(pool, "_build", lambda c, **kw: _StubEngine())
	eng = pool.get_or_create(
		"sess-pin", cfg, cwd=str(tmp_path), permission_preset="readonly"
	)
	assert eng.profile == "readonly"
	# 切换 preset 不溯及既有会话
	eng2 = pool.get_or_create(
		"sess-pin", cfg, cwd=str(tmp_path), permission_preset="full"
	)
	assert eng2 is eng
	assert eng2.profile == "readonly"
	# 新会话拿新 preset
	eng3 = pool.get_or_create(
		"sess-new", cfg, cwd=str(tmp_path), permission_preset="full"
	)
	assert eng3.profile == "full"
	# 缺省 = workspace-write
	eng4 = pool.get_or_create("sess-d", cfg, cwd=str(tmp_path))
	assert eng4.profile == "workspace-write"
