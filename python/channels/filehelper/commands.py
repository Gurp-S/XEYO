"""File Helper 侧指令（不进模型）—— 统一 manifest 的远程面。

命令元数据与别名来自 :mod:`slash.registry`（中文别名即远程用户裸词输入）；
``rule / doctor / proposals`` 执行委托 :func:`slash.dispatch`。通道特有逻辑
（截图识别 / 系统提示补写）保留在此。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from slash.registry import get_command, help_text as registry_help_text

# 远程通道（文件传输助手 / iLink）当前受理的命令白名单：
# service 侧各自实现了 status/cwd/stop/allow/deny；rule/doctor/proposals 走 dispatch。
# compact / transcript 等其余 server 命令暂不下放远程（保持既有行为）。
_REMOTE_COMMANDS = frozenset({
	"help", "status", "cwd", "stop", "allow", "deny",
	"rule", "doctor", "proposals",
})

_SHOT_RE = re.compile(
	r"截图|/screenshot\b|\bscreenshot\b|看(?:一下|看)?(?:屏幕|桌面)",
	re.I,
)

_RULE_RE = re.compile(
	r"^(?:/?(?:rule|规则|记住))\s+(.+)$",
	re.I | re.S,
)


@dataclass(frozen=True)
class CommandHit:
	name: str
	arg: str = ""


def parse_command(text: str) -> CommandHit | None:
	"""把一条远程消息解析为命令；非命令返回 None（交给模型）。

	匹配顺序：
	1. ``/rule <条文>``（及裸词「规则/记住 <条文>」）——带参数的规则行；
	2. 带 ``/`` 的斜杠命令（registry 全别名）；
	3. 整条消息恰好等于某个命令名/别名（裸中文词，如「状态」「停止」）。
	仅接受 :data:`_REMOTE_COMMANDS` 白名单内的命令。
	"""
	raw = (text or "").strip()
	if not raw:
		return None
	# 1) rule <line>
	m = _RULE_RE.match(raw)
	if m:
		return CommandHit(name="rule", arg=m.group(1).strip())
	# 2) /xxx
	if raw.startswith("/"):
		from slash.registry import parse_slash

		cmd, arg = parse_slash(raw)
		if cmd is not None and cmd.name in _REMOTE_COMMANDS:
			return CommandHit(name=cmd.name, arg=arg)
		return None
	# 3) 裸词 = 整条消息恰为命令名/别名（registry 的中文别名即此用途）
	cmd = get_command(raw)
	if cmd is not None and cmd.name in _REMOTE_COMMANDS:
		return CommandHit(name=cmd.name, arg="")
	return None


def is_screenshot_command(text: str) -> bool:
	# 截图不进统一 manifest：由自然语言识别交给模型 Screenshot 工具。
	hit = parse_command(text)
	return hit is not None and hit.name == "screenshot"


def looks_like_screenshot_request(text: str) -> bool:
	t = (text or "").strip()
	if not t or parse_command(t) is not None:
		return False
	return _SHOT_RE.search(t) is not None


def with_screenshot_nudge(text: str) -> str:
	"""截图类请求附加系统提示，避免模型复读「请改用文件助手」。"""
	t = (text or "").strip()
	if not looks_like_screenshot_request(t):
		return t
	return (
		f"{t}\n\n"
		"[系统] 请立刻调用 Screenshot 工具查看用户屏幕。"
		"截图在 ClawBot/iLink 与文件传输助手上都可用；"
		"不要让用户切换通道，不要说无法截图。"
	)


def help_text() -> str:
	"""远程帮助文案 —— registry 生成，按远程白名单过滤。"""
	body = registry_help_text(surfaces=("remote",))
	out: list[str] = ["可用指令（发给文件传输助手即可）："]
	for ln in body.splitlines()[1:]:
		stripped = ln.strip()
		if not stripped:
			continue
		usage = stripped.split(None, 1)[0]
		cmd = get_command(usage)
		if cmd is None or cmd.name not in _REMOTE_COMMANDS:
			continue
		out.append(stripped)
	out.append(
		"其它文字会交给 XEYO（可用 Screenshot 看屏幕、SendToWeChat 把文件发到手机），"
		"完成后只回最终结果。"
	)
	return "\n".join(out)


def handle_instruction_command(name: str, arg: str = "") -> str | None:
	"""rule / doctor / proposals —— 委托统一 dispatcher；未知返回 None。"""
	if name not in _REMOTE_COMMANDS:
		return None
	try:
		from engine.workspace_context import get_cwd

		cwd = get_cwd()
	except Exception:
		cwd = ""
	from slash.dispatch import DispatchContext, dispatch

	res = dispatch(name, arg, ctx=DispatchContext(workspace=cwd or "."))
	return res.message or None
