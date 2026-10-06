"""Lossless MCP result conversion; transport-independent."""
from dataclasses import replace
import json
from typing import Any
from tools.base_tool import ToolResult

def _image_data_url(mime: str, data: str) -> str:
	"""MCP ``image`` content block → ``data:<mime>;base64,<data>`` data URL."""
	mime = (mime or "image/png").strip()
	return f"data:{mime};base64,{data}"


def _result_from_mcp_call(result: Any) -> ToolResult:
	"""Deserialize an MCP ``tools/call`` result into a :class:`ToolResult`.

	- ``text`` blocks → ``content``（维持现状）。
	- ``image`` blocks → ``ToolResult.images``（data URL；vision 门控在
	  ``McpTool`` 执行层按 ``apply_read_vision`` 能力开关决定保留/降级占位）。
	- ``resource`` blocks → ``metadata["_mcp_resources"]``（供 spill 落盘 + 路径引用）。
	"""
	if not isinstance(result, dict):
		return ToolResult(
			content=f"mcp tools/call returned non-object: {result!r}", is_error=True
		)
	is_error = bool(result.get("isError", False))
	content = result.get("content") or []
	texts: list[str] = []
	images: list[str] = []
	resources: list[dict[str, Any]] = []
	for block in content:
		if not isinstance(block, dict):
			continue
		bt = block.get("type")
		if bt == "text":
			texts.append(str(block.get("text") or ""))
		elif bt == "resource":
			res = block.get("resource") or {}
			if isinstance(res, dict):
				resources.append(dict(res))
			else:
				texts.append(str(block.get("text") or ""))
		elif bt == "image":
			data = str(block.get("data") or "")
			if data:
				images.append(_image_data_url(str(block.get("mimeType") or ""), data))
			else:
				texts.append(f"[image data:{block.get('mimeType')}]")
		else:
			# Links and future protocol blocks remain recoverable as factual JSON.
			texts.append(json.dumps(block, ensure_ascii=False, separators=(",", ":")))
	structured = result.get("structuredContent")
	if structured is not None:
		duplicate = False
		for item in texts:
			try:
				duplicate = duplicate or json.loads(item) == structured
			except (ValueError, TypeError):
				pass
		if not duplicate:
			texts.append(json.dumps(structured, ensure_ascii=False, separators=(",", ":")))
	body = "\n".join(texts) if texts else (str(result.get("text") or ""))
	meta: dict[str, Any] = {}
	if resources:
		meta["_mcp_resources"] = resources
	return ToolResult(content=body or "ok", is_error=is_error, images=images or None, metadata=meta or None)


def _finalize_mcp_result(
	result: ToolResult,
	*,
	apply_vision: bool,
	session_id: str,
) -> ToolResult:
	"""F6a 内容融合：image 块视觉门控 + resource 块 spill 落盘。

	- 视觉关（``apply_read_vision`` 能力开关 false）→ image 降级为占位文本，
	  ``images`` 置空（不再进视觉链路）。
	- resource 块 → ``spill`` 落盘 + 路径引用（模型可见路径，可 Read 回读）。
	"""
	meta = dict(result.metadata or {})
	images = list(result.images or [])
	resources = meta.pop("_mcp_resources", None)
	content = result.content or ""
	if images and not apply_vision:
		content = (
			(content.rstrip() + "\n" if content else "")
			+ "[image 块已返回，但当前模型不支持视觉输入；已降级为占位。]"
		)
		images = []
	if resources:
		for res in resources:
			uri = str(res.get("uri") or "")
			res_text = str(res.get("text") or res.get("blob") or "")
			path: str | None = None
			if res_text:
				try:
					from tools.spill import save_text

					ref = save_text(session_id or "mcp", res_text)
					path = ref.path
				except Exception:  # noqa: BLE001 — spill 失败：路径引用降级
					path = None
			if path:
				content += f'\n[resource {uri} spilled: {path}; Read(file_path="{path}") returns it]'
			else:
				content += f"\n[resource {uri}]" + (f"\n{res_text}" if res_text else "")
	final_meta = dict(meta)
	if images:
		final_meta["has_images"] = True
	if resources:
		final_meta["has_resources"] = True
	return replace(
		result,
		content=content or "ok",
		images=images or None,
		metadata=final_meta or None,
	)
