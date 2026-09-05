"""纯 token/行数估参（生产热路径与离线 simulator 共用）。

与 ``memory.simulator.state_model`` 的 P0 估参保持一致，避免生产热路径
（``memory/runtime.py``）因 import 整个离线 ``simulator`` 包而拖入实验依赖。
simulator 内仍通过 ``state_model`` 转导出引用本模块，保证单点不漂移。
"""

from __future__ import annotations


def token_len(text: str) -> int:
	"""P0 tokenizer: ceil(utf-8 bytes / 4). Empty → 0."""
	if not text:
		return 0
	return (len(text.encode("utf-8")) + 3) // 4


def n_lines(text: str) -> int:
	if not text:
		return 0
	return text.count("\n") + 1
