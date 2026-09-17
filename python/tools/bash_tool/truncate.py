from __future__ import annotations

import os
import re
import uuid

DEFAULT_LIMIT = 30_000
HEAD_CHARS = 20_000
TAIL_CHARS = 8_000

#: 高信号错误行（#13）：命中即视为「必须让模型看见」的证据行。
_ERR_LINE_RE = re.compile(
	r"(?:Traceback|SyntaxError|NameError|TypeError|ValueError|KeyError|"
	r"IndexError|ImportError|ModuleNotFoundError|AttributeError|OSError|"
	r"FileNotFoundError|PermissionError|RuntimeError|AssertionError|"
	r"RecursionError|IndentationError|CompileError|LinkerError|"
	r"undefined reference|No such file|fatal error|collect2:|"
	r"^.*\bE\s+.*|FAILED|failed to (?:build|install|compile)|"
	r"error:|Error:)",
	re.IGNORECASE,
)

#: 从被裁掉的「中段」抢救的错误行上限（防超长报错日志撑爆预览）。
MAX_ERROR_EXCERPT_LINES = 8
MAX_ERROR_EXCERPT_CHARS = 800


def ensure_dir(path: str) -> None:
	os.makedirs(path, exist_ok=True)


def _has_signal_line(text: str) -> bool:
	"""尾部/片段内是否已含高信号错误行（避免重复抢救）。"""
	for line in (text or "").splitlines():
		if _ERR_LINE_RE.search(line):
			return True
	return False


def _error_excerpt(middle: str) -> str:
	"""从中段文本抢救高信号错误行（去重、限量），无则返回空串。"""
	seen: set[str] = set()
	kept: list[str] = []
	chars = 0
	for line in (middle or "").splitlines():
		if not _ERR_LINE_RE.search(line):
			continue
		key = line.strip()
		if not key or key in seen:
			continue
		seen.add(key)
		kept.append(line.rstrip()[:200])
		chars += len(kept[-1])
		if len(kept) >= MAX_ERROR_EXCERPT_LINES or chars >= MAX_ERROR_EXCERPT_CHARS:
			break
	if not kept:
		return ""
	return "[error excerpt preserved from truncated middle]\n" + "\n".join(kept)


def truncate_for_model(
	text: str,
	*,
	limit: int = DEFAULT_LIMIT,
	persist_dir: str,
) -> tuple[str, str | None]:
	"""返回 (给模型看的文本, 完整落盘路径或 None)。

	#13：头部+尾部双向保留（head 20k / tail 8k，中间截断有标记）之外，若**尾部
	没有高信号错误行**，则从中段抢救最多 8 行错误证据拼在截断标记之后——
	防「报错后面又跟了 >8k 成功输出、把关键报错挤出预览」的情况（编译/批量任务
	常见）。契约：模型永远能看到头部 20k、尾部 8k 与（有则）中段错误行。
	"""
	if text is None:
		text = ""

	if len(text) <= limit:
		return text, None

	# 容器路由（2026-09-16）：溢出文件必须落在**容器内**，且路径要以容器形态
	# 告诉模型。原实现写宿主 cwd（``<host cwd>/.xeyo/tool-results/…``）并把该
	# **宿主路径**塞进 ``[output truncated, full at …]``——容器里读不到，
	# 模型照着去读必然失败（证据取不回 + 白烧一轮）。
	path = os.path.join(persist_dir, f"bash-{uuid.uuid4().hex}.txt")
	_full_text = text
	try:
		from tools.container_fs import active_container, write_text as _cfs_write

		if active_container():
			path = f"/tmp/.xeyo/tool-results/bash-{uuid.uuid4().hex}.txt"
			if not _cfs_write(path, _full_text):
				# 落盘失败：宁可给未截断原文（超预算），也不给"假的可取回路径"。
				return text, None
			head = text[:HEAD_CHARS]
			tail = text[-TAIL_CHARS:] if len(text) > HEAD_CHARS + TAIL_CHARS else ""
			middle = text[HEAD_CHARS : len(text) - TAIL_CHARS] if tail else ""
			body = head
			if tail:
				body = head + "\n\n...[middle truncated]...\n\n"
				if middle and not _has_signal_line(tail):
					excerpt = _error_excerpt(middle)
					if excerpt:
						body += excerpt + "\n\n"
				body += tail
			body = body + f"\n\n[output truncated, full at {path} ({len(text)} chars)]"
			return body, path
	except Exception:  # noqa: BLE001 — 路由模块异常回落宿主路径（改动前行为）
		path = os.path.join(persist_dir, f"bash-{uuid.uuid4().hex}.txt")

	ensure_dir(persist_dir)
	with open(path, "w", encoding="utf-8", errors="replace") as f:
		f.write(text)

	head = text[:HEAD_CHARS]
	tail = text[-TAIL_CHARS:] if len(text) > HEAD_CHARS + TAIL_CHARS else ""
	middle = text[HEAD_CHARS : len(text) - TAIL_CHARS] if tail else ""
	body = head
	if tail:
		body = head + "\n\n...[middle truncated]...\n\n"
		if middle and not _has_signal_line(tail):
			excerpt = _error_excerpt(middle)
			if excerpt:
				body += excerpt + "\n\n"
		body += tail
	body = body + f"\n\n[output truncated, full at {path} ({len(text)} chars)]"
	return body, path
