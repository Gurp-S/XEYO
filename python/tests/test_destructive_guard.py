"""#14 Phase A 破坏性命令 before-snapshot guard 的离线测试。

验收标准（用户裁决）：rm 掉的文件能通过 rewind 体系恢复出**字节级一致**的内容。
全链路 fail-open 纪律逐条锁死：env 关、无 ctx、目标越界、超上限都只降级为
「不保护」，绝不抛错、绝不阻断。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rewind.context import RewindExecutionContext, bind_context  # noqa: E402
from rewind.journal import OperationJournal  # noqa: E402
from rewind.snapshot import SnapshotStore  # noqa: E402
from tools.bash_tool.destructive_guard import (  # noqa: E402
	plan_destructive_snapshot,
	settle_destructive_plan,
)


def _make_ctx(tmp_path: Path, session_id: str = "s-guard") -> RewindExecutionContext:
	journal = OperationJournal(
		session_id, sessions_dir=tmp_path / "sessions", enabled=True
	)
	snapshots = SnapshotStore(
		session_id, root=tmp_path / "snapshots", enabled=True
	)
	return RewindExecutionContext(
		session_id=session_id,
		turn_id="turn-1",
		revision_id=None,
		journal=journal,
		snapshots=snapshots,
	)


def _touch(path: Path, data: bytes) -> Path:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_bytes(data)
	return path


# ---------------------------------------------------------------- 核心验收


def test_rm_file_snapshot_and_restore(tmp_path):
	"""rm 掉的文件经 rewind 快照恢复出字节级一致内容。"""
	cwd = tmp_path / "ws"
	target = _touch(cwd / "report.txt", b"hello-guard-\xe4\xbd\xa0\xe5\xa5\xbd")
	ctx = _make_ctx(tmp_path)

	plan = plan_destructive_snapshot("rm report.txt", str(cwd), ctx)
	assert plan is not None
	assert len(plan.entries) == 1
	entry = plan.entries[0]
	assert os.path.realpath(str(target)) == entry.path

	op = ctx.journal.get_operation(plan.operation_ids[0])
	assert op is not None
	assert op.operation_type == "bash_destructive"
	assert op.inverse_kind == "restore_snapshot"
	assert op.status == "started"
	assert op.before_hash == entry.content_hash
	assert op.after_hash is None

	# 模拟破坏 → 快照恢复 → 字节级一致
	target.unlink()
	assert not target.exists()
	restored = ctx.snapshots.get_bytes(op.before_hash)
	assert restored == b"hello-guard-\xe4\xbd\xa0\xe5\xa5\xbd"
	target.write_bytes(restored)
	assert target.read_bytes() == b"hello-guard-\xe4\xbd\xa0\xe5\xa5\xbd"


def test_dir_recursive_walk(tmp_path):
	"""rm -rf 目录：树内全部文件逐个快照，均可恢复。"""
	cwd = tmp_path / "ws"
	payloads = {
		cwd / "sub" / "a.txt": b"AAA",
		cwd / "sub" / "nested" / "b.bin": bytes(range(256)),
		cwd / "sub" / "nested" / "deeper" / "c.txt": "中文内容".encode("utf-8"),
	}
	for path, data in payloads.items():
		_touch(path, data)
	ctx = _make_ctx(tmp_path)

	plan = plan_destructive_snapshot("rm -rf sub", str(cwd), ctx)
	assert plan is not None
	assert len(plan.entries) == 3
	restored: dict[str, bytes] = {
		e.path: ctx.snapshots.get_bytes(e.content_hash) for e in plan.entries
	}
	for path, data in payloads.items():
		assert restored[os.path.realpath(str(path))] == data


# ---------------------------------------------------------------- 解析面


def test_flags_and_families(tmp_path):
	"""POSIX 与 Windows 家族旗标不吞目标；mv 双端文件都受保护。"""
	cwd = tmp_path / "ws"
	a = _touch(cwd / "a.txt", b"A")
	b = _touch(cwd / "b.txt", b"B")
	c = _touch(cwd / "c.txt", b"C")
	d = _touch(cwd / "d.txt", b"D")
	e = _touch(cwd / "e.txt", b"E")
	ctx = _make_ctx(tmp_path)

	plan = plan_destructive_snapshot("rm -rf a.txt", str(cwd), ctx)
	assert plan is not None and [x.path for x in plan.entries] == [
		os.path.realpath(str(a))
	]

	plan = plan_destructive_snapshot("del /q /f b.txt", str(cwd), ctx)
	assert plan is not None and [x.path for x in plan.entries] == [
		os.path.realpath(str(b))
	]

	plan = plan_destructive_snapshot("Remove-Item -Force c.txt", str(cwd), ctx)
	assert plan is not None and [x.path for x in plan.entries] == [
		os.path.realpath(str(c))
	]

	plan = plan_destructive_snapshot("mv d.txt e.txt", str(cwd), ctx)
	assert plan is not None
	assert {x.path for x in plan.entries} == {
		os.path.realpath(str(d)),
		os.path.realpath(str(e)),
	}


def test_glob_targets(tmp_path):
	"""rm *.log：glob 展开命中现存文件；无命中 → 不保护（None）。"""
	cwd = tmp_path / "ws"
	one = _touch(cwd / "run1.log", b"1" * 10)
	two = _touch(cwd / "run2.log", b"2" * 10)
	_touch(cwd / "keep.txt", b"K")
	ctx = _make_ctx(tmp_path)

	plan = plan_destructive_snapshot("rm *.log", str(cwd), ctx)
	assert plan is not None
	assert {x.path for x in plan.entries} == {
		os.path.realpath(str(one)),
		os.path.realpath(str(two)),
	}

	plan = plan_destructive_snapshot("rm *.nope", str(cwd), ctx)
	assert plan is None


def test_compound_command(tmp_path):
	"""&& ; | 复合段：破坏段逐个识别，非破坏段忽略。"""
	cwd = tmp_path / "ws"
	inner = _touch(cwd / "inner.txt", b"I")
	outer = _touch(cwd / "outer.txt", b"O")
	zzz = _touch(cwd / "zzz.txt", b"Z")
	ctx = _make_ctx(tmp_path)

	cmd = "cd sub && rm inner.txt; echo hi | rm outer.txt && rm zzz.txt"
	plan = plan_destructive_snapshot(cmd, str(cwd), ctx)
	assert plan is not None
	assert {x.path for x in plan.entries} == {
		os.path.realpath(str(inner)),
		os.path.realpath(str(outer)),
		os.path.realpath(str(zzz)),
	}


def test_outside_cwd_skipped(tmp_path):
	"""越界目标（../、绝对路径）不快照；越界+界内混合时只保护界内。"""
	cwd = tmp_path / "ws"
	inside = _touch(cwd / "in.txt", b"I")
	outside = _touch(tmp_path / "outside.txt", b"X")
	ctx = _make_ctx(tmp_path)

	assert plan_destructive_snapshot("rm ../outside.txt", str(cwd), ctx) is None
	assert plan_destructive_snapshot(
		f"rm \"{outside}\"", str(cwd), ctx
	) is None

	plan = plan_destructive_snapshot("rm ../outside.txt in.txt", str(cwd), ctx)
	assert plan is not None
	assert [x.path for x in plan.entries] == [os.path.realpath(str(inside))]


# ---------------------------------------------------------------- 上限与开关


def test_caps_max_files(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_DESTRUCTIVE_SNAPSHOT_MAX_FILES", "3")
	cwd = tmp_path / "ws"
	for i in range(5):
		_touch(cwd / f"f{i}.txt", b"x")
	ctx = _make_ctx(tmp_path)

	plan = plan_destructive_snapshot("rm f0.txt f1.txt f2.txt f3.txt f4.txt", str(cwd), ctx)
	assert plan is not None
	assert len(plan.entries) == 3
	assert plan.skipped_count == 2


def test_big_file_skipped(tmp_path, monkeypatch):
	"""单文件超字节上限 → 跳过该文件；全部超限 → plan None。"""
	monkeypatch.setenv("XEYO_DESTRUCTIVE_SNAPSHOT_MAX_BYTES", "5")
	cwd = tmp_path / "ws"
	big = _touch(cwd / "big.bin", b"0123456789")
	small = _touch(cwd / "small.bin", b"ok")
	ctx = _make_ctx(tmp_path)

	plan = plan_destructive_snapshot("rm big.bin small.bin", str(cwd), ctx)
	assert plan is not None
	assert [x.path for x in plan.entries] == [os.path.realpath(str(small))]

	assert plan_destructive_snapshot("rm big.bin", str(cwd), ctx) is None
	assert big.exists() and small.exists()  # guard 只观察，从不动手


def test_env_off(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_DESTRUCTIVE_SNAPSHOT", "0")
	cwd = tmp_path / "ws"
	_touch(cwd / "a.txt", b"A")
	ctx = _make_ctx(tmp_path)

	plan = plan_destructive_snapshot("rm a.txt", str(cwd), ctx)
	assert plan is None
	assert ctx.journal.list_operations() == []


# ---------------------------------------------------------------- fail-open


def test_no_context_fail_open(tmp_path):
	"""无 rewind ctx（engine 未绑定/后台线程直调）→ 不保护、不抛错。"""
	cwd = tmp_path / "ws"
	_touch(cwd / "a.txt", b"A")
	assert plan_destructive_snapshot("rm a.txt", str(cwd), None) is None


def test_disabled_ctx_fail_open(tmp_path):
	cwd = tmp_path / "ws"
	_touch(cwd / "a.txt", b"A")
	journal = OperationJournal("s", sessions_dir=tmp_path / "sessions", enabled=False)
	snapshots = SnapshotStore("s", root=tmp_path / "snapshots", enabled=False)
	ctx = RewindExecutionContext(
		session_id="s", turn_id="t", revision_id=None,
		journal=journal, snapshots=snapshots,
	)
	assert plan_destructive_snapshot("rm a.txt", str(cwd), ctx) is None


def test_bound_context_capture(tmp_path):
	"""bash_tool 真实路径依赖 contextvars 捕获 ctx。"""
	cwd = tmp_path / "ws"
	_touch(cwd / "a.txt", b"A")
	ctx = _make_ctx(tmp_path)

	with bind_context(ctx):
		plan = plan_destructive_snapshot("rm a.txt", str(cwd), None)
	assert plan is not None
	assert len(plan.entries) == 1


# ---------------------------------------------------------------- 结算


def test_settle_lifecycle(tmp_path):
	cwd = tmp_path / "ws"
	_touch(cwd / "a.txt", b"A")
	_touch(cwd / "b.txt", b"B")
	ctx = _make_ctx(tmp_path)

	plan = plan_destructive_snapshot("rm a.txt b.txt", str(cwd), ctx)
	assert plan is not None
	settle_destructive_plan(plan, executed=True)
	for op_id in plan.operation_ids:
		assert ctx.journal.get_operation(op_id).status == "completed"

	# 双重结算安全（completed → completed 合法 no-op）
	before = len(ctx.journal.list_operations())
	settle_destructive_plan(plan, executed=True)
	assert len(ctx.journal.list_operations()) == before

	plan2 = plan_destructive_snapshot("rm a.txt b.txt", str(cwd), ctx)
	assert plan2 is not None
	settle_destructive_plan(plan2, executed=False)
	for op_id in plan2.operation_ids:
		assert ctx.journal.get_operation(op_id).status == "cancelled"


def test_settle_none_noop(tmp_path):
	settle_destructive_plan(None, executed=True)  # 不抛错


# ---------------------------------------------------------------- 后台接线


def test_start_background_guard_settles(tmp_path):
	"""日志文件后台路径：worker 结束后 settle executed=True → completed。"""
	from tools.bash_tool.background import start_background

	cwd = tmp_path / "ws"
	_touch(cwd / "a.txt", b"A")
	ctx = _make_ctx(tmp_path)

	plan = plan_destructive_snapshot("rm a.txt", str(cwd), ctx)
	assert plan is not None

	handle = start_background(
		"echo guard-bg-ok",
		cwd=str(cwd),
		timeout_ms=15_000,
		guard_plan=plan,
	)
	text = ""
	deadline = time.time() + 30
	while time.time() < deadline:
		try:
			text = Path(handle.log_path).read_text(encoding="utf-8")
		except OSError:
			text = ""
		if "# status:" in text:
			break
		time.sleep(0.2)
	assert "# status:" in text, "background task did not finish in time"

	deadline = time.time() + 10
	while time.time() < deadline:
		if plan.settled:
			break
		time.sleep(0.1)
	assert plan.settled
	for op_id in plan.operation_ids:
		assert ctx.journal.get_operation(op_id).status == "completed"
