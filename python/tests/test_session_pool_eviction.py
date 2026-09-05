"""P2-10: SessionPool 引擎 LRU 逐出（防多会话内存无界增长）。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from msgtypes.message import user_message
from server.session_pool import ModelConfig, SessionPool


def _cfg(model: str) -> ModelConfig:
	return ModelConfig(
		provider="deepseek",
		api_key="k",
		base_url="http://127.0.0.1:1",
		model=model,
	)


def test_evicts_lru_not_fifo(tmp_path):
	"""Windows monotonic 分辨率 ~15.6ms，sleep 不可靠；直接注入 LRU 时钟。

	s2 比 s1 更早使用但创建更晚 → LRU 应逐出 s2（FIFO 会错误地逐出 s1）。
	"""
	pool = SessionPool(str(tmp_path), max_engines=2)
	pool.get_or_create("keep", _cfg("m1"))
	pool.get_or_create("old", _cfg("m2"))
	# 注入确定的 LRU 时钟：old 最久未用、keep 刚用过
	pool._last_use["keep"] = 900.0
	pool._last_use["old"] = 100.0
	pool.get_or_create("new", _cfg("m3"))

	assert "old" not in pool._engines, "最久未用的会话应被逐出"
	assert {"keep", "new"} <= set(pool._engines)
	assert len(pool._engines) <= 2


def test_busy_session_never_evicted(tmp_path):
	pool = SessionPool(str(tmp_path), max_engines=1)
	pool.get_or_create("busy1", _cfg("m1"))
	assert pool.try_begin("busy1") is not None
	time.sleep(0.005)
	pool.get_or_create("other", _cfg("m2"))
	# busy 会话即使最旧也不逐出；被逐出的是刚建的 other？不——other 是唯一可逐出的，
	# 但 max_engines=1 且 busy1 占位 → other 建立后超限，只能逐出 other 自己之外的非 busy。
	# 引擎数为 2 > 1，busy1 受保护，因此 other 被逐出。
	assert "busy1" in pool._engines
	assert "other" not in pool._engines


def test_evicted_history_restorable_from_stash(tmp_path):
	pool = SessionPool(str(tmp_path), max_engines=1)
	history = [user_message("记住我")]
	e1 = pool.get_or_create("sA", _cfg("m1"), initial_messages=history)
	assert any(getattr(m, "content", "") == "记住我" for m in e1.mutable_messages)
	time.sleep(0.005)
	pool.get_or_create("sB", _cfg("m2"))  # 逐出 sA → 历史进 stash
	assert "sA" not in pool._engines

	# 重新访问 sA：从 stash 恢复历史
	e2 = pool.get_or_create("sA", _cfg("m1"))
	assert any(getattr(m, "content", "") == "记住我" for m in e2.mutable_messages)


def test_stash_bounded(tmp_path):
	pool = SessionPool(str(tmp_path), max_engines=4)
	for i in range(12):
		msg = user_message(f"hi{i}")
		pool.get_or_create(f"s{i}", _cfg(f"m{i % 3}"), initial_messages=[msg])
	assert len(pool._history_stash) <= 4 * 2