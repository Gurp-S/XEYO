"""record_transcript — 把消息追加写入 session JSONL（按 id 去重）。

转录用法约定:
  - persist 关闭时直接 no-op
  - 只追加尚未写过的消息
  - 用户消息进 loop 前就可先调一次，避免中途杀掉后无法 resume

热路径（async record_transcript）不再在事件循环上同步写盘：
去重记账在主线程完成，磁盘 IO 交给后台批量写入线程；
flush_transcript() 阻塞等待队列排空，保证提交的转录已落盘。
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from msgtypes.message import Message
from session.persistence import (
	should_persist,
	transcript_path as default_transcript_path,
)
from session.transcript_blobs import row_from_message

_logger = logging.getLogger(__name__)

# Accepted IDs reserve queued rows; a successful flush confirms durability.
# Failed rows remain owned by the queue until an explicit retry succeeds.
_known_ids_cache: dict[str, set[str]] = {}

# G107: 磁盘临界区锁——所有物理写入路径共用，防止 rotate(rename 当前→归档)
# 与另一路 append 交错，造成行写入已轮转归档或新文件中的重复/丢失。
_disk_lock = threading.Lock()

# 后台写入队列：(seq, path, line)。seq 单调递增，用于 flush 判定「全部落盘」。
_pending: list[tuple[int, str, str]] = []
_failed: list[tuple[int, str, str]] = []
_retry_paths: set[str] = set()
_writing = False
_cv = threading.Condition()
_submitted_seq = 0
_writer_thread: threading.Thread | None = None
_stop = False


def _max_transcript_bytes() -> int:
	"""单文件上限；超过即轮转（保留 2 代归档，可跨轮转恢复）。

	默认 32MB，可用 XEYO_TRANSCRIPT_MAX_BYTES 覆盖（下限 1MB）。
	"""
	raw = os.environ.get("XEYO_TRANSCRIPT_MAX_BYTES", "").strip()
	if raw:
		try:
			return max(1024, int(raw))
		except ValueError:
			pass
	return 32_000_000


# 保留的归档代数：<name>.jsonl.old1（较新）… .old<N>（最旧）。
_ROTATION_KEEP = 2


def rotated_transcript_paths(path: Path) -> list[Path]:
	"""按「最旧 → 最新」返回全部归档路径（不检查存在性）。"""
	return [
		path.with_name(path.name + f".old{i}")
		for i in range(_ROTATION_KEEP, 0, -1)
	]


def rotated_transcript_path(path: Path) -> Path:
	"""最新一代归档路径（<name>.jsonl.old1）；兼容单归档调用方。"""
	return path.with_name(path.name + ".old1")


def _maybe_rotate(path: Path) -> None:
	"""写前检查：超过上限则把当前文件挪入归档链（.old1←current，依次后移），
	最旧一代删除；新写入从空文件开始。
	"""
	try:
		if not path.is_file() or path.stat().st_size <= _max_transcript_bytes():
			return
		olds = rotated_transcript_paths(path)
		oldest = olds[0]
		if oldest.is_file():
			oldest.unlink()
		for i in range(len(olds) - 1):
			if olds[i].is_file():
				os.replace(olds[i], olds[i + 1])
		os.replace(path, olds[-1])
	except OSError:
		_logger.debug("transcript rotate failed for %s", path, exc_info=True)


def transcript_read_paths(path: Path) -> list[Path]:
	"""按时间顺序返回应读取的 transcript 文件：[归档…]（存在者）+ 当前。"""
	return [p for p in rotated_transcript_paths(path) if p.is_file()] + [path]


def discard_rotated_transcripts(path: Path) -> list[str]:
	"""删除轮转归档，防止 rollback 截断后 GET/hydrate 把已删回合再拼回来。

	返回已删除路径的字符串列表（便于审计）。当前 ``path`` 本身不动。
	"""
	removed: list[str] = []
	for archived in rotated_transcript_paths(path):
		if not archived.is_file():
			continue
		try:
			archived.unlink()
			removed.append(str(archived))
		except OSError:
			_logger.debug("discard rotated transcript failed: %s", archived, exc_info=True)
	return removed


def _writer_loop() -> None:
	"""批量消费队列：一次取出一整批，按 path 分组追加写盘。"""
	global _writing
	while True:
		with _cv:
			while not _pending and not _stop:
				_cv.wait(timeout=0.05)
			if not _pending and _stop:
				return
			batch = list(_pending)
			_pending.clear()
			_writing = True
		groups: dict[str, list[tuple[int, str, str]]] = {}
		for item in batch:
			groups.setdefault(item[1], []).append(item)
		failed = []
		for path, items in groups.items():
			try:
				_write_batch(items)
			except Exception:  # noqa: BLE001
				_logger.debug("transcript writer batch failed", exc_info=True)
				failed.extend(items)
			else:
				_retry_paths.discard(path)
		with _cv:
			failed_paths = {path for _, path, _ in failed}
			_failed.extend(failed)
			_failed.extend(item for item in _pending if item[1] in failed_paths)
			_pending[:] = [item for item in _pending if item[1] not in failed_paths]
			_retry_paths.update(failed_paths)
			_writing = False
			_cv.notify_all()


def _write_batch(batch: list[tuple[int, str, str]]) -> None:
	by_path: dict[str, list[str]] = {}
	for _seq, path, line in batch:
		by_path.setdefault(path, []).append(line)
	for path, lines in by_path.items():
		p = Path(path)
		# rotate + append 同一临界区,杜绝与 sync 直写交错(G107)
		with _disk_lock:
			p.parent.mkdir(parents=True, exist_ok=True)
			if path in _retry_paths:
				from session.transcript_retry import reconcile_retry
				lines = reconcile_retry(p, transcript_read_paths(p), lines)
			if lines:
				_maybe_rotate(p)
			with p.open("a", encoding="utf-8") as f:
				f.writelines(lines)
				f.flush()
				os.fsync(f.fileno())  # 崩溃窗口不丢会话尾部(G107)


def _ensure_writer() -> None:
	global _writer_thread
	with _cv:
		if _writer_thread is not None and _writer_thread.is_alive():
			return
		_writer_thread = threading.Thread(
			target=_writer_loop, name="transcript-writer", daemon=True
		)
		_writer_thread.start()


def submit_async_append(path: str, lines: list[str]) -> None:
	"""把待写行入队；调用方必须已完成去重记账（known_ids 就地更新）。"""
	global _submitted_seq
	with _cv:
		if not lines and not _failed:
			return
		if _failed:
			_pending[:0] = _failed
			_failed.clear()
		for line in lines:
			_submitted_seq += 1
			_pending.append((_submitted_seq, path, line))
		_cv.notify_all()
	_ensure_writer()


def flush_pending_sync(timeout: float = 5.0) -> bool:
	"""阻塞等待所有已提交行落盘；返回是否在超时前排空。"""
	deadline = time.monotonic() + timeout
	with _cv:
		# One retry per explicit flush; failed batches never spin in the writer.
		if _failed:
			_pending[:0] = _failed
			_failed.clear()
			_cv.notify_all()
		while _pending or _writing:
			if time.monotonic() >= deadline:
				return False
			_cv.wait(0.2)
		return not _failed


def _atexit_drain() -> None:
	global _stop
	flush_pending_sync(timeout=2.0)
	with _cv:
		_stop = True
		_cv.notify_all()


atexit.register(_atexit_drain)


def message_to_dict(message: Message, *, anchor: Path | None = None) -> dict[str, Any]:
	if anchor is not None:
		return row_from_message(message, anchor=anchor)
	return {
		"id": message.id,
		"role": message.role,
		"content": message.content,
		"tool_call_id": message.tool_call_id,
		"name": message.name,
		**({"narration": message.narration} if getattr(message, "narration", "") else {}),
		**({"interrupted": True} if getattr(message, "interrupted", False) else {}),
		"ts": time.time(),
	}


def _resolve_known_ids(path: Path, known_ids: set[str] | None) -> set[str]:
	"""返回去重集合：优先复用调用方传入的 known_ids，并写入路径级缓存。"""
	key = str(path)
	if known_ids is not None:
		_known_ids_cache[key] = known_ids
		if not known_ids and path.is_file():
			known_ids.update(_load_written_ids(path))
		return known_ids
	cached = _known_ids_cache.get(key)
	if cached is not None:
		return cached
	loaded = _load_written_ids(path)
	_known_ids_cache[key] = loaded
	return loaded


def _load_written_ids(path: Path) -> set[str]:
	known: set[str] = set()
	for p in transcript_read_paths(path):
		if not p.is_file():
			continue
		try:
			# 逐行按字节解码：进程在 append 中途被强杀会留下半个 UTF-8 序列，
			# 文本模式一遇坏字节就整文件抛 UnicodeDecodeError（不是 OSError）⇒
			# 该会话之后每一次落盘都失败。坏行只丢它自己，与下面
			# JSONDecodeError 的"跳过这一行"同一口径。
			with p.open("rb") as f:
				for raw in f:
					line = raw.decode("utf-8", errors="replace").strip()
					if not line:
						continue
					try:
						obj = json.loads(line)
					except json.JSONDecodeError:
						continue
					mid = obj.get("id")
					if isinstance(mid, str) and mid:
						known.add(mid)
		except OSError:
			continue
	return known


def _append_new_messages(
	messages: Iterable[Message],
	*,
	path: Path,
	known: set[str],
) -> int:
	"""追加未写过的消息，返回新写入条数。"""
	pending = [m for m in messages if m.id and m.id not in known]
	if not pending:
		return 0

	# 与后台 writer 同一临界区:rotate+append 不交错;fsync 落盘(G107)
	with _disk_lock:
		path.parent.mkdir(parents=True, exist_ok=True)
		_maybe_rotate(path)
		with path.open("a", encoding="utf-8") as f:
			for m in pending:
				f.write(
					json.dumps(message_to_dict(m, anchor=path), ensure_ascii=False)
					+ "\n"
				)
				known.add(m.id)
			f.flush()
			os.fsync(f.fileno())
	return len(pending)


async def record_transcript(
	messages: list[Message] | tuple[Message, ...],
	*,
	session_id: str,
	path: Path | None = None,
	session_persistence_disabled: bool | None = None,
	known_ids: set[str] | None = None,
) -> int:
	"""异步入口：去重记账在主线程完成，磁盘 IO 由后台线程批量写入。

	Args:
	  messages: 当前要考虑落盘的消息列表（通常是整段历史或本回合增量）
	  session_id: 会话 id，用于默认文件名
	  path: 显式 JSONL 路径；默认 ~/.xeyo/sessions/<id>.jsonl
	  session_persistence_disabled: 会话级开关；True 则不写
	  known_ids: 可选内存缓存，避免每次全文件扫描；会就地更新

	Returns:
	  新写入的消息条数（记账数；实际落盘由后台线程异步完成）
	"""
	if not should_persist(session_flag=session_persistence_disabled):
		return 0

	target = path or default_transcript_path(session_id)
	known = _resolve_known_ids(target, known_ids)

	pending = [m for m in messages if m.id and m.id not in known]
	if not pending:
		submit_async_append(str(target), [])
		return 0
	rows = [
		json.dumps(message_to_dict(m, anchor=target), ensure_ascii=False) + "\n"
		for m in pending
	]
	# known reserves accepted rows, including recoverable failed appends.
	# Only a successful flush certifies that these rows reached disk.
	for m in pending:
		known.add(m.id)
	submit_async_append(str(target), rows)
	return len(pending)


def record_transcript_sync(
	messages: list[Message] | tuple[Message, ...],
	*,
	session_id: str,
	path: Path | None = None,
	session_persistence_disabled: bool | None = None,
	known_ids: set[str] | None = None,
) -> int:
	"""同步版，便于测试 / 非 async 调用点。"""
	if not should_persist(session_flag=session_persistence_disabled):
		return 0

	target = path or default_transcript_path(session_id)
	known = _resolve_known_ids(target, known_ids)
	pending = [m for m in messages if m.id and m.id not in known]
	if not pending:
		if not flush_pending_sync():
			raise OSError("transcript append incomplete")
		return 0
	rows = [
		json.dumps(message_to_dict(m, anchor=target), ensure_ascii=False) + "\n"
		for m in pending
	]
	# 同步调用方也进入同一全局有序队列。此前这里直写文件，而普通
	# record_transcript() 走后台队列，导致 system 留痕可能插入一个多工具
	# 批次的两个 role=tool 行之间，重启后上游会返回 400。
	for m in pending:
		known.add(m.id)
	submit_async_append(str(target), rows)
	if not flush_pending_sync():
		raise TimeoutError("transcript writer did not drain")
	return len(pending)


def load_transcript(path: Path) -> list[dict[str, Any]]:
	"""读取 JSONL，返回 dict 列表（resume 时再用）。"""
	if not path.is_file():
		return []
	out: list[dict[str, Any]] = []
	# 与 _load_written_ids 同口径：坏字节只报废它所在的那一行，绝不因
	# UnicodeDecodeError 让整份转录打不开（resume / session_pool 会直接 500）。
	with path.open("rb") as f:
		for raw in f:
			line = raw.decode("utf-8", errors="replace").strip()
			if not line:
				continue
			try:
				out.append(json.loads(line))
			except json.JSONDecodeError:
				continue
	return out


async def record_ui_thoughts(
	thoughts: Iterable[dict[str, Any]],
	*,
	session_id: str,
	path: Path | None = None,
	known_ids: set[str] | None = None,
) -> int:
	"""追加 UI-only reasoning 块到 transcript（role=ui_thought，engine hydrate 会跳过）。"""
	if not should_persist():
		return 0

	target = path or default_transcript_path(session_id)
	known = _resolve_known_ids(target, known_ids)
	rows: list[str] = []
	for t in thoughts:
		if not isinstance(t, dict):
			continue
		tid = t.get("id")
		text = t.get("text")
		if text is None:
			text = t.get("content")
		if not isinstance(tid, str) or not tid.strip():
			continue
		if tid.strip() in known:
			continue
		if not isinstance(text, str) or not text.strip():
			continue
		ts = t.get("ts")
		if not isinstance(ts, (int, float)):
			created = t.get("createdAt")
			ts = (
				float(created) / 1000.0
				if isinstance(created, (int, float))
				else time.time()
			)
		row: dict[str, Any] = {
			"id": tid.strip(),
			"role": "ui_thought",
			"content": text.strip(),
			"ts": float(ts),
		}
		thought_ms = t.get("thought_ms")
		if thought_ms is None:
			thought_ms = t.get("thoughtMs")
		if isinstance(thought_ms, (int, float)) and thought_ms >= 0:
			row["thought_ms"] = int(thought_ms)
		rows.append(json.dumps(row, ensure_ascii=False) + "\n")
		known.add(tid.strip())

	if not rows:
		return 0
	submit_async_append(str(target), rows)
	return len(rows)


def flush_transcript(path: Path | None = None) -> None:
	"""阻塞等待后台写入队列排空（保证调用返回后转录已落盘）。"""
	_ = path
	if not flush_pending_sync():
		raise OSError("transcript append incomplete")
