"""Workspace 域路由：目录列表/读写删/搜索、Git 状态、终端执行。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from server import deps
from server.deps import _pool, api_error
from server.local_gate import require_loopback

router = APIRouter(tags=["workspace"])

class WorkspaceRequest(BaseModel):
	"""一个文件夹 = 一个工作区（Cursor 风格 Open Folder）。"""

	path: str


class WorkspaceWriteBody(BaseModel):
	path: str
	text: str


class TerminalExecBody(BaseModel):
	command: str = Field(min_length=1, max_length=4000)
	timeout_s: float | None = Field(default=None, ge=1, le=120)


class BashPolicyBody(BaseModel):
	bash_escalate: int | None = Field(default=None, ge=0)
	bash_routing: str | None = None


@router.get("/v1/workspace/policy-bash")
def get_policy_bash() -> dict[str, Any]:
	"""43 号：读 bash 路由/渐进强制策略 + 推荐/上限（供 UI 设置展示）。"""
	from permissions.workspace_policy import (
		BASH_ESCALATE_MAX,
		BASH_ESCALATE_RECOMMENDED,
		load_workspace_policy,
	)

	pol = load_workspace_policy(_pool.cwd)
	return {
		"ok": True,
		"cwd": _pool.cwd,
		"bash_routing": pol.bash_routing,
		"bash_escalate": pol.bash_escalate,
		"escalate_recommended": BASH_ESCALATE_RECOMMENDED,
		"escalate_max": BASH_ESCALATE_MAX,
		"escalate_min": 0,
	}


@router.post("/v1/workspace/policy-bash")
def set_policy_bash(body: BashPolicyBody, request: Request) -> dict[str, Any]:
	"""43 号：写 bash 路由/渐进强制策略（loopback 门禁），返回新策略 + 推荐/上限。"""
	require_loopback(request)
	from permissions.workspace_policy import (
		BASH_ESCALATE_MAX,
		BASH_ESCALATE_RECOMMENDED,
		write_bash_policy,
	)

	pol = write_bash_policy(
		_pool.cwd,
		bash_routing=body.bash_routing,
		bash_escalate=body.bash_escalate,
	)
	return {
		"ok": True,
		"cwd": _pool.cwd,
		"bash_routing": pol.bash_routing,
		"bash_escalate": pol.bash_escalate,
		"escalate_recommended": BASH_ESCALATE_RECOMMENDED,
		"escalate_max": BASH_ESCALATE_MAX,
		"escalate_min": 0,
	}


@router.get("/v1/workspace")
def get_workspace() -> dict[str, Any]:
	return {"ok": True, "cwd": _pool.cwd}


@router.post("/v1/workspace")
def set_workspace(body: WorkspaceRequest) -> dict[str, Any]:
	raw = (body.path or "").strip()
	if not raw:
		raise api_error(400, "workspace path is empty")
	try:
		cwd = _pool.set_cwd(raw)
	except FileNotFoundError as e:
		raise api_error(400, str(e)) from e
	except NotADirectoryError as e:
		raise api_error(400, str(e)) from e
	except ValueError as e:
		raise api_error(400, str(e)) from e
	deps.CWD = cwd
	return {"ok": True, "cwd": cwd}


@router.get("/v1/workspace/entries")
def workspace_entries(path: str = Query(default="")) -> dict[str, Any]:
	from server.workspace_fs import list_entries

	try:
		return list_entries(_pool.cwd, path)
	except FileNotFoundError as e:
		raise api_error(404, str(e)) from e
	except NotADirectoryError as e:
		raise api_error(400, str(e)) from e
	except PermissionError as e:
		raise api_error(403, str(e)) from e


@router.get("/v1/workspace/file")
def workspace_file(path: str = Query(default="")) -> dict[str, Any]:
	from server.workspace_fs import read_file

	if not (path or "").strip():
		raise api_error(400, "path is empty")
	try:
		return read_file(_pool.cwd, path)
	except FileNotFoundError as e:
		raise api_error(404, str(e)) from e
	except PermissionError as e:
		raise api_error(403, str(e)) from e
	except IsADirectoryError as e:
		raise api_error(400, str(e)) from e


@router.get("/v1/workspace/file/stat")
def workspace_file_stat(path: str = Query(default="")) -> dict[str, Any]:
	"""轻量 stat：不读正文，供文件预览 Agent 忙碌期轮询。"""
	from server.workspace_fs import stat_file

	if not (path or "").strip():
		raise api_error(400, "path is empty")
	try:
		return stat_file(_pool.cwd, path)
	except FileNotFoundError as e:
		raise api_error(404, str(e)) from e
	except PermissionError as e:
		raise api_error(403, str(e)) from e
	except IsADirectoryError as e:
		raise api_error(400, str(e)) from e


@router.put("/v1/workspace/file")
def workspace_write(body: WorkspaceWriteBody) -> dict[str, Any]:
	from server.workspace_fs import write_file

	if not (body.path or "").strip():
		raise api_error(400, "path is empty")
	try:
		return write_file(_pool.cwd, body.path, body.text)
	except FileNotFoundError as e:
		raise api_error(404, str(e)) from e
	except PermissionError as e:
		raise api_error(403, str(e)) from e
	except IsADirectoryError as e:
		raise api_error(400, str(e)) from e
	except ValueError as e:
		raise api_error(400, str(e)) from e


@router.delete("/v1/workspace/file")
def workspace_delete_file(
	path: str = Query(default=""),
	recursive: bool = Query(default=False),
) -> dict[str, Any]:
	from server.workspace_fs import delete_path

	if not (path or "").strip():
		raise api_error(400, "path is empty")
	try:
		return delete_path(_pool.cwd, path, recursive=recursive)
	except FileNotFoundError as e:
		raise api_error(404, str(e)) from e
	except PermissionError as e:
		raise api_error(403, str(e)) from e
	except IsADirectoryError as e:
		raise api_error(400, str(e)) from e
	except OSError as e:
		raise api_error(500, str(e)) from e


@router.get("/v1/workspace/graph")
def workspace_graph(refresh: bool = Query(default=False)) -> dict[str, Any]:
	"""代码/架构图：文件节点 + import 边 + 包折叠。无 LLM、无持久索引。"""
	from codeindex.graph import build_workspace_graph

	try:
		return build_workspace_graph(_pool.cwd, refresh=refresh)
	except FileNotFoundError as e:
		raise api_error(404, str(e)) from e
	except PermissionError as e:
		raise api_error(403, str(e)) from e


@router.get("/v1/workspace/outline")
def workspace_outline(path: str = Query(default="")) -> dict[str, Any]:
	"""单文件符号大纲（按需，不扫全仓）。"""
	from pathlib import Path

	from codeindex.symbols import outline
	from server.workspace_fs import resolve_in_workspace

	raw = (path or "").strip()
	if not raw:
		raise api_error(400, "path is empty")
	try:
		abs_path = resolve_in_workspace(_pool.cwd, raw)
	except FileNotFoundError as e:
		raise api_error(404, str(e)) from e
	except PermissionError as e:
		raise api_error(403, str(e)) from e
	if not abs_path.is_file():
		raise api_error(400, "path is not a file")
	syms = outline(str(abs_path))
	return {
		"ok": True,
		"path": raw.replace("\\", "/"),
		"symbols": [
			{
				"kind": s.kind,
				"name": s.name,
				"start": s.start,
				"end": s.end,
				"parent": s.parent,
				"signature": s.signature,
				"approximate": s.approximate,
			}
			for s in syms
		],
	}


class MapExplainBody(BaseModel):
	id: str
	kind: str = "file"  # file | package


@router.post("/v1/workspace/map/explain")
def workspace_map_explain(body: MapExplainBody) -> dict[str, Any]:
	"""按需节点摘要：确定性结构说明；不写 MessageStore / JSONL。

	禁止全仓分析——只解释单个 id。不在打开工作区时自动触发。
	"""
	from pathlib import Path

	from codeindex.graph import build_workspace_graph, package_id
	from codeindex.symbols import outline
	from server.workspace_fs import resolve_in_workspace

	node_id = (body.id or "").strip().replace("\\", "/")
	kind = (body.kind or "file").strip().lower()
	if not node_id:
		raise api_error(400, "id is empty")

	graph = build_workspace_graph(_pool.cwd)
	lines: list[str] = []

	if kind == "package":
		pkg = next((p for p in graph["packages"] if p["id"] == node_id), None)
		if not pkg:
			raise api_error(404, f"package not found: {node_id}")
		files = [f for f in graph["files"] if f["pkg"] == node_id][:12]
		deps = [e["to"] for e in graph["packageEdges"] if e["from"] == node_id][:8]
		importers = [e["from"] for e in graph["packageEdges"] if e["to"] == node_id][:8]
		lines.append(f"包 `{node_id}` · 层 {pkg['layer']} · {pkg['files']} 个文件")
		if files:
			lines.append("主要文件：" + "、".join(f["name"] for f in files[:8]))
		if deps:
			lines.append("依赖：" + "、".join(deps))
		if importers:
			lines.append("被依赖：" + "、".join(importers))
	else:
		fnode = next((f for f in graph["files"] if f["id"] == node_id), None)
		outs = [e["to"] for e in graph["fileEdges"] if e["from"] == node_id][:8]
		ins = [e["from"] for e in graph["fileEdges"] if e["to"] == node_id][:8]
		layer = fnode["layer"] if fnode else "core"
		pkg = fnode["pkg"] if fnode else package_id(node_id)
		lines.append(f"文件 `{node_id}` · 层 {layer} · 包 {pkg}")
		if outs:
			lines.append("imports：" + "、".join(Path(p).name for p in outs))
		if ins:
			lines.append("imported by：" + "、".join(Path(p).name for p in ins))
		try:
			abs_path = resolve_in_workspace(_pool.cwd, node_id)
			if abs_path.is_file():
				syms = outline(str(abs_path))[:16]
				if syms:
					names = [
						(f"{s.parent}.{s.name}" if s.parent else s.name) for s in syms
					]
					lines.append("符号：" + "、".join(names))
		except (OSError, ValueError, FileNotFoundError, PermissionError):
			pass

	return {
		"ok": True,
		"id": node_id,
		"kind": kind,
		"summary": "\n".join(lines),
		"source": "structure",
	}


@router.get("/v1/workspace/search")
def workspace_search(q: str = Query(default="")) -> dict[str, Any]:
	from server.workspace_fs import search_entries

	try:
		return search_entries(_pool.cwd, q)
	except FileNotFoundError as e:
		raise api_error(404, str(e)) from e
	except PermissionError as e:
		raise api_error(403, str(e)) from e


@router.get("/v1/workspace/journal")
def workspace_journal(
    path_prefix: str = Query(default=""),
    agent_id: str = Query(default=""),
    since_ts: float | None = Query(default=None, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
) -> dict[str, Any]:
    """跨 agent 的最近工作区变更（人可见；只读，不含对话正文）。"""
    from memory import journal
    from memory.memdir import workspace_id

    cwd = (str(_pool.cwd or "")).strip()
    if not cwd:
        raise api_error(400, "workspace cwd is empty")
    wsid = workspace_id(cwd)
    rows = journal.recent_changes(
        wsid,
        path_prefix=(path_prefix or "").strip() or None,
        agent_id=(agent_id or "").strip() or None,
        since_ts=since_ts,
        limit=limit,
        workspace_root=cwd,
    )
    return {
        "ok": True,
        "cwd": cwd,
        "changes": [
            {
                "seq": r.seq,
                "agent_id": r.agent_id,
                "path": r.path,
                "action": r.action,
                "ts": r.ts,
                "brief": r.brief,
                "syntax_valid": r.syntax_valid,
                "conflict_task": r.conflict_task,
                "diff": r.diff or "",
                "session_id": str((r.metadata or {}).get("session_id") or ""),
            }
            for r in rows
        ],
    }


@router.get("/v1/workspace/peers")
def workspace_peers(
	cwd: str = Query(default=""),
	session_id: str = Query(default=""),
) -> dict[str, Any]:
	"""同工作区其他会话在场摘要（人类可见；不含对话正文）。"""
	from engine.session_presence import default_session_presence

	root = (cwd or "").strip() or _pool.cwd
	if not root:
		raise api_error(400, "workspace cwd is empty")
	peers = default_session_presence().to_peer_dicts(root, session_id.strip())
	return {"ok": True, "cwd": root, "peers": peers}


@router.get("/v1/workspace/git/status")
def workspace_git_status() -> dict[str, Any]:
	from server.workspace_git import GitBinaryMissing, GitError, read_git_status

	try:
		return read_git_status(_pool.cwd)
	except FileNotFoundError as e:
		raise api_error(404, str(e)) from e
	except GitBinaryMissing as e:
		raise api_error(503, str(e)) from e
	except GitError as e:
		raise api_error(500, str(e)) from e


@router.get("/v1/workspace/git/log")
def workspace_git_log(limit: int = Query(default=20, ge=1, le=500)) -> dict[str, Any]:
	from server.workspace_git import GitBinaryMissing, GitError, read_git_log

	try:
		return read_git_log(_pool.cwd, limit)
	except FileNotFoundError as e:
		raise api_error(404, str(e)) from e
	except GitBinaryMissing as e:
		raise api_error(503, str(e)) from e
	except GitError as e:
		raise api_error(500, str(e)) from e


@router.get("/v1/workspace/git/branches")
def workspace_git_branches() -> dict[str, Any]:
	from server.workspace_git import GitBinaryMissing, GitError, read_git_branches

	try:
		return read_git_branches(_pool.cwd)
	except FileNotFoundError as e:
		raise api_error(404, str(e)) from e
	except GitBinaryMissing as e:
		raise api_error(503, str(e)) from e
	except GitError as e:
		raise api_error(500, str(e)) from e


@router.get("/v1/workspace/file/diff")
def workspace_file_diff(path: str = Query(default="")) -> dict[str, Any]:
	from server.workspace_git import GitBinaryMissing, GitError, read_file_diff

	if not (path or "").strip():
		raise api_error(400, "path is empty")
	try:
		return read_file_diff(_pool.cwd, path)
	except FileNotFoundError as e:
		raise api_error(404, str(e)) from e
	except PermissionError as e:
		raise api_error(403, str(e)) from e
	except GitBinaryMissing as e:
		raise api_error(503, str(e)) from e
	except GitError as e:
		raise api_error(500, str(e)) from e


@router.post("/v1/workspace/terminal/exec")
def workspace_terminal_exec(body: TerminalExecBody, request: Request) -> dict[str, Any]:
	from server.workspace_terminal import TerminalError, run_command
	from permissions.bash_policy import bash_deny_reason

	require_loopback(request)
	denied = bash_deny_reason(body.command)
	if denied:
		raise api_error(403, f"command denied: {denied}", "permission_error")
	try:
		return run_command(_pool.cwd, body.command, body.timeout_s or 30)
	except FileNotFoundError as e:
		raise api_error(404, str(e)) from e
	except TerminalError as e:
		raise api_error(400, str(e)) from e

