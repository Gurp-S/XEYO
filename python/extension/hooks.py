"""插件生命周期钩子执行器（子进程，短超时，三分结果，PermissionRequest fail-closed）。

事件（Subagent*/UserPromptSubmit/PrePostCompact 预留）：
``PreToolUse`` / ``PostToolUse`` / ``PermissionRequest`` / ``SessionStart`` / ``SessionEnd``。

开关：:meth:`ExtensionConfig.hooks_enabled`（扩展层主开关 && hooks 主开关，**默认关**）。
关闭时本模块零执行、零注入（旁路形态，逐位 = 停产）。

结果三分：``Success``（exit 0）/ ``FailedContinue``（非零且
``fail_policy=continue``）/ ``FailedAbort``（非零且 ``fail_policy=abort`` **或超时**）。
``PermissionRequest`` 任一非 Success → fail-closed DENY（短路工具调用，绝不静默放行）。

附加上下文：钩子 stdout 作为**可选**上下文块经 ``extension.reconcile.publish_reconcile_block``
注入（走 T_now 管线，事件类静默即失，绝不门控）。

执行环境安全：子进程环境剥离仓库级 ``GIT_*``（复用 :func:`plugin_fetcher.scrub_git_env`），
并注入 ``XEYO_HOOK_CONTEXT``（JSON）。``command`` 相对插件根（manifest 已校验禁越界）。

本模块不自含调度/主循环；只在工具门禁 / 会话边界的**接缝**被调用（AGENTS.md 反巨石：
新逻辑进新模块，巨石仅留调点）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from extension.config import ExtensionConfig, load_ext_config
from extension.loader import discover_plugins
from extension.plugin_fetcher import scrub_git_env

_log = logging.getLogger(__name__)

EVENTS = ("PreToolUse", "PostToolUse", "PermissionRequest", "SessionStart", "SessionEnd")

#: hooks 生效所需的总开关 + 依赖的 manifest / 配置。
_DEFAULT_TIMEOUT_S = 600.0


@dataclass(frozen=True)
class PluginHook:
	"""一个启用插件的具体钩子（含可执行路径）。"""

	plugin_name: str
	event: str
	command: Path  # 已校验的绝对可执行路径（位于插件根内）
	args: tuple[str, ...] = ()
	timeout_s: float = _DEFAULT_TIMEOUT_S
	fail_policy: str = "continue"


@dataclass
class HookOutcome:
	status: str  # "success" | "continue" | "abort" | "skipped"
	blocks: list[str] = field(default_factory=list)  # 注入的上下文块
	errors: list[str] = field(default_factory=list)  # 记录用途

	@property
	def should_abort(self) -> bool:
		return self.status == "abort"


def hooks_enabled(cwd: str | None, *, config: ExtensionConfig | None = None) -> bool:
	cfg = config if config is not None else load_ext_config(cwd)
	return bool(cfg.hooks_enabled())


def _plugin_hooks(cfg: ExtensionConfig, cwd: str | None) -> list[PluginHook]:
	"""聚合全部启用插件声明的 hooks（且插件本身激活 + hooks 总开关开）。"""
	if not cfg.hooks_enabled():
		return []
	out: list[PluginHook] = []
	for lp in discover_plugins(cwd, config=cfg):
		if not lp.enabled:
			continue
		man = lp.plugin.manifest
		root = lp.plugin.root
		for spec in man.hooks:
			cmd = _resolve_command(root, spec.command)
			if cmd is None:
				_log.warning("plugin %s hook %s missing at %s", lp.name, spec.event, cmd)
				continue
			out.append(
				PluginHook(
					plugin_name=lp.name,
					event=spec.event,
					command=cmd,
					args=tuple(spec.args),
					timeout_s=spec.timeout_s,
					fail_policy=spec.fail_policy,
				)
			)
	return out


def _resolve_command(root: Path, rel: str) -> Path | None:
	p = (root / rel).resolve()
	try:
		p.relative_to(root.resolve())
	except ValueError:
		return None
	return p if p.is_file() else None


def _outcome_for(result: dict[str, Any], hook: PluginHook) -> str:
	"""把子进程结果归类为三分状态。"""
	if result["status"] == "timeout":
		# 超时按 fail-closed 归 FailedAbort（PermissionRequest 场景 DENY）。
		return "abort"
	if result["returncode"] == 0:
		return "success"
	return "abort" if hook.fail_policy == "abort" else "continue"


def _run_one_sync(hook: PluginHook, context: dict[str, Any]) -> dict[str, Any]:
	"""同步执行一个钩子（asyncio.to_thread 包装后供 async 接缝调用）。"""
	import subprocess

	env = scrub_git_env()
	env["XEYO_HOOK_CONTEXT"] = json.dumps(context, ensure_ascii=False)
	cmdline = [str(hook.command), *hook.args]
	try:
		proc = subprocess.run(
			cmdline,
			capture_output=True,
			text=True,
			cwd=str(hook.command.parent),
			env=env,
			timeout=hook.timeout_s,
		)
	except subprocess.TimeoutExpired:
		return {"status": "timeout", "stdout": "", "stderr": "timeout"}
	except OSError as e:
		return {"status": "error", "returncode": -1, "stdout": "", "stderr": str(e)}
	return {
		"status": "ok",
		"returncode": proc.returncode,
		"stdout": proc.stdout or "",
		"stderr": proc.stderr or "",
	}


def run_event_hooks(
	event: str,
	cwd: str | None,
	context: dict[str, Any] | None = None,
	*,
	config: ExtensionConfig | None = None,
) -> HookOutcome:
	"""运行某事件的全部启用钩子；返回三分结果 + 待注入上下文块。"""
	cfg = config if config is not None else load_ext_config(cwd)
	if not cfg.hooks_enabled() or event not in EVENTS:
		return HookOutcome(status="skipped")
	context = context or {}
	hooks = [h for h in _plugin_hooks(cfg, cwd) if h.event == event]
	if not hooks:
		return HookOutcome(status="skipped")
	from extension.reconcile import publish_reconcile_block

	blocks: list[str] = []
	errors: list[str] = []
	last_status = "success"
	aborted = False
	for hook in hooks:
		try:
			res = _run_one_sync(hook, context)
		except Exception as exc:  # noqa: BLE001
			errors.append(f"{hook.plugin_name}:{hook.event} {exc}")
			last_status = "continue"
			continue
		status = _outcome_for(res, hook)
		last_status = status
		stdout = str(res.get("stdout") or "").strip()
		if stdout and status != "abort":
			blk = _format_block(hook, stdout)
			blocks.append(blk)
			publish_reconcile_block(blk)
		if status == "abort":
			aborted = True
			# abort 仍记录前序上下文（放行前的观测），但整体短路。
			break
	if aborted:
		return HookOutcome(status="abort", blocks=blocks, errors=errors)
	return HookOutcome(status=last_status if blocks else "success", blocks=blocks, errors=errors)


def _format_block(hook: PluginHook, stdout: str) -> str:
	title = {
		"PreToolUse": "工具调用前",
		"PostToolUse": "工具调用后",
		"PermissionRequest": "权限请求",
		"SessionStart": "会话开始",
		"SessionEnd": "会话结束",
	}.get(hook.event, hook.event)
	body = stdout[:800]
	return (
		f"# 插件钩子·{title}（background only — 来自插件 {hook.plugin_name}，非用户新提问）\n"
		f"{body}"
	)


# --------------------------------------------------------------------------- #
# async 接缝（工具门禁；用 to_thread 避免阻塞事件循环）
# --------------------------------------------------------------------------- #

async def run_event_hooks_async(
	event: str,
	cwd: str | None,
	context: dict[str, Any] | None = None,
	*,
	config: ExtensionConfig | None = None,
) -> HookOutcome:
	return await asyncio.to_thread(run_event_hooks, event, cwd, context, config=config)
