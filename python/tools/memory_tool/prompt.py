"""memory_tool 描述文本。

路径用稳定占位符，不把绝对路径写进 tools schema，避免每个 workspace
的 tools 前缀字节都不同、无法共享 KV。
"""


def build_description(mem: str = "", sess: str = "") -> str:
	_ = mem, sess  # 保留签名兼容；schema 不再嵌入绝对路径
	return (
		"Long-term workspace memory. "
		"action=search: recall notes (prefer over Grep on memdir); "
		"call it first before answering questions that depend on prior "
		"context, user preferences, or earlier decisions; "
		"the same search also scans session notes of other conversations "
		"in this workspace, so cross-chat context (what other sessions "
		"discussed) comes back labeled by conversation. "
		"action=peers: list other active sessions in this workspace "
		"(busy / owned files / current topic), pulled on demand — "
		"call it when you need to know what other sessions are doing "
		"instead of assuming from background notices. "
		"action=write: store a durable fact (type+content). "
		"action=update/forget: change or tombstone by id. "
		"action=retrieve: restore verbatim compressed-out content (C2 escape-hatch "
		"fragments) by anchor id notes:msg:<index> shown in [C2] summary lines / "
		"citation anchors — use it when a compacted error stack or file path "
		"matters and you need the original bytes. "
		"Do not store directory trees or one-off plans. "
		"MEMORY.md is an index; details are in topics/*.md."
	)
