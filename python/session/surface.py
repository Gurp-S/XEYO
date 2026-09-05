"""surface — transcript 的模型可见面折叠（replace 事件化回溯的持久层语义）。

surface/generation 模型：
- **append-only JSONL 是唯一真相**，回溯不再重写文件，而是追加一条
  ``surface_op`` marker 行，把「当时可见面」从 ``shadow_from`` 起的区间
  **影子化**（shadow）——原始行永不改写、永不移动。
- 模型可见历史 = 对合并日志（含轮转归档 .old2→.old1→当前）做一次
  ``fold_surface_rows``：marker 消费为区间操作，被影子的行从可见面移除。
- 人类侧（原始文件审计、C2 历史指针侧挂）仍可读到全部 append-origin 行——
  与「模型看 surface、人看 append-origin」的分工一致。
- undo = 追加 ``rewind_undo`` marker（幂等、原子单行追加）。此前 v3 的
  「orphan 先落盘 → transcript 原子替换 → 事件落盘」三步崩溃窗口在语义上
  不再存在：最坏情况是 marker 行写坏半行 → 读取时跳过 → 回溯视为未发生。

marker 行形状（无 id / 无 role，``messages_from_rows`` 天然跳过）::

    {"type": "surface_op", "op": "rewind", "rewind_id": "rw_...",
     "shadow_from": "<可见行 id>", "ts": ...}
    {"type": "surface_op", "op": "rewind_undo", "rewind_id": "rw_...", "ts": ...}

兼容性：
- 旧 transcript 无 marker → fold 恒等。
- v2 路由的物理重写重写掉被影子行后，marker 仍保留（``active_markers``），
  影子区间的首行若已不在可见面，fold 对缺失 id 保守地不隐藏任何行。
"""

from __future__ import annotations

import time
from typing import Any

SURFACE_TYPE = "surface_op"

_OP_REWIND = "rewind"
_OP_REWIND_UNDO = "rewind_undo"


def rewind_marker_row(rewind_id: str, shadow_from: str, *, ts: float | None = None) -> dict[str, Any]:
	"""构造一条「影子化 shadow_from 起至可见面末尾」的回溯 marker。"""
	return {
		"type": SURFACE_TYPE,
		"op": _OP_REWIND,
		"rewind_id": str(rewind_id or ""),
		"shadow_from": str(shadow_from or ""),
		"ts": float(ts if ts is not None else time.time()),
	}


def rewind_undo_marker_row(rewind_id: str, *, ts: float | None = None) -> dict[str, Any]:
	"""构造一条撤销 marker：恢复该 rewind_id 影子化的全部行。"""
	return {
		"type": SURFACE_TYPE,
		"op": _OP_REWIND_UNDO,
		"rewind_id": str(rewind_id or ""),
		"ts": float(ts if ts is not None else time.time()),
	}


def is_surface_marker(row: Any) -> bool:
	return isinstance(row, dict) and row.get("type") == SURFACE_TYPE


def _row_id(row: dict[str, Any]) -> str:
	rid = row.get("id")
	return rid if isinstance(rid, str) else ""


def fold_surface_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
	"""把合并日志折叠为模型可见面（保持时间顺序）。

	- ``rewind``：从可见面**末尾反向**定位 ``shadow_from``，其自身与之后的
	  全部可见行被该 marker 影子化（对齐 v3 「target 一并被移除」语义）。
	- ``rewind_undo``：恢复该 marker 影子化的行。恢复顺序 = 原日志顺序；
	  服务端在追加 undo marker 前已保证「marker 之后无新可见行」，因此
	  extend 不会造成乱序。重复 undo 幂等（只恢复一次）。
	- ``shadow_from`` 不在可见面（如 v2 已物理重写）→ 保守不隐藏任何行。
	- 无 id 的普通行（marker 以外的未知行）原样保留（读侧各按所需过滤）。
	"""
	visible: list[str] = []
	hidden_by: dict[str, list[str]] = {}
	undone: set[str] = set()
	for row in rows:
		if is_surface_marker(row):
			op = str(row.get("op") or "")
			rid = str(row.get("rewind_id") or "")
			if not rid:
				continue
			if op == _OP_REWIND and rid not in undone:
				frm = str(row.get("shadow_from") or "")
				if frm in visible:
					idx = len(visible) - 1 - visible[::-1].index(frm)
					hidden_by[rid] = visible[idx:]
					visible = visible[:idx]
			elif op == _OP_REWIND_UNDO and rid not in undone:
				undone.add(rid)
				back = hidden_by.get(rid)
				if back:
					visible.extend(back)
			continue
		rid = _row_id(row)
		if rid:
			visible.append(rid)

	visible_set = set(visible)
	out: list[dict[str, Any]] = []
	for row in rows:
		if is_surface_marker(row):
			continue
		rid = _row_id(row)
		if rid:
			if rid in visible_set:
				out.append(row)
		else:
			out.append(row)
	return out


def active_markers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
	"""返回当前仍然生效（未被 undo）的 rewind marker 行，按日志顺序。

	供 v2 物理重写路径在重写后回填：fold 对「marker 在、影子首行缺失」
	保守不隐藏，因此回填 active marker 永远方向安全。
	"""
	undone: set[str] = set()
	markers: list[dict[str, Any]] = []
	for row in rows:
		if not is_surface_marker(row):
			continue
		rid = str(row.get("rewind_id") or "")
		op = str(row.get("op") or "")
		if not rid:
			continue
		if op == _OP_REWIND:
			markers.append(row)
		elif op == _OP_REWIND_UNDO:
			undone.add(rid)
	return [m for m in markers if str(m.get("rewind_id") or "") not in undone]


def has_undo_marker(rows: list[dict[str, Any]], rewind_id: str) -> bool:
	"""该 rewind_id 是否已有 undo marker（undo 幂等续跑的判定依据）。"""
	rid = str(rewind_id or "")
	return any(
		is_surface_marker(row)
		and str(row.get("op") or "") == _OP_REWIND_UNDO
		and str(row.get("rewind_id") or "") == rid
		for row in rows
	)


def has_rewind_marker(rows: list[dict[str, Any]], rewind_id: str) -> bool:
	rid = str(rewind_id or "")
	return any(
		is_surface_marker(row)
		and str(row.get("op") or "") == _OP_REWIND
		and str(row.get("rewind_id") or "") == rid
		for row in rows
	)
