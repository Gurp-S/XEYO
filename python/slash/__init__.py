"""XEYO 统一斜杠命令：单一事实源 manifest + 服务端 dispatcher。

铁律（见根目录 AGENTS.md）：
- 命令元数据只在 registry 声明一次；GUI / CLI-Py / CLI-TS / 远程通道都消费同一份
  manifest。改动后必须重跑 ``py -3.11 -m slash.export_manifest`` 并提交生成物。
- handler=client 的命令由发起面本地处理；handler=server 的命令由后端统一执行。
- 模式/精简类命令只改「下一轮请求体 / contextvar」，绝不写回 MessageStore / JSONL，
  也不进 system 左段（易变上下文走 T_now 注入管线）。
"""

from __future__ import annotations

from .dispatch import (
	CommandResult,
	DispatchContext,
	build_help,
	dispatch,
	dispatch_command,
)
from .registry import (
	COMMANDS,
	SURFACES,
	Category,
	Command,
	HandlerKind,
	When,
	get_command,
	help_text,
	is_slash_command,
	match_commands,
	parse_slash,
)

__all__ = [
	"COMMANDS",
	"SURFACES",
	"Category",
	"Command",
	"CommandResult",
	"DispatchContext",
	"HandlerKind",
	"When",
	"build_help",
	"dispatch",
	"dispatch_command",
	"get_command",
	"help_text",
	"is_slash_command",
	"match_commands",
	"parse_slash",
]
