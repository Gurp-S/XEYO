"""Transcript 大 payload 外置：JSONL 行只存引用，正文进 {stem}.blobs/{id}.json。"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from msgtypes.message import Message


def blob_threshold_bytes() -> int:
	"""超过此大小的 content 外置；默认 32KB（XEYO_TRANSCRIPT_BLOB_THRESHOLD）。"""
	raw = os.environ.get("XEYO_TRANSCRIPT_BLOB_THRESHOLD", "").strip()
	if raw:
		try:
			return max(512, int(raw))
		except ValueError:
			pass
	return 32_768


def blobs_dir(anchor: Path) -> Path:
	"""与 anchor.jsonl 同级的 blob 目录：``{stem}.blobs/``。"""
	return anchor.parent / f"{anchor.stem}.blobs"


def blob_file(anchor: Path, message_id: str) -> Path:
	return blobs_dir(anchor) / f"{message_id}.json"


def _content_json_bytes(content: Any) -> bytes:
	return json.dumps(content, ensure_ascii=False).encode("utf-8")


def write_content_blob(anchor: Path, message_id: str, content: Any) -> tuple[str, str, int]:
	"""同步写 blob；返回 (content_ref, content_hash, content_bytes)。"""
	payload = _content_json_bytes(content)
	digest = hashlib.sha256(payload).hexdigest()
	target = blob_file(anchor, message_id)
	target.parent.mkdir(parents=True, exist_ok=True)
	tmp = target.with_suffix(".json.tmp")
	tmp.write_bytes(payload)
	os.replace(tmp, target)
	return (f"{message_id}.json", f"sha256:{digest}", len(payload))


def resolve_transcript_row(row: dict[str, Any], anchor: Path) -> dict[str, Any]:
	"""把 content_ref 还原为 inline content（供 hydrate / UI 恢复）。"""
	if not isinstance(row, dict):
		return row
	if row.get("content") is not None:
		return row
	ref = row.get("content_ref")
	if not isinstance(ref, str) or not ref.strip():
		return row
	out = dict(row)
	path = blobs_dir(anchor) / Path(ref).name
	if not path.is_file():
		out["content"] = ""
		return out
	try:
		out["content"] = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		out["content"] = ""
	return out


def resolve_transcript_rows(
	rows: list[dict[str, Any]],
	anchor: Path,
) -> list[dict[str, Any]]:
	return [resolve_transcript_row(row, anchor) for row in rows]


def row_from_message(message: Message, *, anchor: Path) -> dict[str, Any]:
	"""Message → JSONL 行；大 content 外置到 blob 文件。"""
	row: dict[str, Any] = {
		"id": message.id,
		"role": message.role,
		"ts": time.time(),
	}
	if message.tool_call_id:
		row["tool_call_id"] = message.tool_call_id
	if message.name:
		row["name"] = message.name
	# T28：过程旁白（background only）随行留档，供「当时为何动手」追溯。
	if getattr(message, "narration", ""):
		row["narration"] = message.narration
	# 44 号：中断锚（用户看到的必须入史）。
	if getattr(message, "interrupted", False):
		row["interrupted"] = True

	content = message.content
	payload = _content_json_bytes(content)
	if len(payload) >= blob_threshold_bytes() and message.id:
		ref, digest, nbytes = write_content_blob(anchor, message.id, content)
		row["content_ref"] = ref
		row["content_hash"] = digest
		row["content_bytes"] = nbytes
	else:
		row["content"] = content
	return row


def remove_blobs_dir(anchor: Path) -> None:
	"""删除 session 对应的 blob 目录（best-effort）。"""
	import shutil

	root = blobs_dir(anchor)
	if root.is_dir():
		shutil.rmtree(root, ignore_errors=True)
