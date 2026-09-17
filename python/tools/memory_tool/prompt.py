"""memory_tool 描述文本。

路径用稳定占位符，不把绝对路径写进 tools schema，避免每个 workspace
的 tools 前缀字节都不同、无法共享 KV。
"""


def build_description(mem: str = "", sess: str = "") -> str:
	_ = mem, sess  # 保留签名兼容；schema 不再嵌入绝对路径
	return (
		"Long-term workspace memory. "
		"action=search returns matching durable notes and labeled session notes "
		"from this workspace; results include prior context, user preferences, "
		"and earlier decisions when present. "
		"the same search also scans session notes of other conversations "
		"in this workspace, so cross-chat context (what other sessions "
		"discussed) comes back labeled by conversation. "
		"action=peers: list other active sessions in this workspace "
		"(busy / owned files / current topic), pulled on demand. "
		"action=write: store a durable fact (type+content). "
		"action=update/forget: change or tombstone by id. "
		"action=retrieve: restore verbatim compressed-out content (C2 escape-hatch "
		"fragments) by anchor id notes:msg:<index> shown in [C2] summary lines / "
		"citation anchors. "
		"Durable memory records facts and decisions; directory trees and one-off "
		"plans are not durable memory records. "
		"MEMORY.md is an index; details are in topics/*.md."
	)
