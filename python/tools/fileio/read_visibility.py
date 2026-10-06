"""Read 去重依据：规范范围与实际投影中完整可见的正文；不改变写权限。"""
from __future__ import annotations

import hashlib

from prompt.fence import fence_tool_output, unwrap_tool_output


def view_digest(text: str) -> str:
	# 与发送侧同源，密钥过滤/围栏转义不会误使正文判为不可见。
	inner, _ = unwrap_tool_output(fence_tool_output("Read", text))
	return hashlib.sha256(inner.encode("utf-8")).hexdigest()


def sync_read_visibility(registry, projected: list[dict]) -> None:
	from engine.compact import build_tool_use_names
	from tools.catalog import shared_read_state

	names = build_tool_use_names(projected)

	def relevant(text, name):
		# 有明确工具身份时只查 Read；缺失身份保持旧的保守核对路径。
		name = name or unwrap_tool_output(text)[1]
		return not name or name == "Read"

	digests = set()
	for row in projected:
		if row.get("role") == "tool" and isinstance(row.get("content"), str):
			if relevant(row["content"], row.get("name") or names.get(row.get("tool_call_id"))):
				digests.add(view_digest(row["content"]))
		content = row.get("content")
		if isinstance(content, list):
			for block in content:
				if isinstance(block, dict) and block.get("type") == "tool_result" and not block.get("is_error"):
					text = str(block.get("content") or "")
					if relevant(text, names.get(block.get("tool_use_id"))):
						digests.add(view_digest(text))
	shared_read_state(registry).sync_visible_views(digests)
