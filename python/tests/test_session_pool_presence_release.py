"""busy 租约被回收时，跨会话存在状态（presence）必须一起清掉。

`SessionPool.end()` 会调 `_presence_busy(busy=False)`，而这条标记的**清除动作顺带
把 `git_op` / `current_tool` 也清空**（`engine/session_presence.py` 里 `if not busy:`
那两行）。但另外两条释放路径只动了池子：

- `_reclaim_stale()`：处理"stream 的 finally 从未执行"（客户端被杀 / 管道断开）
  的正规恢复路径 —— 它只 `del self._busy[sid]`。
- `force_idle()`：rewind / stop 恢复用 —— 它只 `self._busy.pop(...)`。

presence 的 `busy` **没有 TTL**（只有 `owned_files` 有 `FILE_OWNERSHIP_TTL_SEC`），
所以一次漏清就是永久性的：`permissions/policy.py` 的
`peer_git_conflict(cwd, sid, command)` 会拿某个"还在跑"的对端去拦当前会话的 git
命令，而那个对端其实早就死了 —— 用户看到的是一条没有来源的冲突拦截。
"""

from __future__ import annotations

import time
from pathlib import Path

from engine.session_presence import default_session_presence
from server.session_pool import SessionPool


def _presence(ws: str, sid: str):
	return default_session_presence().self_entry(ws, sid)


def test_end_clears_presence_but_stale_reclaim_does_not(tmp_path: Path) -> None:
	ws = str(tmp_path / "ws")
	pool = SessionPool(ws, busy_stale_sec=0.01)
	reg = default_session_presence()

	lease = pool.try_begin("s1")
	assert lease is not None
	reg.note_git(ws, "s1", "rebase")
	ent = _presence(ws, "s1")
	assert ent is not None and ent.busy is True and ent.git_op == "rebase"

	time.sleep(0.05)
	assert pool.is_busy("s1") is False, "过期租约应被回收"

	ent = _presence(ws, "s1")
	assert ent is not None
	assert ent.busy is False, "池子已回收租约，presence 却仍报 busy"
	assert ent.git_op == "", "busy 清掉时 git_op 必须一起清（政策拦截看的就是它）"


def test_force_idle_clears_presence(tmp_path: Path) -> None:
	ws = str(tmp_path / "ws")
	pool = SessionPool(ws, busy_stale_sec=600.0)
	reg = default_session_presence()

	assert pool.try_begin("s2") is not None
	reg.note_tool(ws, "s2", "Bash")

	pool.force_idle("s2")

	assert pool.is_busy("s2") is False
	ent = _presence(ws, "s2")
	assert ent is not None and ent.busy is False, "force_idle 也要落 idle"
	assert ent.current_tool == ""


def test_reclaim_on_try_begin_clears_old_session_but_not_the_new_one(
	tmp_path: Path,
) -> None:
	"""回收发生在 try_begin 内部：不能把刚拿到的新租约也标成 idle。"""
	ws = str(tmp_path / "ws")
	# busy_stale_sec 同时是"s2 必须还没过期"的安全窗口：取 0.01 时这个窗口只有
	# 10ms，机器一忙（并发跑套件）就被判成 idle，给出与产品无关的假红。
	# 现在 s1 侧仍有 3 倍过期余量，s2 侧的安全窗从 10ms 抬到 0.5s。
	pool = SessionPool(ws, busy_stale_sec=0.5)

	assert pool.try_begin("s1") is not None
	time.sleep(1.5)
	assert pool.try_begin("s2") is not None

	assert _presence(ws, "s1").busy is False, "被回收的 s1 应落 idle"
	assert _presence(ws, "s2").busy is True, "新起的 s2 不能被顺手清掉"
	assert pool.is_busy("s2") is True


def test_explicit_end_still_clears(tmp_path: Path) -> None:
	"""原本正确的路径，钉住别在改回收逻辑时被弄坏。"""
	ws = str(tmp_path / "ws")
	pool = SessionPool(ws, busy_stale_sec=600.0)

	lease = pool.try_begin("s3")
	assert lease is not None
	pool.end("s3", lease)
	assert _presence(ws, "s3").busy is False
