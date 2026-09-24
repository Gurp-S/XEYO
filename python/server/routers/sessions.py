"""Sessions 域路由：会话列表/消息恢复/删除与 rollback 预览执行。"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from common.errors import friendly_error, safe_error_detail
from rewind.locks import LeaseBusyError
from rewind.service import (
    RollbackApprovalError,
    RollbackBlockedError,
    RollbackConflictError,
    RollbackDisabledError,
    RollbackError,
    RollbackIdempotencyError,
    RollbackService,
)
from session.persistence import (
    default_sessions_dir,
    safe_session_filename,
    transcript_path,
)
from session.record_transcript import (
    record_ui_thoughts,
    rotated_transcript_path,
    rotated_transcript_paths,
    transcript_read_paths,
)
from session.transcript_blobs import remove_blobs_dir, resolve_transcript_rows
from server.deps import _MAX_USER_CHARS, _pool, api_error
from server.local_gate import require_loopback

# T33：会话面（含删除/回滚/恢复等破坏性操作）仅 loopback。
router = APIRouter(tags=["sessions"], dependencies=[Depends(require_loopback)])

_logger = logging.getLogger("xeyo.server.sessions")

#: 会话 / 子 agent 身份的合法字符集。``session.persistence.safe_session_filename``
#: 会把 ':' 写成 '__'、把其余非法字符写成 '_'、再剥掉首尾 '._'——于是
#: ``"victim "`` 与 ``"victim"``、``".."`` 与 ``"  "`` 与 ``"."`` 全部落到同一个
#: 磁盘文件名。读错会话 / 改错标题 / 删错数据都只需要一次带空白或点号的 id。
#: 身份有歧义一律在边缘 422，绝不静默清洗后继续执行。
_ID_ALLOWED_RE = re.compile(r"[A-Za-z0-9._:\-]+\Z")
_MAX_ID_CHARS = 128


def _require_stable_id(
	raw: Any, *, field: str, filename_bearing: bool = False
) -> str:
	"""校验身份键并**原样**返回；一切歧义形态 422（不清洗、不裁剪、不替换）。"""
	value = "" if raw is None else str(raw)
	if not value.strip():
		raise api_error(422, f"{field} is blank", "invalid_request")
	if value != value.strip():
		raise api_error(
			422,
			f"{field} has leading or trailing whitespace",
			"invalid_request",
		)
	if len(value) > _MAX_ID_CHARS:
		raise api_error(
			422, f"{field} exceeds {_MAX_ID_CHARS} characters", "invalid_request"
		)
	if not _ID_ALLOWED_RE.match(value):
		raise api_error(
			422,
			f"{field} contains characters outside [A-Za-z0-9._:-]",
			"invalid_request",
		)
	if safe_session_filename(value) == "session" and value != "session":
		# "." / ".." / ":" / "__" 一类：文件名归一化后会 collapse 成 session.*。
		raise api_error(
			422,
			f"{field} has no identity-bearing characters",
			"invalid_request",
		)
	if filename_bearing and safe_session_filename(value) != value:
		# 会落到别人文件名上的写法：``victim.`` 与 ``victim``、``vi:ctim`` 与
		# ``vi__ctim`` 在磁盘上是同一个会话——读错 / 改错 / 删错都不需要第二次请求。
		raise api_error(
			422,
			f"{field} would collide with another id on disk",
			"invalid_request",
		)
	return value


def require_session_id(raw: Any) -> str:
	"""会话 id 边缘校验。当前只有本模块在用：jobs / goals / control / rewind
	 尚未接入（它们现在也不按会话 id 拼路径），别把这句话当成"那边也有守卫"。"""
	return _require_stable_id(raw, field="session_id", filename_bearing=True)


def require_agent_id(raw: Any) -> str:
	return _require_stable_id(raw, field="agent_id", filename_bearing=True)


class _KeyedLocks:
	"""按 key 取的全局锁表：同一资源的读-改-写串行，不同资源不互斥。

	子 agent meta（``pending_followups``）是「读文件 → 改列表 → 整表写回」，
	两个并发请求会各自读到同一份旧表、后写的把先写的静默覆盖掉。
	"""

	def __init__(self) -> None:
		self._lock = threading.Lock()
		self._keys: dict[str, threading.Lock] = {}

	def acquire(self, key: str) -> threading.Lock:
		with self._lock:
			handle = self._keys.get(key)
			if handle is None:
				handle = threading.Lock()
				self._keys[key] = handle
			return handle


_meta_locks = _KeyedLocks()


class NewSessionRequest(BaseModel):
	"""创建新会话：客户端只发 workspace（id 或路径），服务端解析权威路径。"""

	workspace: str | None = Field(default=None, max_length=1024)


@router.post("/v1/sessions")
def create_session(body: NewSessionRequest | None = None) -> dict[str, Any]:
	"""T31：服务端签发新会话 id（消灭客户端自造 UUID）。

	workspace 由服务端权威解析（resolve_workspace：id → 注册路径；否则按路径）。
	不在此创建 engine——首个 chat 请求的 get_or_create 才真正钉死 cwd。
	"""
	sid = f"xeyo-{uuid.uuid4().hex[:12]}"
	cwd = _pool.cwd or ""
	if body is not None and (body.workspace or "").strip():
		try:
			cwd = _pool.resolve_workspace(body.workspace)
		except (FileNotFoundError, NotADirectoryError, ValueError) as e:
			raise api_error(400, str(e)) from e
	return {"ok": True, "session_id": sid, "cwd": cwd}

class RuntimeModeRequest(BaseModel):
	"""运行时审批模式覆盖（轮次进行中 GUI 切换写活值）。"""

	permission_mode: str


@router.post("/v1/sessions/{session_id}/runtime-mode")
def set_session_runtime_mode(
	session_id: str,
	body: RuntimeModeRequest,
) -> dict[str, Any]:
	"""写活审批模式到会话 RuntimeModeStore（立即生效，不必等下一轮）。

　读取优先级：store 活值 > 请求 body 显式 > config 默认。写后当前回合内
　尚未执行的下一工具调用即按新模式判定（收紧即时；放宽经 T26 单向性延后
　到下一 turn）。非法模式值回 400、不写入。
　"""
	sid = require_session_id(session_id)
	from permissions.runtime_mode import get_runtime_mode_store

	store = get_runtime_mode_store()
	normalized = store.set(sid, body.permission_mode)
	if normalized is None:
		raise api_error(
			400,
			"permission_mode must be one of: always / risk / never",
			"invalid_request",
		)
	eff = store.effective(sid)
	return {
		"ok": True,
		"session_id": sid,
		"permission_mode": normalized,
		"effective": eff or normalized,
	}


class RuntimePresetRequest(BaseModel):
	"""运行时会话权限 preset 覆盖（smoke-test #6：会话内实时切换）。"""

	permission_preset: str


@router.get("/v1/sessions/{session_id}/runtime-preset")
def get_session_runtime_preset(session_id: str) -> dict[str, Any]:
	"""读取会话的运行时权限 preset 活值（未显式切换为 null）。"""
	sid = require_session_id(session_id)
	from permissions.runtime_preset import get_runtime_preset_store

	live = get_runtime_preset_store().live(sid)
	return {"ok": True, "session_id": sid, "permission_preset": live}


@router.post("/v1/sessions/{session_id}/runtime-preset")
def set_session_runtime_preset(
	session_id: str,
	body: RuntimePresetRequest,
) -> dict[str, Any]:
	"""写活会话权限 preset（readonly / workspace-write / full）。

	smoke-test #6：会话创建时 pin 的 preset 只是默认值;用户显式切换后,
	``permissions.policy.session_permission_profile`` 优先读本活值 ——
	后续轮次/工具调用立即按新 preset 判定（收紧/放宽都即时,不溯及已执行轮）。
	非法值回 400、不写入。
	"""
	sid = require_session_id(session_id)
	from permissions.presets import PERMISSION_PRESETS
	from permissions.runtime_preset import get_runtime_preset_store

	store = get_runtime_preset_store()
	normalized = store.set(sid, body.permission_preset)
	if normalized is None or normalized not in PERMISSION_PRESETS:
		raise api_error(
			400,
			"permission_preset must be one of: readonly / workspace-write / full",
			"invalid_request",
		)
	return {
		"ok": True,
		"session_id": sid,
		"permission_preset": normalized,
	}

class RollbackPreviewRequest(BaseModel):
	target_message_id: str = Field(min_length=1, max_length=256)
	edited_text: str = Field(min_length=1, max_length=_MAX_USER_CHARS)
	ttl_seconds: float | None = Field(default=None, ge=30, le=3600)


class RollbackExecuteRequest(BaseModel):
	plan_id: str = Field(min_length=1, max_length=256)
	plan_hash: str = Field(min_length=1, max_length=256)
	idempotency_key: str = Field(min_length=1, max_length=256)
	confirmed: bool = False
	expected_workspace_revision: str | None = None
	# 默认关：只恢复 agent 触碰过的文件。可显式开启恢复整棵 shadow-git 树。
	full_tree_restore: bool | None = None
	# None = 跟随 plan.metadata.restores_workspace；False = 仅聊天转录。
	restore_workspace: bool | None = None
	# Rewind v2：transcript_committed 后即返回；工作区在后台完成。
	async_workspace: bool | None = None


class RollbackRecoveryRequest(BaseModel):
	action: Literal["retry_checkpoint", "abandon"]


class UiThoughtItem(BaseModel):
	id: str = Field(min_length=1, max_length=256)
	text: str = Field(min_length=1)
	thought_ms: int | None = Field(default=None, ge=0)
	ts: float | None = None


class UiThoughtsSyncRequest(BaseModel):
	thoughts: list[UiThoughtItem] = Field(default_factory=list, max_length=500)


@router.delete("/v1/sessions/{session_id}")
@router.post("/v1/sessions/{session_id}/delete")
def delete_session(session_id: str) -> dict[str, Any]:
	"""丢弃 FE 已删除聊天的内存 engine（#7），并清理磁盘 transcript 与会话目录。

	归档门槛（2026-09-05）：常态会话一律拒绝删除——必须先归档再删，
	删除是不可逆破坏性操作，归档作为缓冲层（防误删单点）。
	"""
	sid = require_session_id(session_id)
	from engine.title import read_archive

	root0 = default_sessions_dir()
	if read_archive(sid, sessions_dir=root0) is None:
		raise api_error(
			409,
			"会话尚未归档：请先归档，再从已归档列表中删除",
			"archived_required",
		)
	dropped = _pool.drop(sid)
	removed: list[str] = []
	removal_errors: list[dict[str, str]] = []

	# 磁盘 transcript（当前 + 全部轮转归档 .old1/.old2）：不删的话重启后
	# list_sessions 会把已删除会话重新导入；只删 .old1 会把 .old2 的对话原文
	# 留在「已删除」会话名下（用户要的删除是隐私动作，不是改名）。
	root = default_sessions_dir()
	tp = transcript_path(sid, sessions_dir=root)
	targets = [tp, *rotated_transcript_paths(tp)]
	for f in targets:
		try:
			if f.is_file():
				f.unlink()
				removed.append(str(f))
		except OSError as exc:
			removal_errors.append({"path": str(f), "error": safe_error_detail(exc)})
	try:
		remove_blobs_dir(tp)
	except OSError as exc:  # remove_blobs_dir 内部 ignore_errors，这里只兜意外
		removal_errors.append({"path": str(tp) + ".blobs", "error": safe_error_detail(exc)})
	# 归档 sidecar 一并清理（删除即彻底移除，不留孤儿标记）。
	ap = root / f"{safe_session_filename(sid)}.archive.json"
	try:
		if ap.is_file():
			ap.unlink()
			removed.append(str(ap))
	except OSError as exc:
		removal_errors.append({"path": str(ap), "error": safe_error_detail(exc)})

	# 会话子目录（rewind revisions/journal、rollback plans/approvals、recovery jobs）。
	sdir = root / safe_session_filename(sid)
	if sdir.is_dir():
		try:
			shutil.rmtree(sdir)
			removed.append(str(sdir))
		except OSError as exc:
			removal_errors.append({"path": str(sdir), "error": safe_error_detail(exc)})

	# 会话索引白名单同步移除，避免残留索引在下次重启时重新导入。
	index_file = Path(__file__).resolve().parent.parent.parent / ".xeyo_session_index.json"
	try:
		if index_file.exists():
			idx = json.loads(index_file.read_text(encoding="utf-8"))
			ids = idx.get("ids")
			if isinstance(ids, list):
				clean = [x for x in ids if str(x) != sid]
				if len(clean) != len(ids):
					idx["ids"] = clean
					index_file.write_text(
						json.dumps(idx, ensure_ascii=False, indent=2) + "\n",
						encoding="utf-8",
					)
	except Exception as exc:  # noqa: BLE001 — 白名单没清 ⇒ 重启会重新导入，必须留痕
		_logger.warning("session index cleanup failed sid=%s", sid, exc_info=True)
		removal_errors.append({"path": str(index_file), "error": safe_error_detail(exc)})

	# 活审批模式（RuntimeModeStore）按会话清理，防残留。
	try:
		from permissions.runtime_mode import get_runtime_mode_store

		get_runtime_mode_store().clear(sid)
	except Exception:  # noqa: BLE001 — 内存态清理失败不影响删除结果，留痕即可
		_logger.debug("runtime mode cleanup failed sid=%s", sid, exc_info=True)

	# 运行时权限 preset 活值同样按会话清理（smoke-test #6）。
	try:
		from permissions.runtime_preset import get_runtime_preset_store

		get_runtime_preset_store().clear(sid)
	except Exception:  # noqa: BLE001 — 内存态清理失败不影响删除结果，留痕即可
		_logger.debug("runtime preset cleanup failed sid=%s", sid, exc_info=True)

	# 删除动作的完成定义是「磁盘上不再有这个会话」。任何一件没删掉都必须说：
	# 否则前端把卡片摘了，下次重启 list_sessions 又把残留 transcript 导回来，
	# 用户看到「删掉的会话复活」——静默失败比报错贵得多。
	survivors: list[str] = []
	for f in (tp, *rotated_transcript_paths(tp)):
		if f.is_file():
			survivors.append(str(f))
	if survivors:
		_logger.error(
			"delete incomplete sid=%s survivors=%s errors=%s", sid, survivors, removal_errors
		)
		raise api_error(
			500,
			"session transcript could not be removed: " + "; ".join(survivors),
			"delete_incomplete",
		)
	return {
		"ok": True,
		"dropped": dropped,
		"removed": removed,
		"removal_errors": removal_errors,
	}


# (path) -> ((mtime_ns, size), title, created_at_ms)：文件未变时直接复用标题。
_session_meta_cache: dict[str, tuple[tuple[int, int], str, int]] = {}


def _scan_session_meta(p: Path) -> tuple[str, int]:
	"""读 transcript 找标题（首条 user 消息）与创建时间；带 (mtime,size) 缓存。

	轮转后首条 user 消息可能在 .old 归档里，先扫归档再扫当前文件。
	"""
	try:
		st = p.stat()
	except OSError:
		return p.stem, 0
	key = str(p)
	sig = (st.st_mtime_ns, st.st_size)
	cached = _session_meta_cache.get(key)
	if cached is not None and cached[0] == sig:
		return cached[1], cached[2]
	title = p.stem
	created_at = int(st.st_ctime * 1000)
	found_ts = False
	found_user = False
	for f in transcript_read_paths(p):
		try:
			with f.open("r", encoding="utf-8") as fh:
				for line in fh:
					line = line.strip()
					if not line:
						continue
					try:
						obj = json.loads(line)
					except Exception:
						continue
					if not found_ts:
						ts = obj.get("ts")
						if isinstance(ts, (int, float)):
							created_at = int(float(ts) * 1000)
							found_ts = True
					if obj.get("role") == "user" and not str(
						obj.get("note_key") or ""
					).strip():
						# 通报留痕也是 role=user（world_state 片段）：拿它当"第一句
						# 用户话"就会把引擎文本写成会话标题。
						content = obj.get("content")
						if isinstance(content, str) and content.strip():
							title = content.strip()[:40]
						found_user = True
						break
		except Exception:
			continue
		if found_user:
			break
	if len(_session_meta_cache) > 1024:
		_session_meta_cache.clear()
	_session_meta_cache[key] = (sig, title, created_at)
	return title, created_at


@router.get("/v1/sessions")
def list_sessions() -> dict[str, Any]:
	"""列出磁盘上的会话 transcript，供前端在本地索引缺失时恢复历史（#历史回归）。

	若存在会话索引文件（python/.xeyo_session_index.json 的 {"ids": [...]}），
	则只返回这些用户会话，避免把开发测试产生的 transcript 一并导入。
	标题/创建时间按 (mtime,size) 缓存，文件未变时不重复读盘。
	"""
	root = default_sessions_dir()
	index_file = Path(__file__).resolve().parent.parent.parent / ".xeyo_session_index.json"
	# 白名单守护的是默认 ~/.xeyo/sessions 里的「真实用户会话」；会话目录被
	# XEYO_SESSIONS_DIR 隔离（e2e / pytest 临时目录）时不套用它——否则隔离
	# 目录里新建的 sess_* 会被过滤出 /v1/sessions，前端侧栏与测试都看不到。
	sessions_isolated = bool(os.environ.get("XEYO_SESSIONS_DIR", "").strip())
	whitelist: set[str] | None = None
	if not sessions_isolated:
		try:
			if index_file.exists():
				idx = json.loads(index_file.read_text(encoding="utf-8"))
				ids = idx.get("ids")
				if isinstance(ids, list):
					whitelist = {str(x) for x in ids if x}
		except Exception:
			whitelist = None
	out: list[dict[str, Any]] = []
	if not root.exists():
		return {"sessions": out}
	entries: list[tuple[Path, os.stat_result]] = []
	for p in root.glob("*.jsonl"):
		try:
			st = p.stat()
		except OSError:
			continue
		entries.append((p, st))
	entries.sort(key=lambda t: t[1].st_mtime, reverse=True)
	for p, st in entries:
		sid = p.stem
		# 侧聊（side-）transcript 归侧聊面板管，不进主会话恢复列表。
		if sid.startswith("side-"):
			continue
		# 内部索引/工作区归属文件（_workspace_index 等）以 _ 开头，永远
		# 不该出现在用户可见会话列表里（白名单守护的是默认 ~/.xeyo/
		# sessions 真实用户会话；e2e / pytest 隔离目录走 XEYO_SESSIONS_DIR
		# 不套用白名单，若不显式过滤 _workspace_index.jsonl 会被 list 当
		# session 返回，污染前端 hydrate.importServerSessions 的 activeId）。
		if sid.startswith("_"):
			continue
		if whitelist is not None and sid not in whitelist:
			continue
		title, created_at = _scan_session_meta(p)
		# T5：标题 sidecar（pinned/enhanced）优先于首条消息切片。
		try:
			from engine.title import read_title

			sc = read_title(sid)
			if sc:
				title = str(sc.get("title") or title)
		except Exception:
			pass
		# smoke-test #3：归档标记 sidecar，前端用来过滤默认列表 vs 归档视图。
		archive_state: dict[str, float | None] = {}
		try:
			from engine.title import read_archive

			ar = read_archive(sid)
			archive_state["archivedAt"] = float(ar["archivedAt"]) if ar else None
		except Exception:
			pass
		out.append({
			"id": sid,
			"title": title,
			"createdAt": created_at,
			"updatedAt": int(st.st_mtime * 1000),
			**archive_state,
		})
	return {"sessions": out}


@router.get("/v1/workspaces/sessions")
def list_workspace_sessions(
	cwd: str = Query(default="", max_length=1024),
) -> dict[str, Any]:
	"""列出归属指定工作区路径的会话（ws_index 归属映射 + transcript 元数据）。

	前端「移除工作区」会把其下会话迁往默认分区（不删除）；重开同一
	文件夹时前端调本端点把归属会话重新挂回工作区（adoptWorkspaceSessions）。
	"""
	from session.ws_index import sessions_for_workspace

	if not cwd.strip():
		return {"sessions": []}
	try:
		ids = {sid for sid in sessions_for_workspace(cwd) if sid}
	except Exception:  # noqa: BLE001 — 归属索引任何失败都降级为空列表
		return {"sessions": []}
	if not ids:
		return {"sessions": []}
	root = default_sessions_dir()
	out: list[dict[str, Any]] = []
	try:
		entries = sorted(
			root.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
		)
	except OSError:
		return {"sessions": []}
	for p in entries:
		sid = p.stem
		# 侧聊（side-）归侧聊面板管；_workspace_index 等内部文件不在归属集合里。
		if sid.startswith("side-") or sid not in ids:
			continue
		title, created_at = _scan_session_meta(p)
		try:
			from engine.title import read_title

			sc = read_title(sid)
			if sc:
				title = str(sc.get("title") or title)
		except Exception:  # noqa: BLE001
			pass
		try:
			updated_at = int(p.stat().st_mtime * 1000)
		except OSError:
			continue
		archive_state: dict[str, float | None] = {}
		try:
			from engine.title import read_archive

			archive = read_archive(sid)
			archive_state["archivedAt"] = (
				float(archive["archivedAt"]) if archive else None
			)
		except Exception:  # noqa: BLE001 — archive sidecar failure does not block workspace listing
			pass
		out.append({
			"id": sid,
			"title": title,
			"createdAt": created_at,
			"updatedAt": updated_at,
			**archive_state,
		})
	return {"sessions": out}


class RenameRequest(BaseModel):
	title: str


@router.post("/v1/sessions/{session_id}/rename")
def rename_session(session_id: str, body: RenameRequest) -> dict[str, Any]:
	"""T5：用户显式改名——写 pinned sidecar，永不被自动标题覆盖。

	边缘校验两件事：① 身份（``"victim "`` 会被文件名归一化成 ``victim``，等于给
	别人的会话改名）；② 落盘结果（``engine.title.write_title`` 对 OSError 是
	「返回内存里的 entry、不抛异常」，只看返回值会把没写进去的标题当成改成功）。
	"""
	from engine.title import read_title, write_title

	sid = require_session_id(session_id)
	title = str(body.title or "").strip()
	if not title:
		raise api_error(400, "title must not be empty", "invalid_request")
	if len(title) > 200:
		raise api_error(422, "title exceeds 200 characters", "invalid_request")
	try:
		entry = write_title(sid, title, pinned=True)
	except Exception as e:  # noqa: BLE001
		raise api_error(500, friendly_error(e), "server_error") from e
	persisted = read_title(sid)
	if not persisted or str(persisted.get("title") or "") != str(entry.get("title") or ""):
		_logger.warning(
			"rename not persisted for session=%s (wanted=%r got=%r)",
			sid,
			entry.get("title"),
			(persisted or {}).get("title"),
		)
		raise api_error(
			500,
			"title sidecar could not be persisted; rename did not take effect",
			"server_error",
		)
	return {"id": sid, "title": persisted["title"], "pinned": bool(persisted.get("pinned"))}



class ForkRequest(BaseModel):
	reason: str | None = Field(default=None, max_length=128)


@router.post("/v1/sessions/{session_id}/fork")
def fork_session(session_id: str, body: ForkRequest | None = None) -> dict[str, Any]:
	"""smoke-test #3：分叉会话——复制 transcript + title sidecar 到新 sid。

	新 sid 服务端签发；workspace 沿用原会话的 cwd；engine 不预创建（首条 chat 才真正钉死）。
	侧聊（side-）前缀的会话不允许 fork（与主面板语义不一致）；后端会 400。
	"""
	from engine.title import read_title, write_title

	sid = require_session_id(session_id)
	if sid.startswith("side-"):
		raise api_error(400, "side-chat sessions cannot be forked", "side_chat_unsupported")
	root = default_sessions_dir()
	src_tp = transcript_path(sid, sessions_dir=root)
	src_archives = [p for p in rotated_transcript_paths(src_tp) if p.is_file()]
	if not src_tp.is_file() and not src_archives:
		raise api_error(404, "source session has no transcript", "source_missing")

	new_sid = f"xeyo-{uuid.uuid4().hex[:12]}"
	dst_tp = transcript_path(new_sid, sessions_dir=root)
	dst_tp.parent.mkdir(parents=True, exist_ok=True)

	# 复制 current transcript 与**全部**轮转归档（.old1/.old2，顺序保留）。
	# 早先只带 .old1：轮转一旦开始，fork 出来的会话会静默丢掉最老一代历史。
	copied: list[str] = []
	warnings: list[str] = []
	if src_tp.is_file():
		try:
			shutil.copy2(src_tp, dst_tp)
			copied.append(str(dst_tp))
		except OSError as e:
			raise api_error(
				500, safe_error_detail(e, fallback="copy transcript failed"), "server_error"
			) from e
	for src_old in src_archives:
		dst_old = dst_tp.with_name(dst_tp.name + src_old.name[len(src_tp.name) :])
		try:
			shutil.copy2(src_old, dst_old)
			copied.append(str(dst_old))
		except OSError as e:
			# 归档复制失败不影响主 fork，但必须说出口：分叉体少了历史。
			warnings.append(f"old-copy-failed: {safe_error_detail(e)}")

	# 复制 title sidecar（如有）并加 (分叉) 标签，避免直接覆盖原 pinned。
	src_title = read_title(sid, sessions_dir=root)
	fork_title = (src_title["title"] + " (分叉)") if src_title else "新对话 (分叉)"
	try:
		write_title(new_sid, fork_title, pinned=True, sessions_dir=root)
	except Exception:  # noqa: BLE001 — 标题失败回落即时推导，fork 本体已成功
		_logger.debug("fork title copy failed sid=%s", sid, exc_info=True)

	# 索引白名单同步加入新 sid（与 create_session 行为一致）。
	index_file = Path(__file__).resolve().parent.parent.parent / ".xeyo_session_index.json"
	try:
		if index_file.exists():
			idx = json.loads(index_file.read_text(encoding="utf-8"))
			ids = idx.get("ids")
			if isinstance(ids, list) and new_sid not in ids:
				ids.append(new_sid)
				index_file.write_text(
					json.dumps(idx, ensure_ascii=False, indent=2) + "\n",
					encoding="utf-8",
				)
	except Exception as exc:  # noqa: BLE001 — 白名单没写进去 ⇒ 重启后 fork 体消失，必须留痕
		_logger.warning("fork index update failed sid=%s", new_sid, exc_info=True)
		warnings.append(f"index-update-failed: {safe_error_detail(exc)}")

	cwd = _pool.session_cwd(sid) or _pool.cwd or ""
	return {
		"ok": True,
		"source_id": sid,
		"new_id": new_sid,
		"title": fork_title,
		"cwd": cwd,
		"copied": copied,
		"warnings": warnings,
	}


@router.post("/v1/sessions/{session_id}/archive")
def archive_session(session_id: str) -> dict[str, Any]:
	"""smoke-test #3：归档会话——仅写 archive sidecar，不删 transcript。

	可恢复：list_sessions 过滤 archived；restore_session 清 sidecar。
	"""
	from engine.title import write_archive

	sid = require_session_id(session_id)
	root = default_sessions_dir()
	# 没有 transcript 的会话也允许归档（占位）
	entry = write_archive(sid, sessions_dir=root)
	return {"ok": True, "id": sid, "archivedAt": entry["archivedAt"], "reason": entry["reason"]}


@router.post("/v1/sessions/{session_id}/restore")
def restore_session(session_id: str) -> dict[str, Any]:
	"""smoke-test #3：找回已归档会话——删 archive sidecar。"""
	from engine.title import clear_archive

	sid = require_session_id(session_id)
	removed = clear_archive(sid)
	return {"ok": True, "id": sid, "restored": removed}


@router.get("/v1/sessions/{session_id}/messages", response_model=None)
async def session_messages(session_id: str, include_notes: bool = False):
	"""按精确 session_id 读取 transcript 消息（不套 side- 前缀），供前端恢复本地历史。

	跨轮转归档（.old2 → .old1 → 当前）按时间顺序合并读取。
	工具行与 list 形 assistant 块通过 ``_side_row_to_ui`` 展开为前端 ChatMessage 形状。
	``include_notes=True``：连 T_now 留痕条目（hidden system note）一起返回——
	供调试与用户自查（默认过滤：它们是引擎状态，不是对话内容）。

	诚实性（2026-09-25 加固）：
	- 一个文件都读不到 ⇒ 404 ``transcript_not_found``。此前对不存在的会话返回
	  ``200 messages: []``，客户端无法区分「空会话」与「查无此会话」。
	- 单个归档文件读失败（权限 / 编码 / 中途断开）不再 ``except: continue`` 静默
	  丢掉整个文件的历史：失败进 ``read_errors``、坏行进 ``skipped_lines``，并置
	  ``degraded: true``——半截历史必须自称半截。
	"""
	sid = require_session_id(session_id)
	raw_rows: list[dict[str, Any]] = []
	p = transcript_path(sid)
	read_errors: list[dict[str, str]] = []
	skipped_lines = 0
	found = False
	for f in transcript_read_paths(p):
		try:
			if not f.is_file():
				continue
		except OSError as exc:
			read_errors.append({"path": str(f), "error": safe_error_detail(exc)})
			continue
		found = True
		try:
			with f.open("r", encoding="utf-8") as fh:
				for line in fh:
					line = line.strip()
					if not line:
						continue
					try:
						row = json.loads(line)
					except Exception:  # noqa: BLE001 — 坏行容忍，但必须计数
						skipped_lines += 1
						continue
					if isinstance(row, dict):
						raw_rows.append(row)
		except (OSError, UnicodeDecodeError) as exc:
			# 整个文件（含其后所有行）丢了：半截历史必须自称半截。
			read_errors.append({"path": str(f), "error": safe_error_detail(exc)})
			continue
	if not found and _pool.get_if_present(sid) is None:
		raise api_error(
			404,
			f"no transcript for session: {sid}",
			"transcript_not_found",
		)

	messages: list[dict[str, Any]] = []
	pending_calls: deque[dict[str, Any]] = deque()
	# replace 事件化回溯：模型可见面 = fold 后的行（旧日志无 marker 时恒等）。
	from session.surface import fold_surface_rows

	surface_rows = resolve_transcript_rows(fold_surface_rows(raw_rows), p)
	# T_now v2 留痕条目（引擎注入，模型可见 / 用户不可见）：两种形态都算——
	# system 声道写 role=system，通报片段声道写带信封的 role=user。身份只看
	# note_key，缺 kind/fp 也照样过滤；默认不进 UI 流（``include_notes=1`` 显式取出）。
	if not include_notes:
		surface_rows = [
			r for r in surface_rows if not str(r.get("note_key") or "").strip()
		]
	# 去重集必须先整表预扫：ui_thought 行由前端 debounce 批量落盘，位置可能不在所属轮次之后。
	persisted_thoughts = _persisted_thought_keys(surface_rows)
	for i, row in enumerate(surface_rows):
		messages.extend(
			_side_row_to_ui(row, i, pending_calls, persisted_thoughts=persisted_thoughts)
		)
	# T31：随消息返回服务端权威 cwd（供 tui 等薄客户端恢复会话时不自定工作区）。
	return {
		"session_id": sid,
		"messages": messages,
		"cwd": _pool.session_cwd(sid) or _pool.cwd or "",
		"transcript_found": found,
		"degraded": bool(read_errors),
		"read_errors": read_errors,
		"skipped_lines": skipped_lines,
	}


def _thought_key(text: Any) -> str:
	"""Thought 去重键：折叠全部空白后的全文；空白差异不该算两条。

	assistant 行内的 reasoning 块与前端 debounce 补写的 ``ui_thought`` 行描述同一段思考，
	文本只可能差首尾/换行空白，因此用折叠后的全文当键。
	"""
	return " ".join(str(text or "").split())


def _persisted_thought_keys(rows: list[dict[str, Any]]) -> set[str]:
	"""预扫 transcript 里既有的 ``ui_thought`` 行文本，作为投影去重的「已落盘」集合。

	``ui_thought`` 是前端补写的 UI-only 行（``record_ui_thoughts``），额外携带前端测量的
	思考耗时（``thought_ms``）。它与 assistant 行内的 reasoning 块同源，因此同文本时保留前者。
	必须在投影前整表预扫：``ui_thought`` 行由 debounce 批量落盘，位置可能远离所属轮次。
	"""
	keys: set[str] = set()
	for row in rows:
		if not isinstance(row, dict) or str(row.get("role") or "") != "ui_thought":
			continue
		content = row.get("content")
		if isinstance(content, str):
			key = _thought_key(content)
			if key:
				keys.add(key)
	return keys


def _side_row_to_ui(
	row: dict[str, Any],
	idx: int,
	pending_calls: deque[dict[str, Any]],
	*,
	persisted_thoughts: set[str] | None = None,
) -> list[dict[str, Any]]:
    """把侧链 transcript 行（Message dict）展开为前端 ChatMessage 形状。

    与主会话恢复接口保持一致的渲染语义：
    - user：进 text（list 块拆出图片引用）；
    - assistant：str 直接用；list 块按顺序拆出 reasoning（思考→``isThought`` 行）、
      text（正文段落），并把 ``tool_use`` 块压入 pending 队列 —— 它们的输入参数要配对到
      随后的 tool 结果行；
    - tool：content 是块列表（tool_result + 可选 image_url）；按名字/FIFO 配对
      到最近一个未消费的 tool_use，输出「合并单行」：toolName/toolInput/text。
    返回 0..n 行；空返回表示该行无可渲染内容。

    ``persisted_thoughts`` 传入已落盘 ``ui_thought`` 行的文本键，命中则不重复投影该块
    （见 ``_persisted_thought_keys``）。
    """
    role = str(row.get("role") or "")
    content = row.get("content")
    ts = row.get("ts")
    created = int(float(ts) * 1000) if isinstance(ts, (int, float)) else idx
    mid = str(row.get("id") or f"m{idx}")
    msg_name = str(row.get("name") or "")

    if role == "user":
        text_parts: list[str] = []
        media: list[str] = []
        if isinstance(content, str):
            if content.strip():
                text_parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    if text_parts:
                        text_parts.append("\n")
                    text_parts.append(block["text"])
                elif block.get("type") == "image_url":
                    iu = block.get("image_url")
                    url = iu.get("url") if isinstance(iu, dict) else None
                    if isinstance(url, str) and url.strip():
                        media.append(url)
        text = "".join(text_parts)
        if not text.strip() and not media:
            return []
        out: dict[str, Any] = {"id": mid, "role": "user", "text": text, "createdAt": created}
        if media:
            out["mediaRefs"] = media
        return [out]

    if role == "assistant":
        # str：纯文本回复，直接一行。
        if isinstance(content, str):
            if not content.strip():
                return []
            return [{"id": mid, "role": "assistant", "text": content, "createdAt": created}]
        # list：按块顺序拆 reasoning（思考）+ text（正文），并把 tool_use 参数入队等待结果行配对。
        # 顺序与实时渲染一致：Thought 在正文之前；tool 行由后续独立行补齐。
        out_rows: list[dict[str, Any]] = []
        texts: list[str] = []
        if isinstance(content, list):
            known = persisted_thoughts or set()
            for k, block in enumerate(content):
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "reasoning":
                    rtext = block.get("text")
                    if not isinstance(rtext, str) or not rtext.strip():
                        continue
                    key = _thought_key(rtext)
                    if key and key in known:
                        # 已有前端补写的 ui_thought 行（还带着思考耗时）⇒ 不重复投影。
                        continue
                    out_rows.append({
                        # 确定性派生 id：不与 ui_thought 行的前端 id 冲突，也不与正文行同 id。
                        "id": f"{mid}#r{k}",
                        "role": "assistant",
                        "text": rtext.strip(),
                        "isThought": True,
                        "createdAt": created,
                    })
                elif btype == "text" and isinstance(block.get("text"), str) and block["text"].strip():
                    if texts:
                        texts.append("\n")
                    texts.append(block["text"])
                elif btype == "tool_use":
                    pending_calls.append({
                        "id": str(block.get("id") or ""),
                        "name": str(block.get("name") or ""),
                        "input": block.get("input"),
                        "ts": created,
                    })
        text = "".join(texts)
        if text.strip():
            out_rows.append({"id": mid, "role": "assistant", "text": text, "createdAt": created})
        # 纯思考轮（无 text / 无 tool_use）也返回 Thought 行：历史 text-only 轮的思考态
        # 只能从这里恢复，否则刷新后该轮的 Thinking 归零。
        return out_rows

    if role == "tool":
        result_text = ""
        is_error = False
        media_urls: list[str] = []
        tool_use_id = str(row.get("tool_call_id") or "").strip()
        if isinstance(content, str):
            result_text = content
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "tool_result":
                    inner = block.get("content")
                    if isinstance(inner, str):
                        result_text = inner
                    elif isinstance(inner, list):
                        parts: list[str] = []
                        for sub in inner:
                            if (
                                isinstance(sub, dict)
                                and sub.get("type") == "text"
                                and isinstance(sub.get("text"), str)
                            ):
                                parts.append(sub["text"])
                        result_text = "".join(parts)
                    is_error = bool(block.get("is_error"))
                elif btype == "image_url":
                    iu = block.get("image_url")
                    url = iu.get("url") if isinstance(iu, dict) else None
                    if isinstance(url, str) and url.strip():
                        media_urls.append(url)

        # 配对 tool_use：先按结果自带的 id 精确配（并行批次里结果乱序回写时，
        # 队头/FIFO 都会把参数张冠李戴），其次同名，最后 FIFO 兜底。
        if not tool_use_id and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and str(block.get("tool_use_id") or "").strip():
                    tool_use_id = str(block["tool_use_id"]).strip()
                    break
        call: dict[str, Any] | None = None
        if tool_use_id:
            for i, pend in enumerate(pending_calls):
                if str(pend.get("id") or "") == tool_use_id:
                    call = pend
                    del pending_calls[i]
                    break
        if call is None:
            for i, pend in enumerate(pending_calls):
                if (pend.get("name") or "") == msg_name:
                    call = pend
                    del pending_calls[i]
                    break
        if call is None and pending_calls:
            call = pending_calls.popleft()
        try:
            call_input = (
                json.dumps(call.get("input"), ensure_ascii=False)
                if call is not None and call.get("input") is not None
                else ""
            )
        except Exception:
            call_input = ""
        tool_name = msg_name or (call or {}).get("name") or "tool"

        out_tool: dict[str, Any] = {
            "id": mid,
            "role": "tool",
            "toolName": tool_name,
            "toolInput": call_input,
            "text": result_text,
            "toolStatus": ("error" if (is_error or result_text.startswith("[error]")) else "done"),
            "createdAt": created,
        }
        # 前端按 toolUseId 精确结算「仍在运行/等待批准」的工具卡（mergeToolResultsFromServer）；
        # 缺这个键时该分支恒不命中，重开会话后工具卡永久停在运行中。
        paired_id = tool_use_id or str((call or {}).get("id") or "")
        if paired_id:
            out_tool["toolUseId"] = paired_id
        if media_urls:
            out_tool["mediaRefs"] = media_urls
        return [out_tool]

    if role == "ui_thought":
        text = content if isinstance(content, str) else ""
        if not text.strip():
            return []
        out_thought: dict[str, Any] = {
            "id": mid,
            "role": "assistant",
            "text": text.strip(),
            "isThought": True,
            "createdAt": created,
        }
        thought_ms = row.get("thought_ms")
        if isinstance(thought_ms, (int, float)):
            out_thought["thoughtMs"] = int(thought_ms)
        return [out_thought]

    return []


@router.post("/v1/sessions/{session_id}/ui-thoughts")
async def sync_ui_thoughts(
    session_id: str,
    body: UiThoughtsSyncRequest,
) -> dict[str, Any]:
    """持久化前端 reasoning 块（ui_thought 行），供刷新后恢复 Activity 中的 Thought。"""
    sid = require_session_id(session_id)
    rows = [
        {
            "id": t.id,
            "text": t.text,
            "thought_ms": t.thought_ms,
            "ts": t.ts,
        }
        for t in body.thoughts
    ]
    known_ids = _pool.transcript_known_ids(sid)
    written = await record_ui_thoughts(
        rows,
        session_id=sid,
        known_ids=known_ids,
    )
    return {"ok": True, "written": written}


@router.get("/v1/sessions/{session_id}/compression")
def session_compression(session_id: str) -> dict[str, Any]:
    """本会话 C2/压缩态快照，供用量预览展示。"""
    from memory.l5_flag import c2_gate, l5_mode
    from memory.working import hydrate as hydrate_working

    sid = require_session_id(session_id)
    snap = hydrate_working(sid)
    summary = str(snap.c2_summary_text or "")
    preview = summary[:280] + ("…" if len(summary) > 280 else "")
    cursor = int(snap.compact_cursor or 0)
    return {
        "session_id": sid,
        "c2_gate": bool(c2_gate()),
        "l5_mode": l5_mode(),
        "active": cursor > 0 and bool(summary),
        "compact_cursor": cursor,
        "last_action": str(snap.last_action or ""),
        "turns_since_c2": int(snap.turns_since_c2 or 0),
        "c2_summary_chars": len(summary),
        "c2_summary_preview": preview,
    }


@router.get("/v1/sessions/{session_id}/agents")
def session_agents(session_id: str) -> dict[str, Any]:
    """列出该会话跑过的全部子 agent 元数据（FE 卡片列表 / 历史回放入口）。"""
    from engine.subagent_runner import list_subagent_metas

    sid = require_session_id(session_id)
    agents: list[dict[str, Any]] = []
    from engine.live_agents import inbox_count as live_inbox_count

    for m in list_subagent_metas(sid):
        try:
            started_at = int(float(m.get("started_at") or 0) * 1000)
        except (TypeError, ValueError):
            started_at = 0
        aid = str(m.get("agent_id") or "")
        pending = [str(x) for x in (m.get("pending_followups") or []) if str(x).strip()]
        agents.append({
            "agentId": aid,
            "taskId": str(m.get("task_id") or ""),
            "desc": str(m.get("task_desc") or ""),
            "status": str(m.get("status") or "done"),
            "resultPreview": str(m.get("result_preview") or ""),
            "hasTranscript": bool(m.get("has_transcript")),
            "startedAt": started_at,
            "readOnly": bool(m.get("read_only", True))
            if "read_only" in m
            else not bool(m.get("write_scope")),
            "scope": [
                str(x) for x in (m.get("write_scope") or []) if str(x).strip()
            ][:16],
            "inboxCount": len(pending) + live_inbox_count(sid, aid),
            "tokensUsed": max(0, int(m.get("tokens_used") or 0)),
        })
    return {"session_id": sid, "agents": agents}


@router.get("/v1/sessions/{session_id}/agents/{agent_id}", response_model=None)
def session_agent_detail(session_id: str, agent_id: str) -> dict[str, Any]:
    """返回一个子 agent 的元数据 + 完整侧链对话（含图片引用与工具行）。"""
    from engine.subagent_runner import (
        _meta_path,
        load_sidechain_messages,
    )

    sid = require_session_id(session_id)
    aid = require_agent_id(agent_id)

    meta: dict[str, Any] | None = None
    try:
        mp = _meta_path(sid, aid)
        if mp.is_file():
            obj = json.loads(mp.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                meta = obj
    except Exception:
        meta = None

    raw_rows = load_sidechain_messages(sid, aid)
    # 元数据与侧链都不存在 ⇒ 该子 agent 从未运行过（而非「暂时没内容」）；
    # 用 404 让前端保持可重试/可识别，而不是误判为已失败的空记录。
    if meta is None and not raw_rows:
        raise api_error(404, "subagent transcript not found", "agent_not_found")

    messages: list[dict[str, Any]] = []
    pending_calls: deque[dict[str, Any]] = deque()
    for i, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            continue
        messages.extend(_side_row_to_ui(row, i, pending_calls))

    status = str((meta or {}).get("status") or ("done" if raw_rows else "error"))
    from engine.live_agents import inbox_count as live_inbox_count

    pending_followups = [str(x) for x in ((meta or {}).get("pending_followups") or []) if str(x).strip()]
    return {
        "session_id": sid,
        "agent_id": aid,
        "status": status,
        "meta": meta,
        "messages": messages,
        "inboxCount": len(pending_followups) + live_inbox_count(sid, aid),
    }


@router.post("/v1/sessions/{session_id}/agents/{agent_id}/cancel")
def session_agent_cancel(session_id: str, agent_id: str) -> dict[str, Any]:
    """取消正在运行的单个子 Agent（不影响主会话 abort）。"""
    from engine.live_agents import abort_live_agent, is_live_agent

    sid = require_session_id(session_id)
    aid = require_agent_id(agent_id)
    if not is_live_agent(sid, aid):
        raise api_error(404, "subagent is not running", "agent_not_live")
    ok = abort_live_agent(sid, aid)
    if not ok:
        raise api_error(404, "subagent is not running", "agent_not_live")
    return {"ok": True, "session_id": sid, "agent_id": aid, "status": "cancelling"}


class AgentFollowupRequest(BaseModel):
    text: str
    message_id: str | None = None


@router.post("/v1/sessions/{session_id}/agents/{agent_id}/inbox")
def session_agent_followup(
    session_id: str, agent_id: str, body: AgentFollowupRequest
) -> dict[str, Any]:
    """向一个子 agent 投递 follow-up（park 而非注入）。

    - 运行中 → 入运行时 inbox，下一轮 settle 后同实例续跑（卡片继续「运行中」）。
    - 已结束 → 追加到 meta.pending_followups，retry 时附带执行。
    返回 ``deliver``（running / pending）与 ``inboxCount``。
    """
    from engine.live_agents import (
        inbox_count as live_inbox_count,
        is_live_agent,
        post_to_agent,
    )
    from engine.subagent_runner import _meta_path, upsert_subagent_meta

    sid = require_session_id(session_id)
    aid = require_agent_id(agent_id)
    text = (body.text or "").strip()
    if not text:
        raise api_error(400, "follow-up text is empty", "empty_followup")
    if len(text) > 2000:
        # 静默截断会让模型收到一条被切掉尾巴的话；超长直接拒，由界面重投。
        raise api_error(
            422, "follow-up text exceeds 2000 characters", "invalid_request"
        )

    if is_live_agent(sid, aid):
        post_to_agent(sid, aid, text, message_id=str(body.message_id or ""))
        return {
            "ok": True,
            "deliver": "running",
            "inboxCount": live_inbox_count(sid, aid),
        }

    # 已结束：落 meta.pending_followups。这是「读整表 → 追加 → 写整表」的
    # 读-改-写，必须按 (会话, agent) 串行：两个并发投递会各自读到同一份旧表，
    # 后写的把先写的整表覆盖掉——一条 follow-up 静默消失。
    with _meta_locks.acquire(f"{sid}\x00{aid}"):
        meta: dict[str, Any] = {}
        read_failed = False
        try:
            mp = _meta_path(sid, aid)
            if mp.is_file():
                obj = json.loads(mp.read_text(encoding="utf-8"))
                if isinstance(obj, dict):
                    meta = obj
        except Exception:  # noqa: BLE001 — meta 读不到时按空表续写，但要留痕
            _logger.debug("agent meta read failed sid=%s aid=%s", sid, aid, exc_info=True)
            meta = {}
            read_failed = True
        pending = [str(x) for x in (meta.get("pending_followups") or []) if str(x).strip()]
        pending.append(text)
        upsert_subagent_meta(
            sid,
            agent_id=aid,
            task_desc=str(meta.get("task_desc") or ""),
            status=str(meta.get("status") or "done"),
            task_id=str(meta.get("task_id") or ""),
            result_preview=str(meta.get("result_preview") or ""),
            pending_followups=pending,
        )
        # upsert 对 OSError 是「静默 pass」：不回读确认就等于把没落盘的排队
        # 报成已排队（卡片计数 +1，retry 时消息却不存在）。
        persisted = _read_pending_followups(_meta_path, sid, aid)
        if text not in persisted:
            raise api_error(
                500,
                "follow-up could not be persisted to agent meta",
                "agent_inbox_persist_failed",
            )
    return {
        "ok": True,
        "deliver": "pending",
        "inboxCount": len(persisted),
        "meta_read_failed": read_failed,
    }


def _read_pending_followups(meta_path_fn, sid: str, aid: str) -> list[str]:
    """回读 meta.pending_followups（落盘确认与删除路径共用）。"""
    try:
        mp = meta_path_fn(sid, aid)
        if not mp.is_file():
            return []
        obj = json.loads(mp.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        _logger.debug("agent meta reread failed sid=%s aid=%s", sid, aid, exc_info=True)
        return []
    if not isinstance(obj, dict):
        return []
    return [str(x) for x in (obj.get("pending_followups") or []) if str(x).strip()]


@router.delete("/v1/sessions/{session_id}/agents/{agent_id}/inbox/{item_id}")
def session_agent_followup_remove(
    session_id: str, agent_id: str, item_id: str
) -> dict[str, Any]:
    """取消一条 follow-up：运行中从运行时队列移除；已结束从 meta 列表移除。"""
    from engine.live_agents import (
        is_live_agent,
        remove_agent_inbox_item,
    )

    sid = require_session_id(session_id)
    aid = require_agent_id(agent_id)
    target = _require_stable_id(item_id, field="item_id")

    if is_live_agent(sid, aid):
        removed = remove_agent_inbox_item(sid, aid, target)
        return {"ok": True, "deliver": "running", "removed": removed}

    # meta.pending_followups 以「文本即身份」存储：只按精确定位删。
    # 早先的兜底是「匹配不上就 pop() 最后一条」——调用方给错 id 时会删掉
    # 另一条排队消息，且回执 still 说 removed=true（错删 + 谎报）。
    from engine.subagent_runner import _meta_path, upsert_subagent_meta

    with _meta_locks.acquire(f"{sid}\x00{aid}"):
        meta: dict[str, Any] = {}
        try:
            mp = _meta_path(sid, aid)
            if mp.is_file():
                obj = json.loads(mp.read_text(encoding="utf-8"))
                if isinstance(obj, dict):
                    meta = obj
        except Exception:  # noqa: BLE001 — 读不到就当没有，下面按空表回执
            _logger.debug("agent meta read failed sid=%s aid=%s", sid, aid, exc_info=True)
            meta = {}
        pending = [
            str(x) for x in (meta.get("pending_followups") or []) if str(x).strip()
        ]
        idx = next((i for i, x in enumerate(pending) if x == target), None)
        if idx is None:
            return {
                "ok": True,
                "deliver": "pending",
                "removed": False,
                "inboxCount": len(pending),
            }
        pending.pop(idx)
        upsert_subagent_meta(
            sid,
            agent_id=aid,
            task_desc=str(meta.get("task_desc") or ""),
            status=str(meta.get("status") or "done"),
            task_id=str(meta.get("task_id") or ""),
            result_preview=str(meta.get("result_preview") or ""),
            pending_followups=pending,
        )
        persisted = _read_pending_followups(_meta_path, sid, aid)
        if target in persisted:
            raise api_error(
                500,
                "follow-up removal could not be persisted to agent meta",
                "agent_inbox_persist_failed",
            )
    return {"ok": True, "deliver": "pending", "removed": True, "inboxCount": len(persisted)}


class AgentRetryRequest(BaseModel):
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    thinking: str | None = None
    reasoning_effort: str | None = None
    max_budget_usd: float | None = None
    context_limit: int | None = None
    max_tokens: int | None = None


@router.post("/v1/sessions/{session_id}/agents/{agent_id}/retry")
async def session_agent_retry(
    session_id: str,
    agent_id: str,
    body: AgentRetryRequest | None = None,
    authorization: str | None = Header(default=None),
    x_provider: str | None = Header(default=None, alias="X-Provider"),
    x_base_url: str | None = Header(default=None, alias="X-Base-Url"),
) -> dict[str, Any]:
    """按原 task_desc 清侧链后重跑同一 agent_id（失败/取消后）。"""
    import json as _json

    from engine.abort import AbortController
    from engine.live_agents import is_live_agent
    from engine.subagent_runner import _meta_path, clear_sidechain
    from model.openai_compat import PROVIDER_PRESETS
    from server.deps import (
        _extract_bearer,
        _resolve_base_url,
        fake_model_enabled,
        local_model_allowed,
    )
    from server.session_pool import ModelConfig
    from tools.agent_tool import AgentTool

    sid = require_session_id(session_id)
    aid = require_agent_id(agent_id)
    # 双闸：主回合 detached turn 在跑 / busy 租约被占时不允许重试子 agent——
    # 重试会写工作区与侧链，与主回合并发会互相踩（曾无任何互斥直接放行）。
    from engine.turn_runner import get_turn_runner

    if get_turn_runner().is_running(sid):
        raise api_error(409, "会话正忙，请稍候或点停止后重试", "session_busy")
    lease_id = _pool.try_begin(sid)
    if lease_id is None:
        raise api_error(409, "会话正忙，请稍候或点停止后重试", "session_busy")
    if is_live_agent(sid, aid):
        _pool.end(sid, lease_id)
        raise api_error(409, "subagent still running; cancel first", "agent_busy")

    meta: dict[str, Any] = {}
    try:
        mp = _meta_path(sid, aid)
        if mp.is_file():
            obj = _json.loads(mp.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                meta = obj
    except Exception:  # noqa: BLE001
        meta = {}
    desc = str(meta.get("task_desc") or "").strip()
    task_id = str(meta.get("task_id") or "").strip() or "task"
    if not desc:
        _pool.end(sid, lease_id)
        raise api_error(400, "no task_desc in agent meta; cannot retry", "agent_no_desc")

    body = body or AgentRetryRequest()
    try:
        engine = _pool.get_if_present(sid)
        if engine is None:
            api_key = _extract_bearer(authorization)
            provider = (body.provider or x_provider or "deepseek").lower()
            if provider not in PROVIDER_PRESETS or (
                provider == "local" and not local_model_allowed()
            ) or (provider == "fake" and not fake_model_enabled()):
                raise api_error(400, f"unsupported provider: {provider}")
            if not api_key:
                if provider in ("local", "fake"):
                    api_key = "local"
                else:
                    raise api_error(
                        401,
                        "Missing API key. Set Authorization: Bearer <key>",
                        "authentication_error",
                    )
            base_url = _resolve_base_url(provider, body.base_url or x_base_url)
            cfg = ModelConfig(
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=(body.model or "deepseek-v4-flash"),
                thinking=(body.thinking or "disabled").strip().lower(),
                reasoning_effort=(body.reasoning_effort or "").strip().lower(),
                max_budget_usd=body.max_budget_usd,
                context_limit=body.context_limit,
                max_tokens=body.max_tokens,
            )
            engine = _pool.get_or_create(sid, cfg, cwd=_pool.session_cwd(sid) or _pool.cwd or None)
    except Exception:
        _pool.end(sid, lease_id)
        raise

    at = engine._tools.get("Agent")  # noqa: SLF001
    if not isinstance(at, AgentTool):
        _pool.end(sid, lease_id)
        raise api_error(500, "Agent tool not available on session engine")

    try:
        clear_sidechain(sid, aid)
        # P2：已结束 agent 的迟到 follow-up 在 retry 时连带执行——置入运行时
        # inbox，run_subagent 的 follow-up 循环同实例消费（清侧链后重跑但消息不丢）。
        try:
            from engine.live_agents import post_to_agent

            for fu in [str(x) for x in (meta.get("pending_followups") or []) if str(x).strip()]:
                post_to_agent(sid, aid, fu)
        except Exception:  # noqa: BLE001
            pass
        abort = AbortController()
        result = await at.execute(
            {
                "task_id": task_id,
                "desc": desc,
                "reuse_agent_id": aid,
                "parent_depth": 0,
            },
            abort,
        )
    finally:
        _pool.end(sid, lease_id)
    status = "failed" if result.is_error else "done"
    preview = (result.content or "")[:400]
    return {
        "ok": True,
        "session_id": sid,
        "agent_id": aid,
        "task_id": task_id,
        "status": status,
        "resultPreview": preview,
        "is_error": bool(result.is_error),
    }


def _rollback_service(session_id: str) -> RollbackService:
	sid = require_session_id(session_id)
	cwd = _pool.session_cwd(sid) or _pool.cwd
	if not (cwd or "").strip():
		raise api_error(400, "session has no workspace")
	return RollbackService(
		sid,
		cwd,
		session_busy=_pool.is_busy,
		# on_commit 用 drop_engine 而非 drop：会话仍存在，cwd pin / 权限
		# preset / TodoStore 必须保留，否则下一请求不带 workspace 时会静默换仓。
		on_commit=_pool.drop_engine,
		on_interrupt=_pool.interrupt,
		on_force_idle=_pool.force_idle,
		on_acquire_busy=_pool.try_begin,
		on_release_busy=lambda session_id, lease_id: _pool.end(session_id, lease_id),
	)


def _raise_rollback_api_error(exc: Exception) -> None:
	# 路由自己抛的 HTTPException（422 身份校验 / 400 无工作区）必须先原样上抛：
	# 否则会被下面的 catch-all 翻成 500「请求参数有误（400）」，客户端拿不到真因。
	if isinstance(exc, HTTPException):
		raise exc
	# T34：detail 经 safe_error_detail 过滤，内部异常痕迹不出 API。
	if isinstance(exc, RollbackDisabledError):
		raise api_error(404, safe_error_detail(exc), "rewind_disabled") from exc
	if isinstance(exc, LeaseBusyError):
		raise api_error(409, safe_error_detail(exc), "session_busy") from exc
	if isinstance(exc, RollbackConflictError):
		raise api_error(409, safe_error_detail(exc), "rollback_conflict") from exc
	if isinstance(exc, RollbackApprovalError):
		raise api_error(400, safe_error_detail(exc), "approval_required") from exc
	if isinstance(exc, RollbackIdempotencyError):
		raise api_error(409, safe_error_detail(exc), "idempotency_conflict") from exc
	if isinstance(exc, RollbackBlockedError):
		raise api_error(409, safe_error_detail(exc), "rollback_blocked") from exc
	if isinstance(exc, RollbackError):
		raise api_error(500, safe_error_detail(exc), "rollback_error") from exc
	raise api_error(500, friendly_error(exc), "server_error") from exc


@router.post("/v1/sessions/{session_id}/rollback/preview")
def rollback_preview(session_id: str, body: RollbackPreviewRequest) -> dict[str, Any]:
	"""Dry-run only: no transcript, workspace or engine mutation occurs."""
	try:
		plan = _rollback_service(session_id).preview(
			target_message_id=body.target_message_id,
			edited_text=body.edited_text,
			ttl_seconds=body.ttl_seconds,
		)
		return {"ok": True, "plan": plan.to_dict()}
	except Exception as exc:  # noqa: BLE001
		_raise_rollback_api_error(exc)


@router.post("/v1/sessions/{session_id}/rollback/execute")
def rollback_execute(session_id: str, body: RollbackExecuteRequest) -> dict[str, Any]:
	"""Execute one exact approved plan; retries are idempotency-keyed."""
	try:
		result = _rollback_service(session_id).execute(
			plan_id=body.plan_id,
			plan_hash=body.plan_hash,
			idempotency_key=body.idempotency_key,
			confirmed=body.confirmed,
			expected_workspace_revision=body.expected_workspace_revision,
			full_tree_restore=body.full_tree_restore,
			restore_workspace=body.restore_workspace,
			async_workspace=body.async_workspace,
		)
		return {"ok": True, **result}
	except Exception as exc:  # noqa: BLE001
		_raise_rollback_api_error(exc)


@router.post("/v1/sessions/{session_id}/rollback/jobs/{job_id}/recover")
def rollback_recover(
	session_id: str, job_id: str, body: RollbackRecoveryRequest
) -> dict[str, Any]:
	"""Retry checkpoint restore or abandon a recovery_required job."""
	jid = _require_stable_id(job_id, field="job_id")
	try:
		result = _rollback_service(session_id).resolve_recovery(
			job_id=jid,
			action=body.action,
		)
		return {"ok": True, **result}
	except Exception as exc:  # noqa: BLE001
		_raise_rollback_api_error(exc)


@router.get("/v1/sessions/{session_id}/rollback/status/{job_id}")
def rollback_status(session_id: str, job_id: str) -> dict[str, Any]:
	jid = _require_stable_id(job_id, field="job_id")
	try:
		job = _rollback_service(session_id).get_job(jid)
		if job is None:
			raise api_error(404, "rollback job not found", "not_found")
		return {"ok": True, "job": job.to_dict()}
	except HTTPException:
		raise
	except Exception as exc:  # noqa: BLE001
		_raise_rollback_api_error(exc)


@router.get("/v1/sessions/{session_id}/task")
def session_task(session_id: str) -> dict[str, Any]:
	"""当前会话任务快照（刷新 reattach / 重启 recovery 用）。"""
	sid = require_session_id(session_id)
	from engine.turn_runner import get_turn_runner
	from engine.turn_snapshot import hydrate as hydrate_turn

	pub = get_turn_runner().get_public(sid)
	if pub is None:
		snap = hydrate_turn(sid)
		if snap is None:
			return {
				"ok": True,
				"status": "idle",
				"session_id": sid,
				"turn_id": "",
				"last_event_id": 0,
				"stop_reason": "",
				"goal_text": "",
				"waiting_permission": False,
				"busy": _pool.is_busy(sid),
			}
		return {
			"ok": True,
			"status": snap.status,
			"session_id": snap.session_id,
			"turn_id": snap.turn_id,
			"last_event_id": snap.last_event_id,
			"stop_reason": snap.stop_reason,
			"goal_text": snap.goal_text,
			"waiting_permission": snap.waiting_permission,
			"revision": snap.revision,
			"busy": _pool.is_busy(sid),
		}
	return {
		"ok": True,
		"status": pub.status,
		"session_id": pub.session_id,
		"turn_id": pub.turn_id,
		"last_event_id": pub.last_event_id,
		"stop_reason": pub.stop_reason,
		"goal_text": pub.goal_text,
		"waiting_permission": pub.waiting_permission,
		"revision": pub.revision,
		"model": pub.model,
		"busy": _pool.is_busy(sid),
	}


@router.get("/v1/sessions/{session_id}/turns/current/events")
async def session_turn_events(
	session_id: str,
	request: Request,
	cursor: int = Query(default=0, ge=0),
) -> StreamingResponse:
	"""从 cursor 重放 + live 订阅（GUI 刷新 reattach）。"""
	sid = require_session_id(session_id)
	from engine.turn_runner import get_turn_runner

	runner = get_turn_runner()

	async def _live() -> Any:
		agen = runner.subscribe(sid, cursor=cursor)
		got_any = False
		while True:
			try:
				frame = await agen.__anext__()
			except StopAsyncIteration:
				break
			if frame is None:
				# subscribe() 内部 12s 心跳 tick。禁止 wait_for(__anext__)：
				# 超时取消会拆毁订阅生成器，流在无 [DONE] 下提前 EOF。
				if await request.is_disconnected():
					runner.note_client_disconnect(sid)
					break
				if not runner.is_running(sid):
					break
				yield b": ping\n\n"
				continue
			got_any = True
			if await request.is_disconnected():
				runner.note_client_disconnect(sid)
				break
			yield frame
		if not got_any and not runner.is_running(sid):
			yield b"data: [DONE]\n\n"

	return StreamingResponse(
		_live(),
		media_type="text/event-stream",
		headers={
			"Cache-Control": "no-cache",
			"Connection": "keep-alive",
			"X-Accel-Buffering": "no",
			"X-Session-Id": sid,
		},
	)


@router.post("/v1/sessions/{session_id}/recovery/abandon")
def session_recovery_abandon(session_id: str) -> dict[str, Any]:
	"""放弃 recovery_required 快照。"""
	from engine.turn_snapshot import flush as flush_turn, hydrate as hydrate_turn

	sid = require_session_id(session_id)
	snap = hydrate_turn(sid)
	if snap is None:
		return {"ok": True, "status": "idle"}
	snap.status = "stopped"
	snap.stop_reason = snap.stop_reason or "user_abandon"
	flush_turn(snap)
	return {"ok": True, "status": snap.status, "turn_id": snap.turn_id}


# ---------------------------------------------------------------------------
# P1 mid-turn inbox：排队快照 / 取消 / resume（GUI 轮询 + 操作）。
# ---------------------------------------------------------------------------
@router.get("/v1/sessions/{session_id}/inbox")
def session_inbox_list(session_id: str) -> dict[str, Any]:
	"""主会话 inbox 快照（GUI 轮询驱动 chip，多端可见）。"""
	from server.inbox_registry import get_inbox_registry

	sid = require_session_id(session_id)
	return get_inbox_registry().snapshot(sid)


class InboxEditRequest(BaseModel):
	text: str = Field(min_length=1, description="改写后的消息文本")


@router.delete("/v1/sessions/{session_id}/inbox/{queue_id}")
def session_inbox_remove(session_id: str, queue_id: str) -> dict[str, Any]:
	"""取消单条排队消息。delivering 态返回 409。"""
	from server.inbox_registry import get_inbox_registry

	sid = require_session_id(session_id)
	qid = _require_stable_id(queue_id, field="queue_id")
	ok = get_inbox_registry().remove(sid, qid)
	if not ok:
		raise api_error(409, "inbox item not found or already delivering", "inbox_delivering")
	return {"ok": True, "session_id": sid, "queue_id": qid}


@router.patch("/v1/sessions/{session_id}/inbox/{queue_id}")
def session_inbox_edit(
	session_id: str, queue_id: str, body: InboxEditRequest
) -> dict[str, Any]:
	"""改写单条排队消息文本（排队卡「编辑」动作）。

	delivering / 不存在 → 409；超长 → 413；编辑不改变队列位置与 queue_id。
	"""
	from server.inbox_registry import InboxTextTooLong, get_inbox_registry

	sid = require_session_id(session_id)
	qid = _require_stable_id(queue_id, field="queue_id")
	try:
		item = get_inbox_registry().edit(sid, qid, body.text)
	except InboxTextTooLong as e:
		raise api_error(413, str(e), "inbox_text_too_long") from e
	if item is None:
		raise api_error(409, "inbox item not found or already delivering", "inbox_delivering")
	return {"ok": True, "item": item.to_dict()}


@router.post("/v1/sessions/{session_id}/inbox/resume")
async def session_inbox_resume(session_id: str) -> dict[str, Any]:
	"""清 stuck 计数并重新 arm（stop 后 / stuck 后手动投递）。

	2026-09-05 修正：改 async def——``resume`` 内部 ``_maybe_schedule`` 需要运行
	中的事件循环；sync def（线程池）下拿不到 loop 会静默放弃，「立即排水」从不生效。
	"""
	from server.inbox_registry import get_inbox_registry

	sid = require_session_id(session_id)
	return get_inbox_registry().resume(sid)


@router.post("/v1/sessions/{session_id}/inbox/{queue_id}/resume")
async def session_inbox_item_resume(session_id: str, queue_id: str) -> dict[str, Any]:
	"""重试单条 stuck 消息；其它排队项目保持原状态。"""
	from server.inbox_registry import get_inbox_registry

	sid = (session_id or "").strip()
	qid = (queue_id or "").strip()
	if not sid or not qid:
		raise api_error(400, "session_id and queue_id are required")
	snapshot = get_inbox_registry().resume(sid, qid)
	if snapshot is None:
		raise api_error(409, "inbox item not found or no longer stuck", "inbox_not_stuck")
	return {"ok": True, **snapshot}
