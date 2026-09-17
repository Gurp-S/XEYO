"""工具结果的 diff 摘要化——模型可见面瘦身（2026-09-16）。

背景
----
Edit / Write 的结果文本末尾挂一段 ```diff 围栏（``tools/fileio/diff_preview.py``）。
它的消费者是 GUI 的 diff 卡片（``gui/src/lib/toolActivity/todos.ts::extractDiffFence``）；
对模型而言，改动量已由结果首行的事实给出（``The file X has been updated
successfully. +25 -7``），diff 正文是纯重复成本——一轮里连发 N 个 Edit 时按 N 倍
放大，且该成本随之后每一次请求重复支付直到压缩。DSH 的 edit 结果只回一句确认
（diff 只走 UI 侧卡片，见 ``@deepseek-ai/dsh-tool-fs`` 的 presentationMeta）。

接缝
----
剥离发生在**投影送模型**处，与 ``prompt/fence.py`` 的 γ4 围栏同一位置——这是仓库
既有口径：``msgtypes/message.py::tool_result_message`` 的注释明确「模型可见的变换
不写进 MessageStore，以免污染 transcript / ToolResultEvent / UI」。因此本模块只改
投影副本，MessageStore / JSONL / SSE / GUI 的 diff 卡片全部保持原样。

开关（``XEYO_TOOL_RESULT_DIFF``）
--------------------------------
- ``digest``（**默认，主链路**）：剥离 diff 围栏，模型只看到确认行（含 +N -M）
  与其余事实行。
- ``full``（逃生门）：恢复既有行为，diff 正文照常送模型。

未设置 / 非法值一律落 ``digest``（= 默认档）。

功能归属与收益证据（2026-09-16 并入主链路，硬规矩 4）
--------------------------------------------------
- 归属：工具结果模型可见面瘦身；沿用仓库既有口径「模型可见的变换不写进
  MessageStore」（``msgtypes/message.py::tool_result_message``）。
- 证据：真实会话 ``sess_mu3qgq6k_ifm1n5.jsonl``（216 次模型请求、124 条带 diff
  围栏的文件改动结果）：diff 正文合计 104,850 字符（≈26k tokens）首次发送；按
  「每条结果在之后每次请求重发」加权 7.84M 字符·次（≈1.96M tokens）。
- 收益性质：重发多命中 KV 缓存，故收益主要落在**上下文占用 → 压缩更少更晚**，
  不是账单直降。GUI diff 卡片 / transcript / JSONL 均不受影响。
"""

from __future__ import annotations

import os
import re
from typing import Any

MODE_ENV = "XEYO_TOOL_RESULT_DIFF"
MODE_FULL = "full"
MODE_DIGEST = "digest"

#: 只有文件改动类工具的结果才带 diff 围栏。按工具名限定，避免误伤恰好打印
#: ```diff 的 Bash / Grep 输出（那是工具的真实返回数据，不是我们的展示围栏）。
_FILE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})

#: 围栏形状与 diff_preview.append_diff_fence 一致：前导空行 + ```diff + 正文 + ```。
_DIFF_FENCE_RE = re.compile(r"\n*```diff\r?\n[\s\S]*?```[ \t]*", re.IGNORECASE)

#: 投影里 msg["name"] 缺失时的兜底：γ4 围栏自带工具名（fence_tool_output）。
_FENCE_NAME_RE = re.compile(r'<tool_output\s+tool="([^"]*)"', re.IGNORECASE)


def mode() -> str:
	"""当前档位；未设置或非法值一律落默认档 ``digest``，``full`` 为逃生门。"""
	raw = (os.environ.get(MODE_ENV) or "").strip().lower()
	return MODE_FULL if raw == MODE_FULL else MODE_DIGEST


def digest_enabled() -> bool:
	return mode() == MODE_DIGEST


def strip_diff_fence(content: str) -> str:
	"""剥掉 diff 围栏，保留确认行 / ``+N -M`` / Diagnostics 提示。幂等。

	无围栏时原样返回（含 Bash 等工具的任意正文）。
	"""
	text = content if content is not None else ""
	if "```diff" not in text.lower():
		return text
	return _DIFF_FENCE_RE.sub("", text).strip()


def _tool_name(msg: dict[str, Any], block: dict[str, Any], names: dict[str, str]) -> str:
	uid = str(block.get("tool_use_id") or "")
	candidates = (str(msg.get("name") or ""), str(names.get(uid) or ""))
	for name in candidates:
		if name:
			return name
	raw = str(block.get("content") or "")
	m = _FENCE_NAME_RE.search(raw)
	return m.group(1) if m else ""


def apply_tool_result_digest(
	messages: list[dict[str, Any]],
	*,
	id_to_name: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
	"""投影路径：剥离文件改动类工具结果里的 diff 围栏（copy-on-write，幂等）。

	关档 / 无命中时原样返回入参列表（零拷贝、零行为）。
	"""
	if not messages or not digest_enabled():
		return messages
	names = id_to_name or {}
	out: list[dict[str, Any]] = []
	for msg in messages:
		content = msg.get("content")
		if not isinstance(content, list):
			out.append(msg)
			continue
		new_blocks: list[Any] = []
		changed = False
		for block in content:
			if not isinstance(block, dict) or block.get("type") != "tool_result":
				new_blocks.append(block)
				continue
			if _tool_name(msg, block, names) not in _FILE_TOOLS:
				new_blocks.append(block)
				continue
			raw = str(block.get("content") or "")
			digested = strip_diff_fence(raw)
			if digested == raw:
				new_blocks.append(block)
				continue
			changed = True
			nb = dict(block)
			nb["content"] = digested
			new_blocks.append(nb)
		if changed:
			nm = dict(msg)
			nm["content"] = new_blocks
			out.append(nm)
		else:
			out.append(msg)
	return out
