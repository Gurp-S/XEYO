"""会话级资源清理：所有权注册表 + 两处实测漏项（2026-10-13）。

结构性根因：删除会话的清理逻辑是**手写枚举**的（router 里七段 try/except），
于是每新增一个 per-session registry 就漏一处，且漏掉是静默的。实测漏了两处：

- `JobRegistry`：删会话不杀后台 job（transcript / GUI 卡片都没了，后台 Bash 还在跑）；
- `synthetic_round._REQUEST_ENVS`：`api_key` / `model` / `workspace` 陈旧快照残留。

本文件在修复前必须失败（前两组用例是新增能力的 A 臂）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import session_lifecycle  # noqa: E402
from session.persistence import transcript_path  # noqa: E402

SID = "sess_lifecycle"


# ---------------------------------------------------------------------------
# 1. 注册表语义
# ---------------------------------------------------------------------------
class _FakeOwner:
	def __init__(self, name: str, order: int, calls: list[str], boom: bool = False) -> None:
		self.name = name
		self.order = order
		self._calls = calls
		self._boom = boom

	def drop_session(self, session_id: str) -> None:
		self._calls.append(f"{self.name}:{session_id}")
		if self._boom:
			raise RuntimeError("boom")


@pytest.fixture()
def clean_registry(monkeypatch: pytest.MonkeyPatch):
	"""每个用例独占注册表（保留内置函数型 owner 由 drop_all 自行补登）。"""
	session_lifecycle.reset_for_tests()
	yield session_lifecycle
	session_lifecycle.reset_for_tests()


def test_drop_all_calls_every_registered_owner(clean_registry: Any) -> None:
	calls: list[str] = []
	clean_registry.register(_FakeOwner("a", 10, calls))
	clean_registry.register(_FakeOwner("b", 20, calls))
	out = clean_registry.drop_all(SID)
	assert calls == [f"a:{SID}", f"b:{SID}"]
	assert all(err is None for _name, err in out)


def test_drop_all_continues_after_owner_failure(clean_registry: Any) -> None:
	"""单个 owner 失败**不得**中断后续清理（旧实现 goal/inbox 抛错会整段中断删除）。"""
	calls: list[str] = []
	clean_registry.register(_FakeOwner("a", 10, calls))
	clean_registry.register(_FakeOwner("boom", 20, calls, boom=True))
	clean_registry.register(_FakeOwner("c", 30, calls))
	out = clean_registry.drop_all(SID)
	assert f"c:{SID}" in calls, "失败 owner 之后的清理被跳过了"
	errors = {name: err for name, err in out if err}
	assert set(errors) == {"boom"}


def test_cleanup_order_puts_jobs_before_transcript() -> None:
	"""顺序是正确性要求：job 的 settle 会写 transcript，必须排在 transcript 之前。"""
	assert session_lifecycle.ORDER_JOBS < session_lifecycle.ORDER_SYNTHETIC_ENV
	assert session_lifecycle.ORDER_SYNTHETIC_ENV < session_lifecycle.ORDER_GOAL
	assert session_lifecycle.ORDER_GOAL < session_lifecycle.ORDER_POOL
	assert session_lifecycle.ORDER_POOL < session_lifecycle.ORDER_TRANSCRIPT


def test_builtin_hooks_cover_the_two_known_leaks(clean_registry: Any) -> None:
	"""元测试：两处实测漏项必须在注册表里（否则同类漏项会再次静默发生）。"""
	names = {name for name, _order in clean_registry.registered()}
	assert "synthetic_request_env" in names
	assert "runtime_mode" in names
	assert "runtime_preset" in names


def test_singleton_getters_self_register(clean_registry: Any) -> None:
	"""三个持有者必须在**自己的单例 getter** 里登记（不是靠 router 记得调）。"""
	from server.goal_round_driver import GoalRoundDriver
	from server.inbox_registry import InboxRegistry
	from server.job_registry import JobRegistry

	for cls, expected in (
		(JobRegistry, "job_registry"),
		(GoalRoundDriver, "goal_round_driver"),
		(InboxRegistry, "inbox_registry"),
	):
		assert getattr(cls, "name", None) == expected
		assert isinstance(getattr(cls, "order", None), int)
		assert callable(getattr(cls, "drop_session", None))


# ---------------------------------------------------------------------------
# 2. 端到端：删会话必须同时清 job 与 synthetic env
# ---------------------------------------------------------------------------
def _seed_transcript(sessions_dir: Path, sid: str) -> Path:
	tp = transcript_path(sid, sessions_dir=sessions_dir)
	tp.parent.mkdir(parents=True, exist_ok=True)
	tp.write_text(
		'{"role":"user","content":"hello","ts":1757000000.0}\n', encoding="utf-8"
	)
	return tp


@pytest.fixture()
def archived_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
	"""建一个已归档会话（删除门槛要求先归档），并隔离 pool / 会话目录。"""
	sessions_dir = tmp_path / "sessions"
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(sessions_dir))
	from server.routers import sessions as sessions_module
	from server.session_pool import SessionPool

	monkeypatch.setattr(
		sessions_module, "_pool", SessionPool(cwd=str(sessions_dir), busy_stale_sec=600)
	)
	session_lifecycle.reset_for_tests()
	_seed_transcript(sessions_dir, SID)
	assert sessions_module.archive_session(SID)["ok"] is True
	yield SID
	session_lifecycle.reset_for_tests()


def test_delete_session_kills_owned_background_jobs(archived_session: str) -> None:
	"""删会话 ⇒ 该会话的后台 job 必须被杀且清出注册表。"""
	from server.job_registry import STATUS_RUNNING, get_job_registry
	from server.routers import sessions as sessions_module

	reg = get_job_registry()
	jid, err = reg.start(
		kind="bash",
		label="long running",
		owner_session_id=archived_session,
		producer=lambda push: (STATUS_RUNNING, ""),
	)
	assert jid and not err

	out = sessions_module.delete_session(archived_session)
	assert out["ok"] is True
	assert reg.snapshot_list(archived_session) == [], "删会话未清理后台 job"
	ctl = reg._aborts.get(jid)
	assert ctl is None or ctl.aborted, "删会话必须中止该 job 的取消节点"


def test_delete_session_clears_synthetic_request_environment(archived_session: str) -> None:
	"""删会话 ⇒ synthetic 请求环境（含 api_key）必须一并清掉。"""
	from server.routers import sessions as sessions_module
	from server.synthetic_round import env_for, note_request_env

	note_request_env(
		archived_session,
		{"model": "fake-model", "api_key": "SECRET_SENTINEL", "workspace": "/tmp/ws"},
	)
	assert env_for(archived_session) is not None

	out = sessions_module.delete_session(archived_session)
	assert out["ok"] is True
	assert env_for(archived_session) is None, "已删会话仍留着 api_key 快照"


def test_leaks_come_back_when_registry_is_bypassed(
	archived_session: str, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""**反证（防空转）**：把 ``drop_all`` 变成 no-op，两处泄漏必须重现。

	这条证明上面两条端到端用例真的在考"注册表这条通道"，而不是碰巧因为别的原因
	通过。它同时也是"单一清理通道"这一结构性质的锁定：若哪天有人在 router 里
	又加回手写清理，这条仍绿，但 `drop_all` 一被绕开就会红——说明通道确实唯一。
	"""
	from server.job_registry import STATUS_RUNNING, get_job_registry
	from server.routers import sessions as sessions_module
	from server.synthetic_round import env_for, note_request_env

	monkeypatch.setattr(session_lifecycle, "drop_all", lambda _sid: [])

	reg = get_job_registry()
	jid, err = reg.start(
		kind="bash",
		label="leak probe",
		owner_session_id=archived_session,
		producer=lambda push: (STATUS_RUNNING, ""),
	)
	assert jid and not err
	note_request_env(
		archived_session, {"model": "fake-model", "api_key": "SECRET_SENTINEL"}
	)
	assert env_for(archived_session) is not None

	out = sessions_module.delete_session(archived_session)
	assert out["ok"] is True

	assert reg.snapshot_list(archived_session) != [], "泄漏未重现 ⇒ 上面的用例是空转"
	assert env_for(archived_session) is not None, "泄漏未重现 ⇒ 上面的用例是空转"
