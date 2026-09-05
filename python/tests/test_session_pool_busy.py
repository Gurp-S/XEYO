"""#3：busy lease + 过期回收不得让 session 永久卡在 409。"""

from __future__ import annotations

import time

from server.session_pool import SessionPool


def test_try_begin_end_roundtrip():
	pool = SessionPool(cwd=".", busy_stale_sec=600)
	lease = pool.try_begin("s1")
	assert lease is not None
	assert pool.try_begin("s1") is None
	pool.end("s1", lease)
	assert pool.try_begin("s1") is not None


def test_end_ignores_mismatched_lease():
	pool = SessionPool(cwd=".", busy_stale_sec=600)
	lease_a = pool.try_begin("s1")
	assert lease_a is not None
	# 模拟过期回收 + 新持有者，不经过 reclaim 路径：
	pool.end("s1", lease_a)
	lease_b = pool.try_begin("s1")
	assert lease_b is not None
	# 旧 stream 的 finally 不得清除新 lease。
	pool.end("s1", lease_a)
	assert pool.is_busy("s1")
	pool.end("s1", lease_b)
	assert not pool.is_busy("s1")


def test_stale_busy_reclaimed_on_try_begin():
	pool = SessionPool(cwd=".", busy_stale_sec=0.05)
	lease = pool.try_begin("s1")
	assert lease is not None
	assert pool.try_begin("s1") is None
	time.sleep(0.08)
	# 过期 lease 被回收 → 新 begin 成功。
	lease2 = pool.try_begin("s1")
	assert lease2 is not None
	assert lease2 != lease
	# 旧 finally 对较新 lease 为 no-op。
	pool.end("s1", lease)
	assert pool.is_busy("s1")
	pool.end("s1", lease2)


def test_end_without_lease_still_clears():
	pool = SessionPool(cwd=".", busy_stale_sec=600)
	assert pool.try_begin("s1") is not None
	pool.end("s1")  # interrupt / 管理员解锁路径
	assert not pool.is_busy("s1")


def test_interrupt_before_engine_queues():
	"""#4：busy 但 engine 尚未创建时 interrupt。"""
	pool = SessionPool(cwd=".", busy_stale_sec=600)
	lease = pool.try_begin("s1")
	assert lease is not None
	assert pool.interrupt("s1") is True  # busy，engine 尚未存在
	assert pool.take_pending_interrupt("s1") is True
	assert pool.take_pending_interrupt("s1") is False
	pool.end("s1", lease)


def test_interrupt_aborts_attached_batch():
	pool = SessionPool(cwd=".", busy_stale_sec=600)
	lease = pool.try_begin("s-batch")
	abort = pool.attach_batch_abort("s-batch")
	assert pool.batch_is_active("s-batch")
	assert abort.aborted is False
	pool.interrupt("s-batch")
	assert abort.aborted is True
	# 中止后不再算 active，但 map 仍在直到 detach
	assert pool.batch_is_active("s-batch") is False
	pool.detach_batch_abort("s-batch", abort)
	pool.end("s-batch", lease)


def test_detach_batch_abort_ignores_stale_controller():
	pool = SessionPool(cwd=".", busy_stale_sec=600)
	lease = pool.try_begin("s-ov")
	a1 = pool.attach_batch_abort("s-ov")
	# 模拟旧流 finally：不应摘掉若已被替换——但 attach 会复用未 abort 的 a1
	a2 = pool.attach_batch_abort("s-ov")
	assert a2 is a1
	a1.abort()
	a3 = pool.attach_batch_abort("s-ov")
	assert a3 is not a1
	pool.detach_batch_abort("s-ov", a1)  # stale
	assert pool._batch_aborts.get("s-ov") is a3
	pool.detach_batch_abort("s-ov", a3)
	assert "s-ov" not in pool._batch_aborts
	pool.end("s-ov", lease)


def test_try_begin_blocked_while_batch_abort_present():
	pool = SessionPool(cwd=".", busy_stale_sec=0.05)
	lease = pool.try_begin("s-long")
	abort = pool.attach_batch_abort("s-long")
	pool.end("s-long", lease)  # busy 清了但 batch 仍在
	time.sleep(0.08)
	assert pool.try_begin("s-long") is None
	pool.detach_batch_abort("s-long", abort)
	assert pool.try_begin("s-long") is not None


def test_stale_busy_not_reclaimed_while_batch_active():
	pool = SessionPool(cwd=".", busy_stale_sec=0.05)
	lease = pool.try_begin("s1")
	abort = pool.attach_batch_abort("s1")
	time.sleep(0.08)
	assert pool.try_begin("s1") is None
	pool.detach_batch_abort("s1", abort)
	pool.end("s1", lease)


def test_interrupt_idle_is_idempotent_noop():
	"""Idle 时 interrupt 不得排队 pending（污染下次 submit）。"""
	pool = SessionPool(cwd=".", busy_stale_sec=600)
	assert pool.interrupt("idle-sess") is True
	assert pool.take_pending_interrupt("idle-sess") is False
	# 第二次调用仍正常。
	assert pool.interrupt("idle-sess") is True
	assert pool.take_pending_interrupt("idle-sess") is False


def test_default_busy_stale_sec_is_five_minutes():
	"""活 turn 由 TurnRunner 心跳续租 + chat 入口 runner 判活兜底，
	默认 stale 窗可从 15min 收紧到 5min（权限面板 TTL 180s 仍被覆盖）。"""
	pool = SessionPool(cwd=".", busy_stale_sec=600)
	assert pool._busy_stale_sec == 600.0
	pool_default = SessionPool(cwd=".")
	assert pool_default._busy_stale_sec == 300.0


def test_force_idle_clears_stale_busy():
	pool = SessionPool(cwd=".", busy_stale_sec=600)
	lease = pool.try_begin("s1")
	assert lease is not None
	assert pool.is_busy("s1")
	pool.force_idle("s1")
	assert not pool.is_busy("s1")
	assert pool.try_begin("s1") is not None


def test_drop_clears_busy_and_engine():
	from msgtypes.message import user_message
	from server.session_pool import ModelConfig

	pool = SessionPool(cwd=".", busy_stale_sec=600)
	cfg = ModelConfig(
		provider="deepseek",
		api_key="k",
		base_url="https://example.com/v1",
		model="m",
	)
	pool.get_or_create("s1", cfg, initial_messages=[user_message("hi")])
	assert pool.try_begin("s1") is not None
	assert pool.drop("s1") is True
	assert not pool.is_busy("s1")
	assert pool.try_begin("s1") is not None


def test_get_or_create_does_not_deadlock_on_todo_inject():
	"""回归：_build 在持有 _lock 时不得再抢同一把 Lock（多 Agent 冷启动会死锁整进程）。"""
	import threading

	from msgtypes.message import user_message
	from server.session_pool import ModelConfig

	pool = SessionPool(cwd=".", busy_stale_sec=600)
	cfg = ModelConfig(
		provider="deepseek",
		api_key="k",
		base_url="https://example.com/v1",
		model="m",
	)
	box: dict[str, object] = {}

	def _run() -> None:
		try:
			box["eng"] = pool.get_or_create(
				"s-deadlock", cfg, initial_messages=[user_message("hi")]
			)
		except Exception as exc:  # noqa: BLE001
			box["err"] = exc

	t = threading.Thread(target=_run, name="get-or-create-deadlock-probe")
	t.start()
	t.join(timeout=15.0)
	assert not t.is_alive(), "get_or_create deadlocked holding SessionPool._lock"
	assert "err" not in box
	assert box.get("eng") is not None
