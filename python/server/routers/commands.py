"""Slash 命令路由：``POST /v1/slash``。

GUI / CLI-TS 通过该端点执行 ``handler=server`` 的斜杠命令；CLI-Py 与远程通道
进程内直接调 :func:`slash.dispatch`，不走 HTTP。

鉴权与 ``/v1/chat/completions`` 同源（Bearer API key + loopback 门禁）。
命令**不通模型、不改 MessageStore**；模式/精简/模型/主题/审批等
client 命令由发起面本地处理，本端点直接拒收。

边缘信任（与其它 HTTP 路由同一套谓词，构造 ctx 前完成）：``workspace`` 必须是
绝对现存目录（``require_workspace_arg``，空白=回退已登记 cwd 不变）、
``session_id`` 必须是 ``safe_session_filename`` 的固定点
（``sessions._require_stable_id``），``arg`` 不允许以 ``-`` 开头进入转发给 ``git``
argv 的命令——三者都在 422 处收口，因为 dispatch 的 ``_workspace`` 原样透传，
而 ``/revert`` 会按会话名读写磁盘上的 transcript 事件日志。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from server.deps import _extract_bearer, _pool, _resolve_base_url, api_error
from server.local_gate import require_loopback
from server.routers.extensions import require_workspace_arg
from server.routers.sessions import _require_stable_id
from slash.dispatch import CommandResult, DispatchContext, dispatch_command
from slash.registry import get_command

router = APIRouter(tags=["slash"])

_logger = logging.getLogger(__name__)

#: ``arg`` 会被原样拼进 ``git`` argv 的服务端命令（``slash.dispatch._cmd_diff`` →
#: ``_run_git``）。实测 ``/diff --output=<绝对路径>`` 让服务端进程以调用者指定的
#: 路径写文件（HTTP 200）。执行层拦截：这类命令的 arg 不允许以 ``-`` 开头，
#: 422 是中性结果，不是建议。其余 server 命令的 arg 只做 jail 内路径拼接或字典
#: 查表，不在此集合内——新增把 arg 转发进 argv 的命令时要同步这一行。
_ARGV_FORWARDING_COMMANDS = frozenset({"diff"})


def _require_stable_arg(cmd_name: str, arg: str) -> str:
	"""argv 转发类命令：arg 里**任何一个** token 都不许以 ``-`` 开头。

	只看首 token 是不够的 —— 实测 ``git diff --stat HEAD --output=<绝对路径>``
	同样会写出文件（git 在 pathspec 之后仍认这个选项），所以 ``"HEAD --output=..."``
	这种"先给个合法 rev 再夹带选项"的写法必须一起挡住。``HEAD~5`` / ``main`` /
	提交号这类合法 rev 不含前导 ``-``，不受影响。
	"""
	if cmd_name in _ARGV_FORWARDING_COMMANDS and any(
		token.startswith("-") for token in arg.split()
	):
		raise api_error(
			422,
			f"arg for /{cmd_name} must not contain '-' options",
			"invalid_request",
		)
	return arg


def _require_slash_session_id(raw: str | None) -> str:
	"""``session_id`` 的边缘校验：与 ``require_session_id`` 同一固定点谓词。

	空白（含纯空白）返回 ``""``，语义不变——回退到已登记 cwd / 无会话命令自行
	拒绝；非空白但会被 ``safe_session_filename`` 改写的写法（``victim.`` /
	``.victim`` / ``vi:ctim`` / 带首尾空白）一律 422：它们在磁盘上与 ``victim``
	是同一份 transcript 与 rewind 事件日志，``/revert`` 会读错并写错别人的会话。
	"""
	value = (raw or "").strip()
	if not value:
		return ""
	return _require_stable_id(raw, field="session_id", filename_bearing=True)



class SlashRequest(BaseModel):
	name: str = Field(max_length=64)
	arg: str = Field(default="", max_length=4000)
	session_id: str | None = Field(default=None, max_length=128)
	workspace: str | None = Field(default=None, max_length=1024)
	provider: str | None = Field(default=None, max_length=32)
	base_url: str | None = Field(default=None, max_length=512)
	model: str | None = Field(default=None, max_length=128)


@router.post("/v1/slash")
def slash_command(
	body: SlashRequest,
	request: Request,
	authorization: str | None = Header(default=None),
	x_provider: str | None = Header(default=None, alias="X-Provider"),
	x_base_url: str | None = Header(default=None, alias="X-Base-Url"),
) -> dict[str, Any]:
	require_loopback(request)
	cmd = get_command(body.name)
	if cmd is None:
		result = CommandResult(
			handled=False, kind="unknown", message=f"未知命令 /{body.name}，试试 /help。"
		)
	elif cmd.handler != "server":
		result = CommandResult(
			handled=False,
			kind="unknown",
			message=f"/{cmd.name} 由界面本地处理，不应发送到服务端。",
		)
	else:
		# 身份与工作区在边缘按固定点校验，再构造 ctx（dispatch 的 ``_workspace``
		# 原样透传 ctx.workspace，任何相对写法都会按**本进程 cwd**解析）。
		arg = _require_stable_arg(cmd.name, body.arg or "")
		workspace = require_workspace_arg(body.workspace)
		session_id = _require_slash_session_id(body.session_id)
		provider = (body.provider or x_provider or "deepseek").lower()
		ctx = DispatchContext(
			session_id=session_id,
			workspace=workspace,
			provider=provider,
			api_key=_extract_bearer(authorization) or "",
			base_url=_resolve_base_url(provider, body.base_url or x_base_url) or "",
			model=(body.model or "").strip(),
		)
		result = dispatch_command(cmd, arg, ctx=ctx)
		# /goal 是能在「还没有任何轮次」的会话上落盘的服务端命令：目标写进
		# ctx.workspace 的 GoalStore，而 goals 读侧（GET/PATCH/round-driver 走
		# ``_require_known_session``）要求 pool 认识这个会话 —— 新会话的 id 由前端
		# 自造，首个 chat 请求之前两边都不满足，回读必然 404（写侧 200、读侧 404，
		# 条带挂不出来）。在边缘把「会话 → 工作区」登记进 pool（与首个 chat 请求
		# 同一张表、同一 first-write-wins 语义），读写两侧解析到同一个 store。
		if (
			cmd.name == "goal"
			and session_id
			and workspace
			and result.handled
			and isinstance(result.result, dict)
			and result.result.get("ok") is True
		):
			try:
				_pool.pin_session_cwd(session_id, workspace)
			except Exception:  # noqa: BLE001 — 登记失败不推翻已完成的写入，只影响回读
				_logger.warning(
					"goal session pin failed for session %s", session_id, exc_info=True
				)
	if result.result is not None and not isinstance(result.result, dict):
		result.result = {"value": result.result}
	return {
		"handled": result.handled,
		"kind": result.kind,
		"message": result.message,
		"result": result.result,
	}
