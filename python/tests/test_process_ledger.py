"""test_process_ledger — P3 台账旁路单测(纯逻辑,假 probe/cleanup,零真实进程)。

覆盖:登记幂等、list 过滤、reap(除名死项/清理活项/owner+kind 过滤/dry-run)、
sweep(active 保护/宽限期/孤儿清理)、cleanup 绝不触碰台账外对象、快照。
"""
from __future__ import annotations

import os
import time

import pytest

from engine.process_ledger import (
	Entry,
	Kind,
	ProcessLedger,
	ReapReport,
	leftovers,
	register_process,
	unregister_process,
)


class FakeBackend:
	"""可控存活表 + cleanup 调用记录。"""

	def __init__(self) -> None:
		self.alive: dict[str, bool] = {}
		self.cleaned: list[tuple[Kind, str]] = []

	def probe(self, e: Entry) -> bool:
		return self.alive.get(e.key, True)

	def cleanup(self, e: Entry) -> bool:
		self.cleaned.append((e.kind, e.key))
		self.alive[e.key] = False
		return True


def test_register_idempotent_and_list_filters() -> None:
	b = FakeBackend()
	ledger = ProcessLedger(probe=b.probe, cleanup=b.cleanup)
	assert ledger.register(Kind.PROC, "p1", "s1", pid=1) is True
	# 同键重复登记:不新增,更新为最新
	assert ledger.register(Kind.PROC, "p1", "s1", pid=1, note="v2") is False
	assert ledger.count() == 1
	ledger.register(Kind.PORT, "8080", "s1", pid=2)
	ledger.register(Kind.LOCK, "/tmp/x.lock", "s2")
	assert ledger.register(Kind.LOCK, "/tmp/x.lock", "s2") is False
	assert {e.key for e in ledger.list(owner="s1")} == {"p1", "8080"}
	assert {e.key for e in ledger.list(kind=Kind.LOCK)} == {"/tmp/x.lock"}
	assert ledger.unregister(Kind.LOCK, "/tmp/x.lock") is True
	assert ledger.unregister(Kind.LOCK, "/tmp/x.lock") is False
	assert ledger.count() == 2


def test_reap_purges_dead_without_cleanup() -> None:
	b = FakeBackend()
	ledger = ProcessLedger(probe=b.probe, cleanup=b.cleanup)
	b.alive = {"p1": False, "p2": True}
	ledger.register(Kind.PROC, "p1", "s1", pid=1)
	ledger.register(Kind.PROC, "p2", "s1", pid=2)
	r = ledger.reap(owner="s1")
	assert isinstance(r, ReapReport)
	assert r.dead_purged == 1  # p1 已死,静默除名
	assert r.cleaned == 1  # p2 被杀
	assert b.cleaned == [(Kind.PROC, "p2")]
	assert ledger.count() == 0


def test_reap_owner_and_kind_filter() -> None:
	b = FakeBackend()
	ledger = ProcessLedger(probe=b.probe, cleanup=b.cleanup)
	b.alive = {"a": True, "b": True, "c": True}
	ledger.register(Kind.PROC, "a", "s1", pid=1)
	ledger.register(Kind.PROC, "b", "s2", pid=2)
	ledger.register(Kind.LOCK, "c", "s1")
	# 只收 s1 的 proc → 只动 a
	r = ledger.reap(owner="s1", kind=Kind.PROC)
	assert r.cleaned == 1
	assert [(k, key) for k, key in b.cleaned] == [(Kind.PROC, "a")]
	assert {e.key for e in ledger.list()} == {"b", "c"}


def test_reap_dry_run_never_cleans() -> None:
	b = FakeBackend()
	ledger = ProcessLedger(probe=b.probe, cleanup=b.cleanup)
	b.alive = {"p1": True}
	ledger.register(Kind.PROC, "p1", "s1", pid=1)
	r = ledger.reap(owner="s1", dry_run=True)
	assert r.dry_run is True
	assert r.considered == 1 and r.cleaned == 0 and r.clean_failed == 0
	assert b.cleaned == []
	assert ledger.count() == 1  # 未除名


def test_cleanup_failure_keeps_entry_for_next_sweep() -> None:
	class Flaky(FakeBackend):
		def cleanup(self, e: Entry) -> bool:
			self.cleaned.append((e.kind, e.key))
			return False  # 失败:保留

	b = Flaky()
	ledger = ProcessLedger(probe=b.probe, cleanup=b.cleanup)
	ledger.register(Kind.PROC, "p1", "s1", pid=1)
	r = ledger.reap(owner="s1")
	assert r.cleaned == 0 and r.clean_failed == 1
	assert ledger.count() == 1  # 保留待重试
	# 失败后进程其实已死 → 下次 reap 除名
	b.alive["p1"] = False
	r2 = ledger.reap(owner="s1")
	assert r2.dead_purged == 1
	assert ledger.count() == 0


def test_sweep_active_owner_kept_young_inactive_kept() -> None:
	b = FakeBackend()
	ledger = ProcessLedger(probe=b.probe, cleanup=b.cleanup)
	b.alive = {"a": True, "b": True, "c": True, "d": False}
	now = time.monotonic()
	ledger.register(Kind.PROC, "a", "s_active", pid=1)  # active → 保留
	ledger.register(Kind.PROC, "b", "s_gone", pid=2)  # 新孤儿 → 宽限内保留
	ledger.register(Kind.PROC, "c", "s_gone", pid=3)  # 老孤儿 → 清理
	ledger.register(Kind.PROC, "d", "s_active", pid=4)  # active 但已死 → 除名
	entries = ledger.list()
	for e in entries:
		if e.key == "c":
			# 人为把它变成超过宽限期的老孤儿
			e.created = now - 120.0
	r = ledger.sweep({"s_active"}, grace_s=60.0, now=now)
	assert r.dead_purged == 1  # d
	assert r.cleaned == 1  # c
	assert [(k, key) for k, key in b.cleaned] == [(Kind.PROC, "c")]
	assert {e.key for e in ledger.list()} == {"a", "b"}


def test_cleanup_never_called_for_unregistered() -> None:
	b = FakeBackend()
	ledger = ProcessLedger(probe=b.probe, cleanup=b.cleanup)
	b.alive = {"ghost": True}
	# 台账外对象:reap/sweep 都不该产生任何 cleanup
	ledger.reap(owner="s1")
	ledger.sweep({"s1"}, grace_s=0.0)
	assert b.cleaned == []
	assert ledger.count() == 0


def test_reap_idempotent_after_success() -> None:
	b = FakeBackend()
	ledger = ProcessLedger(probe=b.probe, cleanup=b.cleanup)
	ledger.register(Kind.PROC, "p1", "s1", pid=1)
	ledger.reap(owner="s1")
	# 第二次 reap 无事可做
	r = ledger.reap(owner="s1")
	assert r.considered == 0 and r.cleaned == 0
	assert len(b.cleaned) == 1


def test_snapshot_fields() -> None:
	b = FakeBackend()
	ledger = ProcessLedger(probe=b.probe, cleanup=b.cleanup)
	ledger.register(Kind.PROC, "p1", "s1", pid=42, cmdline="sleep 100", note="x")
	snap = ledger.snapshot()
	assert len(snap) == 1
	row = snap[0]
	assert row["key"] == "p1" and row["pid"] == 42
	assert row["cmdline"] == "sleep 100" and row["note"] == "x"
	assert row["age_s"] >= 0 and row["kind"] == "proc"


# ---------------------------------------------------------------------------
# 旁路便捷入口:env 门控 + 显式 owner
# ---------------------------------------------------------------------------


def test_helper_gated_by_env(monkeypatch) -> None:
	monkeypatch.delenv("XEYO_PROC_LEDGER", raising=False)
	from engine.process_ledger import get_ledger

	base = get_ledger().count()
	# 关:登记/除名全 no-op
	assert register_process(12345, cmdline="x", owner="s1") is False
	assert get_ledger().count() == base
	# 开:登记走显式 owner
	monkeypatch.setenv("XEYO_PROC_LEDGER", "1")
	assert register_process(12345, cmdline="x", owner="s1") is True
	assert any(e.key == "12345" and e.owner == "s1" for e in get_ledger().list())
	assert unregister_process(12345) is True
	assert get_ledger().count() == base


def test_leftovers_uses_live_probe(monkeypatch) -> None:
	monkeypatch.setenv("XEYO_PROC_LEDGER", "1")
	from engine.process_ledger import get_ledger

	base = get_ledger().count()
	# 当前进程必然存活 → leftovers 能看见,除名后消失
	assert register_process(os.getpid(), cmdline="self", owner="self_test") is True
	try:
		hit = [e for e in leftovers(owner="self_test") if e.key == str(os.getpid())]
		assert len(hit) == 1
	finally:
		unregister_process(os.getpid())
	assert get_ledger().count() == base
