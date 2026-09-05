"""XEYO 统一斜杠命令 manifest —— 单一事实源。

所有消费方（GUI / CLI-Py / CLI-TS / 远程通道）读本清单，保证命令名、别名、类别、
帮助文案、可用面一致。**不要在别处再写一份命令表**；新增命令只改这里。

约定：
- ``name``：规范化命令名（小写、无前导斜杠、无参数）。
- ``aliases``：额外匹配名（去掉前导斜杠、小写）；含中文自然别名（XEYO 风格）与
  少数通用短别名（/help → h / ?）。**别名全局唯一**，不得跨命令重复。
- ``handler``：``client`` = 发起面本地处理；``server`` = 后端 ``slash.dispatch`` 执行。
- ``surfaces``：哪些面展示 / 接受该命令（gui / cli / cli_ts / remote）。
- ``when``：``idle`` = 会话空闲才可执行；``always`` = 运行中也允许（/stop /allow /deny）。

新增命令步骤：
1. 在此追加一个 ``Command`` 条目（别名先查重）；
2. 若 ``handler=server``，在 :mod:`slash.dispatch` 注册处理函数；
3. 运行 ``py -3.11 -m slash.export_manifest`` 重新生成 GUI / CLI-TS 的 manifest TS；
4. 更新 ``docs/设计/37-斜杠命令统一设计.md``（帮助文案由 help_text 自动生成）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

Category = Literal[
	"meta",
	"session",
	"mode",
	"info",
	"control",
	"memory",
	"tool",
	"extension",
	"demo",
]
HandlerKind = Literal["client", "server"]
When = Literal["idle", "always"]

# 面标识：gui=Web/Tauri 桌面；cli=Python REPL；cli_ts=TypeScript Ink；remote=微信远程通道
SURFACES: tuple[str, ...] = ("gui", "cli", "cli_ts", "remote")


@dataclass(frozen=True)
class Command:
	name: str
	category: Category
	handler: HandlerKind
	summary: str
	usage: str
	aliases: tuple[str, ...] = ()
	arg_spec: str = ""
	surfaces: tuple[str, ...] = SURFACES
	when: When = "idle"

	def to_dict(self) -> dict:
		return asdict(self)


_COMMANDS: tuple[Command, ...] = (
	# ---------------------------------------------------------------- 元信息
	Command(
		name="help",
		category="meta",
		handler="client",
		summary="显示本帮助列表",
		usage="/help",
		# 帮助/命令：远程通道裸词输入兼容（文件助手旧别名）
		aliases=("h", "?", "帮助", "命令"),
	),
	Command(
		name="version",
		category="meta",
		handler="client",
		summary="显示当前版本",
		usage="/version",
		aliases=("ver",),
	),
	Command(
		name="docs",
		category="meta",
		handler="client",
		summary="打开 XEYO 文档（docs/）",
		usage="/docs",
		aliases=("文档", "资料"),
		surfaces=("gui", "cli_ts"),
	),
	# ------------------------------------------------------------- 会话
	Command(
		name="clear",
		category="session",
		handler="client",
		summary="新建会话（清空当前对话）",
		usage="/clear",
		aliases=("reset", "new", "清空", "新会话"),
	),
	Command(
		name="load",
		category="session",
		handler="client",
		summary="载入历史会话",
		usage="/load <session_id>",
		aliases=("载入", "打开会话"),
		arg_spec="sid",
		surfaces=("cli", "cli_ts"),
	),
	Command(
		name="export",
		category="session",
		handler="server",
		summary="导出当前会话为 Markdown 文件",
		usage="/export <file.md>",
		aliases=("导出", "存档"),
		arg_spec="file",
	),
	Command(
		name="retry",
		category="session",
		handler="client",
		summary="重发上一条消息（重试）",
		usage="/retry",
		aliases=("重试", "再来"),
	),
	Command(
		name="goal",
		category="session",
		handler="server",
		summary="创建/绑定当前会话目标（显式新建 goal）",
		usage="/goal <目标>",
		aliases=("目标",),
		arg_spec="text",
	),
	Command(
		name="exit",
		category="session",
		handler="client",
		summary="退出 REPL",
		usage="/exit",
		aliases=("quit", "q"),
		surfaces=("cli", "cli_ts"),
	),
	# ---------------------------------------------------------------- 模式
	Command(
		name="mode",
		category="mode",
		handler="client",
		summary="切换 Agent 模式：agent / plan / ask",
		usage="/mode <agent|plan|ask>",
		aliases=("模式",),
		arg_spec="m",
	),
	Command(
		name="output",
		category="mode",
		handler="client",
		summary="切换「输出精简」档位：lite / full / ultra / off",
		usage="/output [lite|full|ultra|off]",
		aliases=("out", "输出", "精简"),
		arg_spec="lvl",
	),
	Command(
		name="code",
		category="mode",
		handler="client",
		summary="切换「写代码精简」档位：lite / full / ultra / off",
		usage="/code [lite|full|ultra|off]",
		aliases=("代码", "写码"),
		arg_spec="lvl",
	),
	Command(
		name="reasoning-tail",
		category="mode",
		handler="client",
		summary="切换「上一轮思考回顾」注入：on / off",
		usage="/reasoning-tail <on|off>",
		aliases=("思考回顾", "推理回顾"),
		arg_spec="m",
	),
	Command(
		name="model",
		category="mode",
		handler="client",
		summary="切换模型档位",
		usage="/model <model_id>",
		aliases=("模型", "档位"),
		arg_spec="id",
	),
	Command(
		name="theme",
		category="mode",
		handler="client",
		summary="切换界面主题",
		usage="/theme <theme_id>",
		aliases=("主题",),
		arg_spec="id",
		surfaces=("gui",),
	),
	Command(
		name="approval",
		category="mode",
		handler="client",
		summary="设置审批模式：always / risk / never",
		usage="/approval <always|risk|never>",
		aliases=("审批", "审批模式"),
		arg_spec="m",
	),
	# ---------------------------------------------------------------- 信息
	Command(
		name="status",
		category="info",
		handler="server",
		summary="显示会话 / 任务 / 挂起请求状态",
		usage="/status",
		# 状态：远程通道裸词输入兼容
		aliases=("状态",),
	),
	Command(
		name="usage",
		category="info",
		handler="server",
		summary="显示用量统计（厂商权威 + 本机账本）",
		usage="/usage [days]",
		arg_spec="days",
	),
	Command(
		name="context",
		category="info",
		handler="server",
		summary="查看当前上下文（压缩游标 / 摘要 / todos）",
		usage="/context",
		aliases=("ctx", "上下文"),
	),
	Command(
		name="cwd",
		category="info",
		handler="server",
		summary="显示当前工作区路径",
		usage="/cwd",
		aliases=("pwd", "目录", "工作目录", "路径"),
	),
	Command(
		name="ls",
		category="info",
		handler="server",
		summary="列出工作区目录（只读）",
		usage="/ls [dir]",
		aliases=("dir", "列目录"),
		arg_spec="dir",
		surfaces=("gui", "cli"),
	),
	# ------------------------------------------------------------- 控制
	Command(
		name="stop",
		category="control",
		handler="server",
		summary="中断正在运行的任务",
		usage="/stop",
		aliases=("停止", "中断"),
		when="always",
	),
	Command(
		name="allow",
		category="control",
		handler="server",
		summary="批准当前待确认的操作",
		usage="/allow [request_id]",
		aliases=("允许", "同意", "approve"),
		arg_spec="rid",
		when="always",
	),
	Command(
		name="deny",
		category="control",
		handler="server",
		summary="拒绝当前待确认的操作",
		usage="/deny [request_id]",
		aliases=("拒绝", "不允许", "reject"),
		arg_spec="rid",
		when="always",
	),
	# -------------------------------------------------------------- 记忆
	Command(
		name="compact",
		category="memory",
		handler="server",
		summary="强制记忆压缩（C2 游标前移）",
		usage="/compact",
		aliases=("压缩",),
	),
	Command(
		name="transcript",
		category="memory",
		handler="server",
		summary="回放本会话最近消息",
		usage="/transcript [n]",
		aliases=("history", "历史", "回放"),
		arg_spec="n",
	),
	Command(
		name="rule",
		category="memory",
		handler="server",
		summary="向工作区 XEYO.md 追加一行规则（用户发起）",
		usage="/rule <条文>",
		aliases=("规则", "记住"),
		arg_spec="line",
		surfaces=("gui", "remote"),
	),
	Command(
		name="doctor",
		category="memory",
		handler="server",
		summary="检查 XEYO.md 是否过长 / 可推导 / 坏 include",
		usage="/doctor",
		aliases=("体检", "检查规则"),
		surfaces=("gui", "remote"),
	),
	Command(
		name="proposals",
		category="memory",
		handler="server",
		summary="查看待确认的 XEYO.md 写入提案",
		usage="/proposals",
		aliases=("提案", "规则提案"),
		surfaces=("gui", "remote"),
	),
	# ---------------------------------------------------------------- 工具
	Command(
		name="run",
		category="tool",
		handler="client",
		summary="让 Agent 用 Bash 工具执行命令（走权限门禁）",
		usage="/run <command>",
		aliases=("bash", "执行", "跑命令"),
		arg_spec="cmd",
	),
	Command(
		name="git",
		category="tool",
		handler="server",
		summary="Git 只读操作：status / log / branch",
		usage="/git <status|log|branch>",
		arg_spec="op",
	),
	Command(
		name="diff",
		category="tool",
		handler="server",
		summary="显示工作区 git 差异摘要",
		usage="/diff [rev]",
		aliases=("差异", "区别"),
		arg_spec="rev",
	),
	Command(
		name="revert",
		category="tool",
		handler="server",
		summary="回溯恢复到某 checkpoint（需二次确认）",
		usage="/revert [rewind_id] [confirm]",
		aliases=("rollback", "回退", "撤销", "还原"),
		arg_spec="id",
	),
	# ----------------------------------------------------------- 扩展
	Command(
		name="skills",
		category="extension",
		handler="server",
		summary="技能列表 / 详情（workspace > home > plugin）",
		usage="/skills [show <name>]",
		aliases=("skill", "技能"),
		arg_spec="q",
	),
	Command(
		name="mcp",
		category="extension",
		handler="server",
		summary="MCP 服务器列表 / 启停 / 单工具勾选",
		usage="/mcp [list|status|enable|disable <id>|tool <id> <raw> <on|off>]",
	),
	Command(
		name="plugins",
		category="extension",
		handler="server",
		summary="插件列表 / 启停 / 安装管理",
		usage="/plugins [list|enable|disable <name>|install <source> [update]|update <name>|remove <name>]",
		aliases=("插件",),
		arg_spec="op",
	),
)

_NAMES: dict[str, Command] = {c.name: c for c in _COMMANDS}
_ALIAS_INDEX: dict[str, Command] = {}
for _c in _COMMANDS:
	_ALIAS_INDEX[_c.name] = _c
	for _a in _c.aliases:
		_prev = _ALIAS_INDEX.get(_a)
		if _prev is not None and _prev is not _c:
			raise RuntimeError(
				f"slash alias conflict: {_a!r} 已属于 /{_prev.name}，"
				f"不能同时给 /{_c.name}（registry 别名必须全局唯一）"
			)
		_ALIAS_INDEX[_a] = _c

COMMANDS: tuple[Command, ...] = _COMMANDS


def _norm_key(text: str) -> str:
	"""去掉前导斜杠与首尾空白并小写，作为命令/别名匹配的键。"""
	return ((text or "").strip().lstrip("/")).lower()


def is_slash_command(text: str) -> bool:
	return (text or "").strip().startswith("/")


def get_command(text: str) -> Command | None:
	"""按命令名或别名取命令；未匹配返回 None（只匹配第一个 token）。"""
	key = _norm_key(text)
	if not key:
		return None
	key = key.split(None, 1)[0]
	return _ALIAS_INDEX.get(key)


def parse_slash(text: str) -> tuple[Command | None, str]:
	"""把一行拆成 (命令, 参数串)。

	- 不以 / 开头：返回 ``(None, "")``。
	- 已知命令：返回 ``(命令, 剩余参数串)``。
	- 未知 /xxx：返回 ``(None, 去掉前导斜杠后的整串)``，由调用面按「未知命令」处理。
	"""
	raw = (text or "").strip()
	if not raw.startswith("/"):
		return None, ""
	body = raw[1:].strip()
	if not body:
		return None, ""
	parts = body.split(None, 1)
	cmd = _ALIAS_INDEX.get(parts[0].lower())
	if cmd is None:
		return None, body
	arg = parts[1].strip() if len(parts) > 1 else ""
	return cmd, arg


def match_commands(
	prefix: str, *, surfaces: tuple[str, ...] = SURFACES
) -> list[Command]:
	"""按前缀返回候选命令（自动补全），按 (类别, 名字) 排序；按可用面过滤。"""
	p = (prefix or "").strip().lstrip("/").lower()
	out: list[Command] = []
	for c in _COMMANDS:
		if p and not (c.name.startswith(p) or any(a.startswith(p) for a in c.aliases)):
			continue
		if any(s in c.surfaces for s in surfaces):
			out.append(c)
	out.sort(key=lambda c: (c.category, c.name))
	return out


_CATEGORY_ZH: dict[str, str] = {
	"meta": "通用",
	"session": "会话",
	"mode": "配置",
	"info": "状态",
	"control": "控制",
	"memory": "记忆",
	"tool": "工具",
	"extension": "扩展",
	"demo": "演示",
}


def help_text(*, surfaces: tuple[str, ...] = SURFACES) -> str:
	"""面向用户的帮助文案（按可用面过滤；类别分组）。"""
	groups: dict[str, list[str]] = {}
	for c in _COMMANDS:
		if not any(s in c.surfaces for s in surfaces):
			continue
		alias_note = ""
		if c.aliases:
			alias_note = "（" + "/".join(c.aliases[:3]) + "）"
		groups.setdefault(_CATEGORY_ZH.get(c.category, c.category), []).append(
			f"{c.usage:<32} {c.summary}{alias_note}"
		)
	lines: list[str] = ["可用斜杠命令："]
	for cat in sorted(groups):
		lines.append(f"● {cat}")
		lines.extend(groups[cat])
	return "\n".join(lines)


__all__ = [
	"COMMANDS",
	"SURFACES",
	"Category",
	"Command",
	"HandlerKind",
	"When",
	"is_slash_command",
	"get_command",
	"parse_slash",
	"match_commands",
	"help_text",
]
