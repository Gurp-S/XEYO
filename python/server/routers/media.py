"""Media 域路由：图片上传/读取与文本附件上传。"""

from __future__ import annotations

import asyncio
import mimetypes
import uuid
from typing import Any

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse

from server.deps import UPLOAD_DIR, api_error
from common.errors import safe_error_detail

router = APIRouter(tags=["media"])

#: 文本附件上限：读满 limit+1 即停，超限请求不得把整个请求体拉进内存。
_MAX_FILE_BYTES = 2 * 1024 * 1024
#: 回给调用方的内联正文上限（超出部分只落盘，不进上下文）。
_MAX_INLINE_CHARS = 80_000

@router.get("/v1/media/{digest}")
async def get_media(digest: str) -> FileResponse:
	"""读取已上传图片；仅允许 xeyo-media 引用对应的存储对象。"""
	from media_store import MediaError, _path_for_ref

	try:
		path = _path_for_ref(f"xeyo-media://{digest}")
	except MediaError as exc:
		raise api_error(404, "media not found") from exc
	media_type, _ = mimetypes.guess_type(path.name)
	return FileResponse(path, media_type=media_type or "application/octet-stream")


@router.post("/v1/media/upload")
async def upload_media(file: UploadFile = File(...)) -> dict[str, Any]:
	"""上传图片并返回不可变媒体引用；原有 /v1/files 保持文本附件语义。

	校验/落盘（sha256 + Pillow + fsync）在线程池执行，避免大图阻塞事件循环。
	"""
	from media_store import MediaError, max_media_bytes, save_image

	limit = max_media_bytes()
	chunks: list[bytes] = []
	total = 0
	while True:
		chunk = await file.read(min(1024 * 1024, limit + 1 - total))
		if not chunk:
			break
		chunks.append(chunk)
		total += len(chunk)
		if total > limit:
			raise api_error(413, f"image too large (max {limit} bytes)")
	payload = b"".join(chunks)
	try:
		asset = await asyncio.to_thread(
			save_image,
			payload,
			filename=file.filename or "image",
			declared_mime=file.content_type,
		)
	except MediaError as exc:
		raise api_error(400, safe_error_detail(exc)) from exc
	return {"ok": True, **asset.to_public()}


@router.post("/v1/files")
async def upload_file(file: UploadFile = File(...)) -> dict[str, Any]:
	name = file.filename or f"upload-{uuid.uuid4().hex[:8]}"
	# 分隔符（/ \ 与控制字符）一律换成 '_'，再冠以随机前缀：落点恒在 UPLOAD_DIR 内，
	# 客户端给的 filename 不参与决定写到哪里（与 /v1/media/upload 的 sha256 命名同口径）。
	safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
	dest = UPLOAD_DIR / f"{uuid.uuid4().hex[:10]}_{safe}"
	chunks: list[bytes] = []
	total = 0
	while total < _MAX_FILE_BYTES + 1:
		chunk = await file.read(min(1024 * 1024, _MAX_FILE_BYTES + 1 - total))
		if not chunk:
			break
		chunks.append(chunk)
		total += len(chunk)
	if total > _MAX_FILE_BYTES:
		raise api_error(413, f"file too large (max {_MAX_FILE_BYTES} bytes)")
	raw = b"".join(chunks)
	await asyncio.to_thread(dest.write_bytes, raw)

	text: str
	try:
		text = raw.decode("utf-8")
	except UnicodeDecodeError:
		try:
			text = raw.decode("gbk")
		except UnicodeDecodeError:
			text = f"[binary file saved: {dest.name}, {len(raw)} bytes]"

	# 截断 prompt 中过大的文本附件：置 truncated 旗标，不静默吞掉。
	truncated = len(text) > _MAX_INLINE_CHARS
	if truncated:
		text = text[:_MAX_INLINE_CHARS] + "\n…[truncated]"

	return {
		"id": dest.name,
		"filename": name,
		"bytes": len(raw),
		"text": text,
		"path": str(dest),
		"truncated": truncated,
	}
