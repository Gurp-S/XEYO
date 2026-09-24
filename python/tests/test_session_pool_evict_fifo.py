"""`_evict_locked` 的 stash FIFO 必须"重新入队即刷新"。

docstring 明写 "stash 同步限幅（FIFO，重新入队即刷新）"。但 Python 的 dict **不会**
因为重新赋值就改变插入顺序 —— ``d[k] = v`` 对一个已存在的键保持原位。于是被反复访问
的会话（最该留下的那份历史）反而占着最老的位置，先被挤掉。

逐出本身有磁盘 transcript 兜底，所以这不是数据丢失，而是"注释承诺的语义与代码
实际做的不一样"——而这正是最难查的那类：读代码的人按注释推理，行为却不按它走。

注意 `_evict_locked` 只在 ``len(_engines) > max_engines`` 时才动手，所以每次逐出
都要陪一个"最新使用"的占位会话，让它自己不被选中。
"""

from __future__ import annotations

from pathlib import Path

from server.session_pool import SessionPool

_KEEPER = "_keeper"
_KEEPER_TS = 1e12


class _StubEngine:
	"""只需要 evict 真正会碰到的两个成员。"""

	def __init__(self, msgs: list[str]) -> None:
		self.mutable_messages = msgs
		self.interrupted = False

	def interrupt(self) -> None:
		self.interrupted = True


def _pool(tmp_path: Path) -> SessionPool:
	return SessionPool(str(tmp_path / "ws"), busy_stale_sec=600.0, max_engines=1)


def _evict_one(pool: SessionPool, sid: str, msgs: list[str]) -> _StubEngine:
	"""插入 ``sid`` 并保证它成为本轮唯一的逐出对象。"""
	stub = _StubEngine(msgs)
	pool._engines[sid] = (None, stub)
	pool._engines[_KEEPER] = (None, _StubEngine(["keeper"]))
	pool._last_use[sid] = 1.0
	pool._last_use[_KEEPER] = _KEEPER_TS
	pool._evict_locked()
	return stub


def test_restashing_a_session_moves_it_to_the_back_of_the_fifo(tmp_path: Path) -> None:
	pool = _pool(tmp_path)

	_evict_one(pool, "a", ["a-v1"])
	assert list(pool._history_stash) == ["a"]

	_evict_one(pool, "b", ["b-v1"])
	assert list(pool._history_stash) == ["a", "b"]

	# 重新访问 a → 重新入队，按 docstring 应刷新到队尾
	_evict_one(pool, "a", ["a-v2"])
	assert pool._history_stash["a"] == ["a-v2"]
	assert list(pool._history_stash) == ["b", "a"], (
		"重新入队没有刷新位置：最活跃的会话排在最老，会被第一个挤掉"
	)

	# c 入 stash 触发限幅（cap = max_engines * 2 = 2）→ 该淘汰最久没被重用的 b
	_evict_one(pool, "c", ["c-v1"])
	assert len(pool._history_stash) == 2
	assert "a" in pool._history_stash, "刚被重新访问过的历史被挤掉了"
	assert "b" not in pool._history_stash, "限幅应淘汰最久未重用的那一份"


def test_evict_never_touches_a_busy_session(tmp_path: Path) -> None:
	"""逐出的前提（busy 绝不逐出）也要钉住——别在改 FIFO 时被弄坏。"""
	pool = _pool(tmp_path)
	assert pool.try_begin("busy_one") is not None
	pool._engines["busy_one"] = (None, _StubEngine(["keep me"]))
	pool._engines["idle_two"] = (None, _StubEngine(["drop me"]))
	pool._last_use["busy_one"] = 0.0
	pool._last_use["idle_two"] = 1.0
	pool._evict_locked()
	assert "busy_one" in pool._engines, "在跑的会话不能被逐出"
	assert "idle_two" not in pool._engines
	assert pool._history_stash.get("idle_two") == ["drop me"]


def test_evict_interrupts_the_engine_it_drops(tmp_path: Path) -> None:
	pool = _pool(tmp_path)
	stub = _evict_one(pool, "gone", ["x"])
	assert stub.interrupted is True
