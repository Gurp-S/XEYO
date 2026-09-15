"""NotebookEdit — cell-level Jupyter notebook editing."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from engine.abort import AbortController
from permissions import filesystem
from rewind.context import current_context
from tools.base_tool import ToolResult
from tools.fileio.paths import expand_path
from tools.fileio.read_state import FileStateEntry, ReadFileState
from tools.fileio.text import get_mtime_ms, write_text_file
from tools.notebook_edit_tool.prompt import DESCRIPTION, NOTEBOOK_EDIT_TOOL_NAME

_MAX_SOURCE = 1_024 * 1_024
_EMPTY_NB = {
	"nbformat": 4,
	"nbformat_minor": 5,
	"metadata": {},
	"cells": [],
}


class NotebookEditTool:
	name = NOTEBOOK_EDIT_TOOL_NAME

	def __init__(self, *, cwd: str = ".", read_state: ReadFileState | None = None) -> None:
		self._cwd = os.path.abspath(cwd or ".")
		self._read_state = read_state or ReadFileState()
		self._write_store: Any | None = None
		self._agent_id: str = "main"

	def set_read_file_state(self, state: ReadFileState) -> None:
		self._read_state = state

	def set_write_store(self, store: Any) -> None:
		self._write_store = store

	def set_agent_id(self, agent_id: str | None) -> None:
		self._agent_id = agent_id or "main"

	@staticmethod
	def is_read_only() -> bool:
		return False

	@staticmethod
	def is_concurrency_safe() -> bool:
		return False

	def schema(self) -> dict[str, Any]:
		return {
			"name": self.name,
			"description": DESCRIPTION,
			"input_schema": {
				"type": "object",
				"required": ["notebook_path", "edit_mode"],
				"properties": {
					"notebook_path": {
						"type": "string",
						"description": "Path to .ipynb under workspace.",
					},
					"edit_mode": {
						"type": "string",
						"enum": ["replace", "insert", "delete"],
					},
					"cell_idx": {
						"type": "integer",
						"description": (
							"0-based cell index. insert: insert before this "
							"index; omit to append."
						),
					},
					"new_source": {
						"type": "string",
						"description": "New cell source. Required for replace/insert.",
					},
					"cell_type": {
						"type": "string",
						"enum": ["code", "markdown"],
						"description": (
							"For insert: default code if omitted. "
							"For replace: optional (keep existing type)."
						),
					},
				},
				"additionalProperties": False,
			},
		}

	def check_permissions(self, input_data: dict[str, Any], context: Any = None) -> bool:
		return filesystem.check_write_permission_for_tool(self, input_data, context)

	def _persist(self, full: str, content: str) -> None:
		if self._write_store is None:
			# 与 file_edit_tool 同款兜底：子 agent（write_scope 激活）必须经
			# WriteStore，禁止静默直写——多 agent 写隔离唯一旁路（G129）。
			from permissions.write_scope import get_write_scope

			if get_write_scope() is not None:
				raise RuntimeError(
					"write_store required for sub-agent writes "
					"(refusing direct disk bypass)"
				)
			write_text_file(full, content, encoding="utf-8", line_endings="LF")
			return
		from engine.write_store import ChangeIntent, EditOp, _content_hash_text

		entry = self._read_state.get(full)
		if entry is not None and entry.content:
			base_hash = _content_hash_text(entry.content)
		elif entry is not None:
			# sidecar 恢复条目正文未知：现读现比对，避免 missing_read 拒绝首写。
			from tools.fileio.text import read_text_file as _rtf

			try:
				base_hash = _content_hash_text(_rtf(full)[0])
			except OSError:
				base_hash = ""
		else:
			base_hash = ""
		result = self._write_store.submit_sync(
			ChangeIntent(
				agent_id=self._agent_id,
				base_hashes={full: base_hash},
				ops=[EditOp(path=full, new_content=content)],
			)
		)
		if not result.ok:
			raise RuntimeError(
				"File has been unexpectedly modified. Read it again before writing."
				if result.base_stale
				else f"write failed: {result.reason}"
			)

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		abort.raise_if_aborted()
		raw = input or {}
		nb_path = str(raw.get("notebook_path") or "").strip()
		mode = str(raw.get("edit_mode") or "").strip().lower()
		if not nb_path:
			return ToolResult(content="notebook_path is required", is_error=True)
		if mode not in ("replace", "insert", "delete"):
			return ToolResult(
				content="edit_mode must be replace|insert|delete",
				is_error=True,
			)
		if not nb_path.lower().endswith(".ipynb"):
			return ToolResult(
				content="notebook_path must end with .ipynb",
				is_error=True,
			)

		perm_input = {"notebook_path": nb_path}
		if not self.check_permissions(perm_input):
			return ToolResult(content="permission denied", is_error=True)

		full = expand_path(nb_path, cwd=self._cwd)
		new_source = raw.get("new_source")
		if new_source is not None and not isinstance(new_source, str):
			new_source = str(new_source)
		cell_type = str(raw.get("cell_type") or "").strip().lower() or None
		cell_idx_raw = raw.get("cell_idx", None)

		if mode in ("replace", "insert"):
			if new_source is None:
				return ToolResult(
					content="new_source is required for replace/insert",
					is_error=True,
				)
			if len(new_source) > _MAX_SOURCE:
				return ToolResult(
					content=f"new_source exceeds {_MAX_SOURCE} bytes",
					is_error=True,
				)
		if mode == "insert":
			if cell_type is None:
				cell_type = "code"
			if cell_type not in ("code", "markdown"):
				return ToolResult(
					content="cell_type must be code|markdown (default code for insert)",
					is_error=True,
				)

		abort.raise_if_aborted()
		created = False
		if not os.path.exists(full):
			if mode != "insert":
				return ToolResult(content=f"notebook not found: {full}", is_error=True)
			nb = json.loads(json.dumps(_EMPTY_NB))
			created = True
		else:
			entry = self._read_state.get(full)
			if not entry or entry.is_partial_view:
				return ToolResult(
					content=(
						"Notebook has not been read yet. "
						"Read it first before NotebookEdit."
					),
					is_error=True,
				)
			try:
				mtime = get_mtime_ms(full)
			except OSError as e:
				return ToolResult(content=str(e), is_error=True)
			if mtime > entry.timestamp and entry.content:
				# 内容仍与磁盘一致则放行
				try:
					disk = await asyncio.to_thread(
						lambda: open(full, encoding="utf-8").read()
					)
				except OSError as e:
					return ToolResult(content=str(e), is_error=True)
				if disk != entry.content:
					return ToolResult(
						content=(
							"Notebook modified since Read. Read it again "
							"before NotebookEdit."
						),
						is_error=True,
					)
			try:
				# ipynb 常含大段 output（数 MB），读盘+解析挪线程。
				text = await asyncio.to_thread(
					lambda: open(full, encoding="utf-8").read()
				)
			except OSError as e:
				return ToolResult(content=str(e), is_error=True)
			try:
				nb = json.loads(text)
			except json.JSONDecodeError as e:
				return ToolResult(
					content=f"invalid notebook JSON: {e}",
					is_error=True,
				)
			if not isinstance(nb, dict) or not isinstance(nb.get("cells"), list):
				return ToolResult(
					content="invalid notebook: missing cells list",
					is_error=True,
				)

		cells: list[Any] = nb["cells"]
		n = len(cells)

		try:
			if mode == "delete":
				if cell_idx_raw is None:
					return ToolResult(content="cell_idx is required for delete", is_error=True)
				idx = int(cell_idx_raw)
				if idx < 0 or idx >= n:
					return ToolResult(
						content=f"cell_idx {idx} out of range (0..{n - 1})",
						is_error=True,
					)
				cells.pop(idx)
				summary = f"Deleted cell {idx} in {nb_path}"
			elif mode == "insert":
				idx = n if cell_idx_raw is None else int(cell_idx_raw)
				if idx < 0 or idx > n:
					return ToolResult(
						content=f"cell_idx {idx} out of range for insert (0..{n})",
						is_error=True,
					)
				assert isinstance(new_source, str)
				assert cell_type in ("code", "markdown")
				cell = _new_cell(cell_type, new_source)
				cells.insert(idx, cell)
				summary = (
					f"{'Created notebook and inserted' if created else 'Inserted'} "
					f"cell {idx} in {nb_path} ({cell_type}, {len(new_source)} chars)"
				)
			else:  # replace
				if cell_idx_raw is None:
					return ToolResult(
						content="cell_idx is required for replace",
						is_error=True,
					)
				idx = int(cell_idx_raw)
				if idx < 0 or idx >= n:
					return ToolResult(
						content=f"cell_idx {idx} out of range (0..{n - 1})",
						is_error=True,
					)
				cell = cells[idx]
				if not isinstance(cell, dict):
					return ToolResult(content=f"cell {idx} is not an object", is_error=True)
				ctype = cell_type or str(cell.get("cell_type") or "code")
				if ctype not in ("code", "markdown"):
					return ToolResult(
						content=f"unsupported cell_type: {ctype}",
						is_error=True,
					)
				assert isinstance(new_source, str)
				cell["cell_type"] = ctype
				cell["source"] = _source_to_list(new_source)
				cell["outputs"] = []
				cell["execution_count"] = None
				if "metadata" not in cell or not isinstance(cell["metadata"], dict):
					cell["metadata"] = {}
				summary = (
					f"Replaced cell {idx} in {nb_path} "
					f"({ctype}, {len(new_source)} chars)"
				)
		except (TypeError, ValueError) as e:
			return ToolResult(content=f"invalid cell_idx: {e}", is_error=True)

		content = json.dumps(nb, ensure_ascii=False, separators=(",", ":")) + "\n"
		abort.raise_if_aborted()
		try:
			if self._write_store is not None:
				await asyncio.to_thread(self._persist, full, content)
			else:
				self._persist(full, content)
		except Exception as e:  # noqa: BLE001
			return ToolResult(content=str(e), is_error=True)

		self._read_state.set(
			full,
			FileStateEntry(
				content=content,
				timestamp=get_mtime_ms(full),
				offset=None,
				limit=None,
			),
		)

		rewind_context = current_context()
		if rewind_context is not None:
			try:
				rewind_context.record_file_mutation(
					path=full,
					tool_name=self.name,
					agent_id=self._agent_id,
				)
			except Exception:  # noqa: BLE001
				logging.getLogger(__name__).debug(
					"rewind file mutation note failed", exc_info=True
				)

		preview = ""
		if isinstance(new_source, str) and new_source and mode != "delete":
			preview = "\n" + (new_source[:400] + ("…" if len(new_source) > 400 else ""))
		n_after = len(nb["cells"])
		footer = (
			f"\ncells_now={n_after}; valid cell_idx 0..{max(0, n_after - 1)} "
			f"(insert omits cell_idx to append; default cell_type=code)."
		)
		return ToolResult(content=summary + preview + footer, is_error=False)


def _source_to_list(source: str) -> list[str]:
	if source == "":
		return []
	# 像 Jupyter 常做的那样，把末尾换行保留为空的最后一段。
	parts = source.split("\n")
	if len(parts) == 1:
		return [parts[0]]
	out: list[str] = []
	for i, part in enumerate(parts):
		if i < len(parts) - 1:
			out.append(part + "\n")
		elif part:
			out.append(part)
	return out


def _new_cell(cell_type: str, source: str) -> dict[str, Any]:
	cell: dict[str, Any] = {
		"cell_type": cell_type,
		"metadata": {},
		"source": _source_to_list(source),
	}
	if cell_type == "code":
		cell["outputs"] = []
		cell["execution_count"] = None
	return cell
