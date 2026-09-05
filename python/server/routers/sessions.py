"""Sessions 域路由：会话列表/消息恢复/删除与 rollback 预览执行。"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
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
    transcript_read_paths,
)
from session.transcript_blobs import remove_blobs_dir, resolve_transcript_rows
from server.deps import _MAX_USER_CHARS, _pool, api_error
from server.local_gate import require_loopback

# T33：会话面（含删除/回滚/恢复等破坏性操作）仅 loopback。
router = APIRouter(tags=["sessions"], dependencies=[Depends(require_loopback)])

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
	sid = (session_id or "").strip()
	if not sid:
		raise api_error(400, "session_id is empty")
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
	sid = (session_id or "").strip()
	if not sid:
		raise api_error(400, "session_id is empty")
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
	sid = (session_id or "").strip()
	if not sid:
		raise api_error(400, "session_id is empty")
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
	# Default off: restore only agent-touched files. Opt in for full shadow-git tree.
	full_tree_restore: bool | None = None
	# None = follow plan.metadata.restores_workspace; False = chat transcript only.
	restore_workspace: bool | None = None
	# Rewind v2: return after transcript_committed; workspace finishes in background.
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
	"""丢弃 FE 已删除聊天的内存 engine（#7），并清理磁盘 transcript 与会话目录。"""
	sid = (session_id or "").strip()
	if not sid:
		raise api_error(400, "session_id is empty")
	dropped = _pool.drop(sid)
	removed: list[str] = []

	# 磁盘 transcript（.jsonl + .old 轮转归档）：不删的话重启后 list_sessions 会把已删除会话重新导入。
	root = default_sessions_dir()
	try:
		tp = transcript_path(sid, sessions_dir=root)
		for f in (tp, rotated_transcript_path(tp)):
			if f.is_file():
				f.unlink()
				removed.append(str(f))
		remove_blobs_dir(tp)
	except OSError:
		pass

	# 会话子目录（rewind revisions/journal、rollback plans/approvals、recovery jobs）。
	sdir = root / safe_session_filename(sid)
	if sdir.is_dir():
		shutil.rmtree(sdir, ignore_errors=True)
		removed.append(str(sdir))

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
	except Exception:
		pass

	# 活审批模式（RuntimeModeStore）按会话清理，防残留。
	try:
		from permissions.runtime_mode import get_runtime_mode_store

		get_runtime_mode_store().clear(sid)
	except Exception:
		pass

	# 运行时权限 preset 活值同样按会话清理（smoke-test #6）。
	try:
		from permissions.runtime_preset import get_runtime_preset_store

		get_runtime_preset_store().clear(sid)
	except Exception:
		pass

	return {"ok": True, "dropped": dropped, "removed": removed}


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
					if obj.get("role") == "user":
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
		archived_at: float | None = None
		try:
			from engine.title import read_archive

			ar = read_archive(sid)
			if ar:
				archived_at = float(ar["archivedAt"])
		except Exception:
			archived_at = None
		out.append({
			"id": sid,
			"title": title,
			"createdAt": created_at,
			"updatedAt": int(st.st_mtime * 1000),
			"archivedAt": archived_at,
		})
	return {"sessions": out}


class RenameRequest(BaseModel):
	title: str


@router.post("/v1/sessions/{session_id}/rename")
def rename_session(session_id: str, body: RenameRequest) -> dict[str, Any]:
	"""T5：用户显式改名——写 pinned sidecar，永不被自动标题覆盖。"""
	title = str(body.title or "").strip()
	if not title:
		raise api_error(400, "title must not be empty", "invalid_request")
	try:
		from engine.title import write_title

		entry = write_title(session_id, title, pinned=True)
	except Exception as e:  # noqa: BLE001
		raise api_error(500, friendly_error(e), "server_error") from e
	return {"id": session_id, "title": entry["title"], "pinned": True}


class ForkRequest(BaseModel):
	reason: str | None = Field(default=None, max_length=128)


@router.post("/v1/sessions/{session_id}/fork")
def fork_session(session_id: str, body: ForkRequest | None = None) -> dict[str, Any]:
	"""smoke-test #3：分叉会话——复制 transcript + title sidecar 到新 sid。

	新 sid 服务端签发；workspace 沿用原会话的 cwd；engine 不预创建（首条 chat 才真正钉死）。
	侧聊（side-）前缀的会话不允许 fork（与主面板语义不一致）；后端会 400。
	"""
	from engine.title import read_title, write_title

	sid = (session_id or "").strip()
	if not sid:
		raise api_error(400, "session_id is empty")
	if sid.startswith("side-"):
		raise api_error(400, "side-chat sessions cannot be forked", "side_chat_unsupported")
	root = default_sessions_dir()
	src_tp = transcript_path(sid, sessions_dir=root)
	src_old = rotated_transcript_path(src_tp)
	if not src_tp.is_file() and not src_old.is_file():
		raise api_error(404, "source session has no transcript", "source_missing")

	new_sid = f"xeyo-{uuid.uuid4().hex[:12]}"
	dst_tp = transcript_path(new_sid, sessions_dir=root)
	dst_tp.parent.mkdir(parents=True, exist_ok=True)

	# 复制 current transcript；若有 .old 轮转归档也一并复制（顺序保留）。
	copied: list[str] = []
	if src_tp.is_file():
		try:
			shutil.copy2(src_tp, dst_tp)
			copied.append(str(dst_tp))
		except OSError as e:
			raise api_error(500, f"copy transcript failed: {e}", "server_error") from e
	if src_old.is_file():
		dst_old = rotated_transcript_path(dst_tp)
		try:
			shutil.copy2(src_old, dst_old)
			copied.append(str(dst_old))
		except OSError as e:
			# .old 复制失败不影响主 fork，保留 warn
			copied.append(f"WARN old-copy-failed: {e}")

	# 复制 title sidecar（如有）并加 (分叉) 标签，避免直接覆盖原 pinned。
	src_title = read_title(sid, sessions_dir=root)
	fork_title = (src_title["title"] + " (分叉)") if src_title else "新对话 (分叉)"
	try:
		write_title(new_sid, fork_title, pinned=True, sessions_dir=root)
	except Exception:
		pass

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
	except Exception:
		pass

	cwd = _pool.session_cwd(sid) or _pool.cwd or ""
	return {
		"ok": True,
		"source_id": sid,
		"new_id": new_sid,
		"title": fork_title,
		"cwd": cwd,
		"copied": copied,
	}


@router.post("/v1/sessions/{session_id}/archive")
def archive_session(session_id: str) -> dict[str, Any]:
	"""smoke-test #3：归档会话——仅写 archive sidecar，不删 transcript。

	可恢复：list_sessions 过滤 archived；restore_session 清 sidecar。
	"""
	from engine.title import write_archive

	sid = (session_id or "").strip()
	if not sid:
		raise api_error(400, "session_id is empty")
	root = default_sessions_dir()
	# 没有 transcript 的会话也允许归档（占位）
	entry = write_archive(sid, sessions_dir=root)
	return {"ok": True, "id": sid, "archivedAt": entry["archivedAt"], "reason": entry["reason"]}


@router.post("/v1/sessions/{session_id}/restore")
def restore_session(session_id: str) -> dict[str, Any]:
	"""smoke-test #3：找回已归档会话——删 archive sidecar。"""
	from engine.title import clear_archive

	sid = (session_id or "").strip()
	if not sid:
		raise api_error(400, "session_id is empty")
	removed = clear_archive(sid)
	return {"ok": True, "id": sid, "restored": removed}


@router.get("/v1/sessions/{session_id}/messages", response_model=None)
async def session_messages(session_id: str):
	"""按精确 session_id 读取 transcript 消息（不套 side- 前缀），供前端恢复本地历史。

	跨轮转归档（.old2 → .old1 → 当前）按时间顺序合并读取。
	工具行与 list 形 assistant 块通过 ``_side_row_to_ui`` 展开为前端 ChatMessage 形状。
	"""
	raw_rows: list[dict[str, Any]] = []
	p = transcript_path(session_id)
	for f in transcript_read_paths(p):
		if not f.exists():
			continue
		try:
			with f.open("r", encoding="utf-8") as fh:
				for line in fh:
					line = line.strip()
					if not line:
						continue
					try:
						row = json.loads(line)
					except Exception:
						continue
					if isinstance(row, dict):
						raw_rows.append(row)
		except Exception:
			continue

	messages: list[dict[str, Any]] = []
	pending_calls: deque[dict[str, Any]] = deque()
	# replace 事件化回溯：模型可见面 = fold 后的行（旧日志无 marker 时恒等）。
	from session.surface import fold_surface_rows

	for i, row in enumerate(
		resolve_transcript_rows(fold_surface_rows(raw_rows), p)
	):
		messages.extend(_side_row_to_ui(row, i, pending_calls))
	# T31：随消息返回服务端权威 cwd（供 cli-ts 等薄客户端恢复会话时不自定工作区）。
	return {
		"session_id": session_id,
		"messages": messages,
		"cwd": _pool.session_cwd(session_id) or _pool.cwd or "",
	}


def _side_row_to_ui(
	row: dict[str, Any],
	idx: int,
	pending_calls: deque[dict[str, Any]],
) -> list[dict[str, Any]]:
    """把侧链 transcript 行（Message dict）展开为前端 ChatMessage 形状。

    与主会话恢复接口保持一致的渲染语义：
    - user：进 text（list 块拆出图片引用）；
    - assistant：str 直接用；list 块拆出 text 段落，并把 ``tool_use`` 块压入
      pending 队列 —— 它们的输入参数要配对到随后的 tool 结果行；
    - tool：content 是块列表（tool_result + 可选 image_url）；按名字/FIFO 配对
      到最近一个未消费的 tool_use，输出「合并单行」：toolName/toolInput/text。
    返回 0..n 行；空返回表示该行无可渲染内容（如纯 thinking 块）。
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
        # list：拆 text 段落 + 把 tool_use 参数入队等待结果行配对。
        texts: list[str] = []
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text" and isinstance(block.get("text"), str) and block["text"].strip():
                    if texts:
                        texts.append("\n")
                    texts.append(block["text"])
                elif btype == "tool_use":
                    pending_calls.append({
                        "name": str(block.get("name") or ""),
                        "input": block.get("input"),
                        "ts": created,
                    })
        text = "".join(texts)
        if not text.strip():
            return []
        return [{"id": mid, "role": "assistant", "text": text, "createdAt": created}]

    if role == "tool":
        result_text = ""
        is_error = False
        media_urls: list[str] = []
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

        # 配对 tool_use：优先同名，否则 FIFO（跨行喂给前端 Args 展示）。
        call: dict[str, Any] | None = None
        for i, pend in enumerate(pending_calls):
            same_name = (pend.get("name") or "") == msg_name
            if same_name or (i == 0 and not any(p.get("name") == msg_name for p in pending_calls)):
                call = pending_calls.popleft() if same_name else pending_calls.popleft()
                break
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
    sid = (session_id or "").strip()
    if not sid:
        raise api_error(400, "session_id is empty")
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

    sid = (session_id or "").strip()
    if not sid:
        raise api_error(400, "session_id is empty")
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

    sid = (session_id or "").strip()
    if not sid:
        raise api_error(400, "session_id is empty")
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
        })
    return {"session_id": sid, "agents": agents}


@router.get("/v1/sessions/{session_id}/agents/{agent_id}", response_model=None)
def session_agent_detail(session_id: str, agent_id: str) -> dict[str, Any]:
    """返回一个子 agent 的元数据 + 完整侧链对话（含图片引用与工具行）。"""
    from engine.subagent_runner import (
        _meta_path,
        load_sidechain_messages,
    )

    sid = (session_id or "").strip()
    aid = (agent_id or "").strip()
    if not sid or not aid:
        raise api_error(400, "session_id and agent_id are required")

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

    sid = (session_id or "").strip()
    aid = (agent_id or "").strip()
    if not sid or not aid:
        raise api_error(400, "session_id and agent_id are required")
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

    sid = (session_id or "").strip()
    aid = (agent_id or "").strip()
    text = (body.text or "").strip()
    if not sid or not aid:
        raise api_error(400, "session_id and agent_id are required")
    if not text:
        raise api_error(400, "follow-up text is empty", "empty_followup")
    if len(text) > 2000:
        text = text[:2000]

    if is_live_agent(sid, aid):
        post_to_agent(sid, aid, text, message_id=str(body.message_id or ""))
        return {
            "ok": True,
            "deliver": "running",
            "inboxCount": live_inbox_count(sid, aid),
        }

    # 已结束：落 meta.pending_followups（先读后写，锁内原子）。
    meta: dict[str, Any] = {}
    try:
        mp = _meta_path(sid, aid)
        if mp.is_file():
            import json as _json

            obj = _json.loads(mp.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                meta = obj
    except Exception:  # noqa: BLE001
        meta = {}
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
    return {
        "ok": True,
        "deliver": "pending",
        "inboxCount": len(pending),
    }


@router.delete("/v1/sessions/{session_id}/agents/{agent_id}/inbox/{item_id}")
def session_agent_followup_remove(
    session_id: str, agent_id: str, item_id: str
) -> dict[str, Any]:
    """取消一条 follow-up：运行中从运行时队列移除；已结束从 meta 列表移除。"""
    from engine.live_agents import (
        is_live_agent,
        remove_agent_inbox_item,
    )

    sid = (session_id or "").strip()
    aid = (agent_id or "").strip()
    if not sid or not aid:
        raise api_error(400, "session_id and agent_id are required")

    if is_live_agent(sid, aid):
        removed = remove_agent_inbox_item(sid, aid, item_id)
        return {"ok": True, "deliver": "running", "removed": removed}

    # meta.pending_followups：按 item_id == 文本 精确定位（无匹配则取首条）。
    from engine.subagent_runner import _meta_path, upsert_subagent_meta

    meta: dict[str, Any] = {}
    try:
        mp = _meta_path(sid, aid)
        if mp.is_file():
            import json as _json

            obj = _json.loads(mp.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                meta = obj
    except Exception:  # noqa: BLE001
        meta = {}
    pending = [str(x) for x in (meta.get("pending_followups") or []) if str(x).strip()]
    removed = False
    idx = next((i for i, x in enumerate(pending) if x == item_id), None)
    if idx is not None:
        pending.pop(idx)
        removed = True
    elif pending:
        pending.pop()
        removed = True
    upsert_subagent_meta(
        sid,
        agent_id=aid,
        task_desc=str(meta.get("task_desc") or ""),
        status=str(meta.get("status") or "done"),
        task_id=str(meta.get("task_id") or ""),
        result_preview=str(meta.get("result_preview") or ""),
        pending_followups=pending,
    )
    return {"ok": True, "deliver": "pending", "removed": removed}


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
        local_model_enabled,
    )
    from server.session_pool import ModelConfig
    from tools.agent_tool import AgentTool

    sid = (session_id or "").strip()
    aid = (agent_id or "").strip()
    if not sid or not aid:
        raise api_error(400, "session_id and agent_id are required")
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
                provider == "local" and not local_model_enabled()
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
	sid = (session_id or "").strip()
	if not sid:
		raise api_error(400, "session_id is empty")
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
	try:
		result = _rollback_service(session_id).resolve_recovery(
			job_id=job_id,
			action=body.action,
		)
		return {"ok": True, **result}
	except Exception as exc:  # noqa: BLE001
		_raise_rollback_api_error(exc)


@router.get("/v1/sessions/{session_id}/rollback/status/{job_id}")
def rollback_status(session_id: str, job_id: str) -> dict[str, Any]:
	try:
		job = _rollback_service(session_id).get_job(job_id)
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
	sid = (session_id or "").strip()
	if not sid:
		raise api_error(400, "session_id required", "invalid_request")
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
	sid = (session_id or "").strip()
	if not sid:
		raise api_error(400, "session_id required", "invalid_request")
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

	sid = (session_id or "").strip()
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

	sid = (session_id or "").strip()
	if not sid:
		raise api_error(400, "session_id required", "invalid_request")
	return get_inbox_registry().snapshot(sid)


@router.delete("/v1/sessions/{session_id}/inbox/{queue_id}")
def session_inbox_remove(session_id: str, queue_id: str) -> dict[str, Any]:
	"""取消单条排队消息。delivering 态返回 409。"""
	from server.inbox_registry import get_inbox_registry

	sid = (session_id or "").strip()
	qid = (queue_id or "").strip()
	if not sid or not qid:
		raise api_error(400, "session_id and queue_id required", "invalid_request")
	ok = get_inbox_registry().remove(sid, qid)
	if not ok:
		raise api_error(409, "inbox item not found or already delivering", "inbox_delivering")
	return {"ok": True, "session_id": sid, "queue_id": qid}


@router.post("/v1/sessions/{session_id}/inbox/resume")
async def session_inbox_resume(session_id: str) -> dict[str, Any]:
	"""清 stuck 计数并重新 arm（stop 后 / stuck 后手动投递）。

	2026-09-05 修正：改 async def——``resume`` 内部 ``_maybe_schedule`` 需要运行
	中的事件循环；sync def（线程池）下拿不到 loop 会静默放弃，「立即排水」从不生效。
	"""
	from server.inbox_registry import get_inbox_registry

	sid = (session_id or "").strip()
	if not sid:
		raise api_error(400, "session_id required", "invalid_request")
	return get_inbox_registry().resume(sid)
