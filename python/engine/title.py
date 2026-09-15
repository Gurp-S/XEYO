"""会话标题（T5）：确定性即时标题 + 可选异步 LLM 增强。

- ``instant_title``：零延迟、无模型依赖；从首条用户消息推导，UTF-8 按字节
  预算安全截断（不切坏多字节字符）。
- 标题落盘 sidecar ``<sessions>/<safe>.title.json``：
  ``{"title", "pinned", "enhanced", "ts"}``；transcript 本体保持不动
  （投影字节稳定性不受影响）。
- ``pinned``（用户显式 rename）永不被自动路径覆盖。
- ``enhance_with_model``：``purpose='session-title'`` 旁路请求；thinking 关、
  无工具、dispatch 前写审计（``title.enhance``）；空结果 / 非 stop 结束 /
  pinned 一律拒绝采纳，保留即时标题。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, AsyncIterator, Protocol

#: 即时标题字节预算（UTF-8；CJK 每 char 3 字节 → 约 32 个汉字）。
MAX_TITLE_BYTES = 96

DEFAULT_TITLE = "新会话"

_MD_NOISE_RE = re.compile(r"[#>*_`~]+")
_LEADING_MARKER_RE = re.compile(r"^[\-\+•·]+\s*")




class _StreamClient(Protocol):
	"""最小流式客户端契约（ModelClient 兼容）。"""

	def stream(
		self,
		messages: list[dict],
		tools: list[dict],
		abort: Any,
	) -> AsyncIterator[Any]: ...


def _byte_safe_truncate(text: str, limit: int = MAX_TITLE_BYTES) -> str:
	"""按 UTF-8 字节预算截断；绝不切坏多字节字符。"""
	raw = text.encode("utf-8")
	if len(raw) <= limit:
		return text
	out: list[str] = []
	used = 0
	for ch in text:
		w = len(ch.encode("utf-8"))
		if used + w > limit:
			break
		out.append(ch)
		used += w
	return "".join(out).rstrip()


def instant_title(first_user_text: str) -> str:
	"""从首条用户消息推导确定性标题：去 markdown 噪声、折叠空白、安全截断。"""
	raw = str(first_user_text or "")
	for line in raw.splitlines():
		line = line.strip()
		if line:
			raw = line
			break
	else:
		return DEFAULT_TITLE
	line = _MD_NOISE_RE.sub("", raw.strip()).strip()
	line = _LEADING_MARKER_RE.sub("", line).strip()
	line = re.sub(r"\s+", " ", line)
	if not line:
		return DEFAULT_TITLE
	title = _byte_safe_truncate(line)
	return title or DEFAULT_TITLE


# ── sidecar 持久化 ────────────────────────────────────────────────


def _sessions_dir(sessions_dir: Path | None = None) -> Path:
	if sessions_dir is not None:
		return Path(sessions_dir)
	from session.persistence import default_sessions_dir

	return default_sessions_dir()


def _safe_name(session_id: str) -> str:
	from session.persistence import safe_session_filename

	return safe_session_filename(session_id)


def title_sidecar_path(
	session_id: str, *, sessions_dir: Path | None = None
) -> Path:
	return _sessions_dir(sessions_dir) / f"{_safe_name(session_id)}.title.json"


def read_title(
	session_id: str, *, sessions_dir: Path | None = None
) -> dict[str, Any] | None:
	"""读标题 sidecar；坏文件视为不存在（跳过并忽略）。"""
	p = title_sidecar_path(session_id, sessions_dir=sessions_dir)
	try:
		obj = json.loads(p.read_text(encoding="utf-8"))
	except (OSError, ValueError):
		return None
	if not isinstance(obj, dict):
		return None
	title = str(obj.get("title") or "").strip()
	if not title:
		return None
	return {
		"title": title,
		"pinned": bool(obj.get("pinned")),
		"enhanced": bool(obj.get("enhanced")),
		"ts": float(obj.get("ts") or 0.0),
	}


def write_title(
	session_id: str,
	title: str,
	*,
	pinned: bool = False,
	enhanced: bool = False,
	sessions_dir: Path | None = None,
) -> dict[str, Any]:
	"""写标题 sidecar（O_EXCL 语义不必要——同 key 覆盖是常规操作）。

	已 pinned 的条目只有 ``pinned=True`` 的调用（显式 rename）能改写。
	"""
	p = title_sidecar_path(session_id, sessions_dir=sessions_dir)
	clean = _byte_safe_truncate(str(title or "").strip()) or DEFAULT_TITLE
	existing = read_title(session_id, sessions_dir=sessions_dir)
	if existing and existing.get("pinned") and not pinned:
		return existing
	entry: dict[str, Any] = {
		"title": clean,
		"pinned": bool(pinned),
		"enhanced": bool(enhanced),
		"ts": round(time.time(), 3),
	}
	p.parent.mkdir(parents=True, exist_ok=True)
	tmp = p.with_suffix(".tmp")
	try:
		tmp.write_text(
			json.dumps(entry, ensure_ascii=False, indent=None), encoding="utf-8"
		)
		os.replace(tmp, p)
	except OSError:
		# sidecar 失败不影响会话本身：标题回退即时推导。
		return entry
	return entry


def ensure_instant_title(session_id: str, first_user_text: str) -> dict[str, Any]:
	"""会话首次消息时落一个即时标题；已有 sidecar 则原样返回。"""
	existing = read_title(session_id)
	if existing is not None:
		return existing
	return write_title(session_id, instant_title(first_user_text))


# ── 归档 sidecar（smoke-test #3：归档/找回，不动 transcript）──────


def archive_sidecar_path(
	session_id: str, *, sessions_dir: Path | None = None
) -> Path:
	"""归档标记 sidecar 路径：``<safe>.archive.json``。"""
	return _sessions_dir(sessions_dir) / f"{_safe_name(session_id)}.archive.json"


def read_archive(
	session_id: str, *, sessions_dir: Path | None = None
) -> dict[str, Any] | None:
	"""读归档 sidecar；无文件 / 坏 JSON / 缺 archivedAt 一律视为未归档。"""
	p = archive_sidecar_path(session_id, sessions_dir=sessions_dir)
	try:
		obj = json.loads(p.read_text(encoding="utf-8"))
	except (OSError, ValueError):
		return None
	if not isinstance(obj, dict):
		return None
	archived_at = obj.get("archivedAt")
	if not isinstance(archived_at, (int, float)):
		return None
	return {
		"archivedAt": float(archived_at),
		"reason": str(obj.get("reason") or "user"),
	}


def write_archive(
	session_id: str,
	*,
	reason: str = "user",
	sessions_dir: Path | None = None,
) -> dict[str, Any]:
	"""写归档 sidecar（重复归档幂等覆盖，刷新时间戳）。"""
	p = archive_sidecar_path(session_id, sessions_dir=sessions_dir)
	entry: dict[str, Any] = {
		"archivedAt": round(time.time() * 1000, 3),
		"reason": str(reason or "user"),
	}
	p.parent.mkdir(parents=True, exist_ok=True)
	tmp = p.with_suffix(".tmp")
	try:
		tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
		os.replace(tmp, p)
	except OSError:
		pass
	return entry


def clear_archive(
	session_id: str, *, sessions_dir: Path | None = None
) -> bool:
	"""清归档 sidecar（恢复）。返回是否实际删除了文件。"""
	p = archive_sidecar_path(session_id, sessions_dir=sessions_dir)
	try:
		p.unlink()
		return True
	except FileNotFoundError:
		return False
	except OSError:
		return False


# ── 可选异步 LLM 增强 ─────────────────────────────────────────────


async def _stream_text(client: _StreamClient, prompt: str) -> tuple[str, str | None]:
	"""收集 1-shot 文本；返回 (text, finish_reason)。"""
	from engine.abort import AbortController

	abort = AbortController()
	text = ""
	finish: str | None = None
	async for chunk in client.stream(
		[
			{
				"role": "user",
				"content": prompt,
			}
		],
		[],
		abort,
	):
		kind = getattr(chunk, "kind", "")
		if kind == "text_delta":
			text += str(getattr(chunk, "text", "") or "")
		fr = getattr(chunk, "finish_reason", None) or getattr(chunk, "finish", None)
		if fr:
			finish = str(fr)
	return text, finish


_TITLE_PROMPT = (
	"为下面的用户首条消息生成一个不超过 16 个字的中文会话标题。"
	"只输出标题本身，不要引号、句号或任何解释。\n\n用户消息：\n"
)


def _audit(kind: str, **fields: Any) -> None:
	try:
		from audit.log import default_audit_log

		default_audit_log().record(kind, **fields)
	except Exception:  # noqa: BLE001
		logging.getLogger(__name__).debug("title audit failed", exc_info=True)


async def enhance_with_model(
	session_id: str,
	first_user_text: str,
	client: _StreamClient,
	*,
	purpose: str = "session-title",
) -> str | None:
	"""旁路 LLM 增强；dispatch 前审计，采纳条件严格（空/非停止/pinned 拒绝）。"""
	existing = read_title(session_id)
	if existing is not None and existing.get("pinned"):
		return None
	_audit(
		"title.enhance",
		session_id=session_id,
		purpose=purpose,
		source_chars=len(str(first_user_text or "")),
	)
	try:
		text, finish = await _stream_text(client, _TITLE_PROMPT + str(first_user_text or ""))
	except Exception:  # noqa: BLE001
		_audit("title.enhance.failed", session_id=session_id, reason="model_error")
		return None
	title = instant_title(text)
	if finish not in ("stop", None) or not title or title == DEFAULT_TITLE:
		_audit("title.enhance.rejected", session_id=session_id, finish=finish)
		return None
	entry = write_title(session_id, title, enhanced=True)
	_audit("title.enhance.applied", session_id=session_id, title=entry["title"])
	return str(entry["title"])


def fire_and_forget_enhance(
	session_id: str,
	first_user_text: str,
	client: _StreamClient,
) -> asyncio.Task[None] | None:
	"""尽力派发后台增强任务；无运行中事件循环时返回 None。"""
	try:
		loop = asyncio.get_running_loop()
	except RuntimeError:
		return None

	async def _run() -> None:
		try:
			await asyncio.wait_for(
				enhance_with_model(session_id, first_user_text, client),
				timeout=20.0,
			)
		except Exception:  # noqa: BLE001
			pass

	return loop.create_task(_run())
