"""把运行时审计事件归并为一条可查询的证据链。

Trace 是 derived data：它不拥有会话、工具或进程状态，也不参与调度。
输入只允许来自审计事件，输出只保留身份/状态字段，不保存命令、工具参数、
提示词或结果正文。这样诊断可以回答“哪一版投影触发了哪次工具调用”，同时
不会把敏感工作内容复制进第二份日志。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable


SCHEMA_VERSION = 1
_MAX_TEXT = 160


def _text(value: Any) -> str:
	return str(value or "")[:_MAX_TEXT]


def _digest(*parts: Any) -> str:
	payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
	return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()[:24]


@dataclass(frozen=True)
class TraceNode:
	"""一个可归因的运行实体或审计事件。"""

	node_id: str
	kind: str
	fields: dict[str, Any] = field(default_factory=dict)

	def to_dict(self) -> dict[str, Any]:
		return {"id": self.node_id, "kind": self.kind, "fields": dict(self.fields)}


@dataclass(frozen=True)
class TraceEdge:
	source: str
	target: str
	kind: str

	def to_dict(self) -> dict[str, str]:
		return {"source": self.source, "target": self.target, "kind": self.kind}


class TraceGraph:
	"""有界、只读友好的审计证据图。"""

	def __init__(self, *, session_id: str = "") -> None:
		self.session_id = _text(session_id)
		self._nodes: dict[str, TraceNode] = {}
		self._edges: set[tuple[str, str, str]] = set()

	def add_node(self, node_id: str, kind: str, **fields: Any) -> str:
		node_id = _text(node_id)
		if not node_id:
			return ""
		clean = {key: value for key, value in fields.items() if value not in (None, "")}
		old = self._nodes.get(node_id)
		if old is None:
			self._nodes[node_id] = TraceNode(node_id, _text(kind), clean)
		elif clean:
			merged = dict(old.fields)
			merged.update(clean)
			self._nodes[node_id] = TraceNode(old.node_id, old.kind, merged)
		return node_id

	def add_edge(self, source: str, target: str, kind: str) -> None:
		if source and target and source != target:
			self._edges.add((_text(source), _text(target), _text(kind)))

	@classmethod
	def from_audit_rows(
		cls,
		rows: Iterable[dict[str, Any]],
		*,
		session_id: str = "",
		max_events: int = 200,
	) -> "TraceGraph":
		"""从审计行构建图；接受新→旧或旧→新的输入顺序。"""
		selected: list[tuple[int, dict[str, Any]]] = []
		wanted = _text(session_id)
		for ordinal, row in enumerate(rows):
			if not isinstance(row, dict):
				continue
			if wanted and _text(row.get("session_id")) != wanted:
				continue
			selected.append((ordinal, row))
		selected.sort(key=lambda item: (float(item[1].get("ts") or 0), item[0]))
		selected = selected[-max(0, int(max_events)) :] if max_events else []

		graph = cls(session_id=wanted)
		for ordinal, row in selected:
			kind = _text(row.get("kind")) or "unknown"
			sid = _text(row.get("session_id")) or wanted
			if sid:
				graph.add_node(f"session:{sid}", "session", session_id=sid)

			# event id 只由非敏感审计身份字段和输入序号组成。
			event_key = _digest(
				ordinal,
				row.get("ts"),
				kind,
				row.get("request_id"),
				row.get("model_request_id"),
				row.get("action_id"),
			)
			event_id = graph.add_node(
				f"event:{event_key}",
				"event",
				event_kind=kind,
				ts=row.get("ts"),
				turn_id=_text(row.get("turn_id")),
				status=_text(row.get("status")),
				is_error=bool(row.get("is_error", False)),
				error_kind=_text(row.get("error_kind")),
			)
			if sid:
				graph.add_edge(f"session:{sid}", event_id, "observed")

			projection_id = _text(row.get("projection_id"))
			model_id = _text(row.get("model_request_id"))
			if kind.startswith("model.") and not model_id:
				model_id = _text(row.get("request_id"))
			if projection_id:
				projection_node = graph.add_node(
					f"projection:{projection_id}",
					"projection",
					projection_id=projection_id,
				)
				if sid:
					graph.add_edge(f"session:{sid}", projection_node, "owns")
				if model_id:
					graph.add_edge(projection_node, f"model:{model_id}", "produced")

			if model_id:
				model_node = graph.add_node(
					f"model:{model_id}",
					"model_request",
					model_request_id=model_id,
					attempt=row.get("attempt"),
					provider=_text(row.get("provider")),
					model=_text(row.get("model")),
				)
				if sid:
					graph.add_edge(f"session:{sid}", model_node, "owns")
				graph.add_edge(model_node, event_id, "observed")

			request_id = _text(row.get("request_id"))
			tool_name = _text(row.get("tool_name"))
			if request_id and tool_name:
				tool_node = graph.add_node(
					f"tool:{request_id}",
					"tool_call",
					request_id=request_id,
					tool_name=tool_name,
				)
				if model_id:
					graph.add_edge(f"model:{model_id}", tool_node, "emitted")
				graph.add_edge(tool_node, event_id, "observed")
				action_id = _text(row.get("action_id"))
				if action_id:
					action_node = graph.add_node(
						f"action:{action_id}", "action", action_id=action_id
					)
					graph.add_edge(tool_node, action_node, "dispatches")

		return graph

	def snapshot(self) -> dict[str, Any]:
		nodes = [self._nodes[key].to_dict() for key in sorted(self._nodes)]
		edges = [
			TraceEdge(source, target, kind).to_dict()
			for source, target, kind in sorted(self._edges)
		]
		counts: dict[str, int] = {}
		for node in nodes:
			kind = str(node["kind"])
			counts[kind] = counts.get(kind, 0) + 1
		return {
			"schema_version": SCHEMA_VERSION,
			"session_id": self.session_id,
			"node_counts": counts,
			"nodes": nodes,
			"edges": edges,
		}


__all__ = ["SCHEMA_VERSION", "TraceEdge", "TraceGraph", "TraceNode"]
