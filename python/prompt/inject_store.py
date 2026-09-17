"""T_now 注入去重台账（B 阶段：装配口旁路件，默认 on）。

设计口径（T_now v2「一个边界三条管道」）：
- 管道 2（引擎当前态）纪律：**值不变不重注**。本模块是这条纪律的落点。
- 管道 3（引擎事件）**永不过本模块**——事件有 drain 语义（取走即清），
  去重会把"第二次发生"误判成"没发生"，静默丢事件。

台账键 = 块登记名（``T_NOW_BLOCK_REGISTRY`` 的 key），值 = 该块上一次注入
文本的指纹。因此去重的充分条件是「上一版仍在模型可见面」——该前提由留痕面
（hidden entry，C 阶段）提供。**C 未落地前本模块不改变任何注入行为**：

- ``on``（默认）：真去重（同 key 同指纹 → 本轮不注入）。
- ``shadow``：只**记录**「本轮本可跳过」的证据（供收益评估），注入照旧。
- ``off``：完全不介入，逐字节等价于无本模块。

硬约束：
1. fail-open：任何异常一律返回「注入」，绝不因台账故障而丢模型可见信息。
2. 有界：会话数 LRU 硬顶 + 单会话键数硬顶，防长驻进程内存泄漏。
3. 纯旁路：本模块不持有任何模型可见文本，只持有指纹。
"""

from __future__ import annotations

import hashlib
import os
import threading
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

#: 档位开关：``on``（默认） | ``shadow``（只观测） | ``off``（逃生门）
FLAG_ENV = "XEYO_T_NOW_DEDUP"

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ON = "on"

#: 单会话键数硬顶（登记块数远小于此；超限按插入序淘汰，防异常膨胀）
MAX_KEYS_PER_SESSION = 64
#: 会话数硬顶（LRU：最久未 begin 的会话先淘汰）
MAX_SESSIONS = 64


@dataclass(frozen=True)
class Note:
	"""待落库的留痕条目（管道 2 状态块 → 历史中的 hidden system 消息）。"""

	key: str
	kind: str
	fp: str
	text: str


def mode() -> str:
	"""读档位：``off`` / ``shadow`` 显式声明，其余（含未设/未知值）一律 ``on``。

	``on`` 是 T_now v2 的**设计行为**（管道 2：值不变不重注），所以默认就是它；
	``off`` 是逃生门（逐字节回到旧行为），``shadow`` 是只观测不生效的采集档。
	"""
	raw = (os.environ.get(FLAG_ENV) or "").strip().lower()
	if raw == MODE_OFF:
		return MODE_OFF
	if raw == MODE_SHADOW:
		return MODE_SHADOW
	return MODE_ON


def fingerprint(text: str) -> str:
	"""文本指纹：行尾空白与 CRLF 归一后取 sha256 前 32 位（128 bit）。

	归一的目的只是「同一份状态不因换行风格差异被当成变了」；不做 trim
	之外的语义改写（缩进、空行、大小写一律保留）。
	"""
	norm = "\n".join(line.rstrip() for line in (text or "").replace("\r\n", "\n").split("\n"))
	norm = norm.strip()
	return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]


class InjectStore:
	"""按会话记账的注入去重台账（进程内单例，见 :func:`get_store`）。"""

	def __init__(self) -> None:
		self._ledger: dict[str, dict[str, str]] = {}
		#: 待落库的留痕条目：session → {key: Note}（同 key 只留最新版本）
		self._pending: dict[str, dict[str, "Note"]] = {}
		self._lock = threading.Lock()
		self._hits = 0  # 判定为「值未变」（on 档＝跳过；shadow 档＝本可跳过）
		self._misses = 0  # 判定为「新值」（注入）
		self._would_skip: dict[str, int] = {}
		#: 台账说"在历史里"、投影里却没有的次数（历史被改写未清账的证据面）
		self._stale = 0
		self._stale_keys: dict[str, int] = {}
		#: 被兼容性闸拦下、拒绝写留痕的次数（A：system-in-middle 不兼容 provider）
		self._disarmed: dict[str, int] = {}

	def begin(self, session_id: str) -> None:
		"""标记本轮所属会话（无 session_id 时本轮不参与去重）。"""
		sid = (session_id or "").strip()
		if not sid:
			return
		try:
			with self._lock:
				table = self._ledger.get(sid)
				if table is None:
					self._evict_if_needed()
					table = {}
					self._ledger[sid] = table
				else:
					# LRU：触碰即置尾
					self._ledger.pop(sid, None)
					self._ledger[sid] = table
		except Exception:  # noqa: BLE001
			pass

	def decide(
		self,
		name: str,
		text: str,
		*,
		visible: frozenset[tuple[str, str]] | None = None,
	) -> bool:
		"""返回 True = 本轮应注入；False = 同 key 同值**且确实还在可见面**。

		两个前提缺一不可，否则一律重发（宁可多注入一次，绝不静默丢块）：
		1. 台账已 **commit**（那一版真的落进过历史）；
		2. ``visible`` 给出时，``(key, fp)`` **在本轮投影里真实存在**
		   —— 台账只是快路径，投影才是真相源（历史被改写却没人清账时靠它兜底）。
		``off`` 档恒 True（不记账）；``shadow`` 档恒 True（只记证据）；
		``on`` 档才可能返回 False。任何异常 → True（fail-open）。
		"""
		key = (name or "").strip()
		if not key:
			return True
		cur = mode()
		if cur == MODE_OFF:
			return True
		sid = _CURRENT.get()
		if not sid:
			return True
		try:
			fp = fingerprint(text)
			with self._lock:
				table = self._ledger.get(sid)
				if table is None:
					return True
				pending = self._pending.get(sid) or {}
				prev = table.get(key)
				_hist_ok = prev is not None and prev == fp
				if _hist_ok and visible is not None and (key, fp) not in visible:
					# 台账说"还在历史里"，本轮投影里却没有 ⇒ 历史被改写且无人清账。
					# 计证据、继续注入（并让调用方下一轮拿到重注后的新账）。
					self._stale += 1
					self._stale_keys[key] = self._stale_keys.get(key, 0) + 1
					_hist_ok = False
				_vis_ok = visible is None or (key, fp) in visible
				unchanged = _hist_ok and _vis_ok and key not in pending
				if unchanged:
					self._hits += 1
					self._would_skip[key] = self._would_skip.get(key, 0) + 1
					return cur != MODE_ON
				self._misses += 1
				if cur == MODE_SHADOW:
					# 只观测档：记账用于统计「本可跳过」，但绝不跳过注入
					table[key] = fp
				return True
		except Exception:  # noqa: BLE001 — fail-open：台账故障不得影响可见面
			return True

	def commit(self, session_id: str, key: str, fp: str) -> None:
		"""留痕**落库成功**后提交台账：此后同值才允许判「值没变」。"""
		sid = (session_id or "").strip()
		name = (key or "").strip()
		if not sid or not name or not fp:
			return
		try:
			with self._lock:
				table = self._ledger.setdefault(sid, {})
				if len(table) >= MAX_KEYS_PER_SESSION and name not in table:
					table.pop(next(iter(table)), None)
				table[name] = fp
		except Exception:  # noqa: BLE001
			pass

	def note(self, session_id: str, key: str, text: str, *, kind: str = "") -> Note | None:
		"""登记留痕条目（同 key 只留最新版本 → 落库即"值变才追加一条"）。

		只在 ``on`` 档登记：``off``/``shadow`` 不写历史（逐字节等价旧行为）。
		"""
		if mode() != MODE_ON:
			return None
		sid = (session_id or "").strip()
		name = (key or "").strip()
		body = (text or "").strip()
		if not sid or not name or not body:
			return None
		item = Note(key=name, kind=(kind or "").strip(), fp=fingerprint(body), text=body)
		try:
			with self._lock:
				table = self._pending.setdefault(sid, {})
				if len(table) >= MAX_KEYS_PER_SESSION and name not in table:
					table.pop(next(iter(table)), None)
				table[name] = item
		except Exception:  # noqa: BLE001
			return None
		return item

	def drain_notes(self, session_id: str) -> list[Note]:
		"""取走待落库条目（取走即清：落库失败也不会重复追加）。"""
		sid = (session_id or "").strip()
		if not sid:
			return []
		try:
			with self._lock:
				table = self._pending.pop(sid, None) or {}
				return list(table.values())
		except Exception:  # noqa: BLE001
			return []

	def invalidate(self, session_id: str) -> None:
		"""历史被改写（压缩）后清账：下一轮按当前值重注（先压缩、后重注）。"""
		sid = (session_id or "").strip()
		if not sid:
			return
		try:
			with self._lock:
				self._ledger.pop(sid, None)
		except Exception:  # noqa: BLE001
			pass

	def pending_count(self, session_id: str) -> int:
		with self._lock:
			return len(self._pending.get((session_id or "").strip(), {}))

	def note_disarmed(self, session_id: str) -> None:
		"""记录一次「兼容闸拦下留痕」（观测面：该 provider 走了非 system 声道）。"""
		sid = (session_id or "").strip() or "?"
		try:
			with self._lock:
				self._disarmed[sid] = self._disarmed.get(sid, 0) + 1
		except Exception:  # noqa: BLE001
			pass

	def forget(self, session_id: str) -> None:
		"""会话结束/重启时清账（压缩重写历史后同样应清，见契约 C6）。"""
		sid = (session_id or "").strip()
		if not sid:
			return
		try:
			with self._lock:
				self._ledger.pop(sid, None)
				self._pending.pop(sid, None)
		except Exception:  # noqa: BLE001
			pass

	def clear(self) -> None:
		"""全清（测试与进程级复位用）。"""
		with self._lock:
			self._ledger.clear()
			self._pending.clear()
			self._would_skip.clear()
			self._stale_keys.clear()
			self._disarmed.clear()
			self._hits = 0
			self._misses = 0
			self._stale = 0

	def stats(self) -> dict[str, Any]:
		"""观测面：``hits`` = 值未变次数，``stale`` = 台账与投影不一致次数。

		``stale`` 长时间为 0 才说明清账点覆盖完整；一旦非 0，说明有改写历史
		却没人调 :func:`invalidate` 的路径（靠每轮投影校验兜住，不丢块）。
		"""
		with self._lock:
			return {
				"mode": mode(),
				"sessions": len(self._ledger),
				"hits": self._hits,
				"misses": self._misses,
				"stale": self._stale,
				"stale_keys": dict(self._stale_keys),
				"disarmed": dict(self._disarmed),
				"would_skip": dict(self._would_skip),
			}

	def _evict_if_needed(self) -> None:
		while len(self._ledger) >= MAX_SESSIONS:
			self._ledger.pop(next(iter(self._ledger)), None)


_STORE = InjectStore()
#: 本轮所属会话（由 :func:`begin_round` 设置；装配点据此查账）
_CURRENT: ContextVar[str] = ContextVar("xeyo_inject_store_session", default="")


def get_store() -> InjectStore:
	return _STORE


def begin_round(session_id: str) -> Token:
	"""装配口入口调用：把本轮会话写进 contextvar，返回复位句柄。"""
	_STORE.begin(session_id)
	return _CURRENT.set((session_id or "").strip())


def end_round(token: Token) -> None:
	try:
		_CURRENT.reset(token)
	except Exception:  # noqa: BLE001 — 跨上下文复位失败不致命
		pass


def decide(
	name: str,
	text: str,
	*,
	visible: frozenset[tuple[str, str]] | None = None,
) -> bool:
	"""装配点调用：True = 注入，False = 本轮跳过。

	``visible`` = 本轮投影里真实存在的留痕身份集合（真相源；None = 未提供）。
	"""
	return _STORE.decide(name, text, visible=visible)


def note(key: str, text: str, *, kind: str = "") -> None:
	"""装配点调用：把本轮送达的状态块登记为留痕条目（``on`` 档才生效）。

	落库时点在下一个边界（``engine/t_now_notes.persist_pending``）——本轮由
	T_now 尾部送达，下一轮起由历史承载，台账据此判「值没变」不再重发。
	"""
	_STORE.note(_CURRENT.get(), key, text, kind=kind)


def current_session() -> str:
	"""本轮所属会话（装配点/落库侧定位目标用）。"""
	return _CURRENT.get()


__all__ = [
	"FLAG_ENV",
	"MODE_OFF",
	"MODE_ON",
	"MODE_SHADOW",
	"InjectStore",
	"Note",
	"begin_round",
	"commit",
	"current_session",
	"decide",
	"drain_notes",
	"end_round",
	"fingerprint",
	"get_store",
	"invalidate",
	"mode",
	"note",
	"note_disarmed",
]


def drain_notes(session_id: str) -> list[Note]:
	"""落库侧调用：取走某会话的待落库留痕条目（取走即清）。"""
	return _STORE.drain_notes(session_id)


def commit(session_id: str, key: str, fp: str) -> None:
	"""落库侧调用：条目**写进历史成功后**提交台账（此后同值才算"值没变"）。"""
	_STORE.commit(session_id, key, fp)


def invalidate(session_id: str) -> None:
	"""压缩改写历史后调用：清账 ⇒ 下一轮按当前值重注。"""
	_STORE.invalidate(session_id)


def note_disarmed(session_id: str) -> None:
	"""兼容闸拦下一次留痕写入（观测面：该会话走了非 system 声道）。"""
	_STORE.note_disarmed(session_id)
