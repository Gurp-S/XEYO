from __future__ import annotations

import os
import uuid

DEFAULT_LIMIT = 30_000
HEAD_CHARS = 20_000
TAIL_CHARS = 8_000


def ensure_dir(path: str) -> None:
	os.makedirs(path, exist_ok=True)


def truncate_for_model(
	text: str,
	*,
	limit: int = DEFAULT_LIMIT,
	persist_dir: str,
) -> tuple[str, str | None]:
	"""返回 (给模型看的文本, 完整落盘路径或 None)。"""
	if text is None:
		text = ""
	if len(text) <= limit:
		return text, None

	ensure_dir(persist_dir)
	path = os.path.join(persist_dir, f"bash-{uuid.uuid4().hex}.txt")
	with open(path, "w", encoding="utf-8", errors="replace") as f:
		f.write(text)

	head = text[:HEAD_CHARS]
	tail = text[-TAIL_CHARS:] if len(text) > HEAD_CHARS + TAIL_CHARS else ""
	body = head
	if tail:
		body = head + "\n\n...[middle truncated]...\n\n" + tail
	body = body + f"\n\n[output truncated, full at {path} ({len(text)} chars)]"
	return body, path
