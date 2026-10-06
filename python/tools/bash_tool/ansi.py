"""终端转义序列剥离：只删 CSI 渲染指令，不删正文。

为什么需要：宿主 Bash 的输出直接进模型注意力，PowerShell 的 Format-Table 表头、
错误流、``Write-Host`` 都带 SGR 序列（实测 2026-10-03 会话 sess_mur8ilhk_zz7jt9
行 3 / 行 9 里就是 ``\\x1b[31;1m`` / ``\\x1b[0m``）。这些字节对模型是不可用噪声，
还把「红=失败、绿=成功」这类只有终端能表达的含义变成无法解析的碎串。

作用面按**实测到的形状**收：只剥 CSI（``ESC [ + 参数 + 中间字节 + 最终字节``，含
SGR / 光标 / 清屏）。以下一律不动，因为剥它们是丢信息而不是丢噪声——
- OSC（``\\x1b]8;;<url>\\a``）：超链接的目标 URL 只存在于序列内部；
- 孤立 ``\\x1b``：无法判定是否为被截断的序列，保守保留。
"""

from __future__ import annotations

import re

#: CSI：ESC [ + 参数（0-9 ; ?）+ 中间字节（空格~/）+ 最终字节（@~）。
_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
	"""剥离 CSI 序列；不含 ESC 的输入原样返回（零改动）。"""
	if "\x1b" not in text:
		return text
	return _CSI_RE.sub("", text)
