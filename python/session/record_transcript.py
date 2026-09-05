"""record_transcript — 把消息追加写入 session JSONL（按 id 去重）。

对齐 Claude QueryEngine 阶段 ④/⑥/⑦ 的 recordTranscript 用法:
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

# 按 transcript 路径缓存已写入 id，避免 ui_thought 同步等路径反复全文件扫描。
_known_ids_cache: dict[str, set[str]] = {}

# 后台写入队列：(seq, path, line)。seq 单调递增，用于 flush 判定「全部落盘」。
_pending: list[tuple[int, str, str]] = []
_cv = threading.Condition()
_submitted_seq = 0
_written_seq = 0
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
	global _written_seq
	while True:
		with _cv:
			while not _pending and not _stop:
				_cv.wait(timeout=0.05)
			if not _pending and _stop:
				return
			batch = list(_pending)
			_pending.clear()
			max_seq = batch[-1][0]
		try:
			_write_batch(batch)
		except Exception:  # noqa: BLE001
			_logger.debug("transcript writer batch failed", exc_info=True)
		with _cv:
			_written_seq = max(_written_seq, max_seq)
			_cv.notify_all()


def _write_batch(batch: list[tuple[int, str, str]]) -> None:
	by_path: dict[str, list[str]] = {}
	for _seq, path, line in batch:
		by_path.setdefault(path, []).append(line)
	for path, lines in by_path.items():
		p = Path(path)
		p.parent.mkdir(parents=True, exist_ok=True)
		_maybe_rotate(p)
		with p.open("a", encoding="utf-8") as f:
			f.writelines(lines)
			f.flush()


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
	if not lines:
		return
	with _cv:
		for line in lines:
			_submitted_seq += 1
			_pending.append((_submitted_seq, path, line))
		_cv.notify_all()
	_ensure_writer()


def flush_pending_sync(timeout: float = 5.0) -> bool:
	"""阻塞等待所有已提交行落盘；返回是否在超时前排空。"""
	deadline = time.monotonic() + timeout
	with _cv:
		while _written_seq < _submitted_seq:
			if time.monotonic() >= deadline:
				return False
			_cv.wait(0.2)
		return True


def _atexit_drain() -> None:
	global _stop
	with _cv:
		_stop = True
		_cv.notify_all()
	flush_pending_sync(timeout=2.0)


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
			with p.open("r", encoding="utf-8") as f:
				for line in f:
					line = line.strip()
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

	path.parent.mkdir(parents=True, exist_ok=True)
	_maybe_rotate(path)
	with path.open("a", encoding="utf-8") as f:
		for m in pending:
			f.write(
				json.dumps(message_to_dict(m, anchor=path), ensure_ascii=False) + "\n"
			)
			known.add(m.id)
		f.flush()
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
		return 0
	rows = [
		json.dumps(message_to_dict(m, anchor=target), ensure_ascii=False) + "\n"
		for m in pending
	]
	# 先记账再去重：known 挡掉后续重复提交，行内容交给后台线程写盘。
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

	return _append_new_messages(messages, path=target, known=known)


def load_transcript(path: Path) -> list[dict[str, Any]]:
	"""读取 JSONL，返回 dict 列表（resume 时再用）。"""
	if not path.is_file():
		return []
	out: list[dict[str, Any]] = []
	with path.open("r", encoding="utf-8") as f:
		for line in f:
			line = line.strip()
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
	flush_pending_sync()
