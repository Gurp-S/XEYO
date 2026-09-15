"""突触压缩（Workflow Synaptic Compression, WSC）。

旁路形态：本包不 import 任何生产链模块（``engine`` / ``memory`` / ``server``），
``python/tests/synaptic/test_isolation.py`` 机器执法。融入主链时只需在外层加
一个开关 + 一个接线点；验证失败时整目录删除即可。

一句话：把膨胀的执行历史，压缩成一份可继续工作的**最小充分状态**。
"""

from __future__ import annotations

from synaptic.assemble import AssemblyState, build_pins, pick_level
from synaptic.coldstore import ColdStore, branch_handle, node_handle, parse_handle
from synaptic.graph import Graph, build_graph, graph_digest
from synaptic.project import Projection, default_params, project
from synaptic.types import (
	LEVEL_WATERMARK,
	LEVELS,
	MODE_APPEND_ONLY,
	MODE_CLOSURE,
	FileState,
	HotLayer,
	Level,
	Node,
	Pin,
	PruneCard,
	WscParams,
	WscResult,
)

__all__ = [
	"GRAPH_EXPORTS",
	"LEVELS",
	"LEVEL_WATERMARK",
	"MODE_APPEND_ONLY",
	"MODE_CLOSURE",
	"AssemblyState",
	"ColdStore",
	"FileState",
	"Graph",
	"HotLayer",
	"Level",
	"Node",
	"Pin",
	"Projection",
	"PruneCard",
	"WscParams",
	"WscResult",
	"branch_handle",
	"build_graph",
	"build_pins",
	"default_params",
	"graph_digest",
	"node_handle",
	"parse_handle",
	"pick_level",
	"project",
]

GRAPH_EXPORTS = ("build_graph", "graph_digest", "project", "default_params")
