"""Read 工具的图片 / PDF 解码（仅在 vision 开启时使用）。

限制（合理默认，可用环境变量覆盖）：
- 磁盘文件上限 ``XEYO_READ_IMAGE_MAX_BYTES``（默认 8 MiB）
- 送模型最长边 ``XEYO_READ_IMAGE_MAX_DIMENSION``（默认 2048）
- 编码后 data URL 软顶约 1.5 MiB；超限再压 JPEG quality
"""

from __future__ import annotations

import base64
import io
import os
from typing import Any


def _env_int(name: str, default: int) -> int:
	raw = os.environ.get(name, "").strip()
	if not raw:
		return default
	try:
		return max(1, int(raw))
	except ValueError:
		return default


# 磁盘读取上限：过大先拒，避免无界读入内存
READ_IMAGE_MAX_BYTES = _env_int("XEYO_READ_IMAGE_MAX_BYTES", 8 * 1024 * 1024)
# 送 LLM 最长边（像素）
READ_IMAGE_MAX_DIMENSION = _env_int("XEYO_READ_IMAGE_MAX_DIMENSION", 2048)
# data URL 载荷软顶（字节，约 base64 前）
READ_IMAGE_MAX_ENCODED = _env_int("XEYO_READ_IMAGE_MAX_ENCODED", 1_500_000)


def _to_data_url(raw: bytes, mime: str) -> str:
	b64 = base64.standard_b64encode(raw).decode("ascii")
	return f"data:{mime};base64,{b64}"


def compress_image_for_llm(
	raw: bytes,
	*,
	max_dimension: int = READ_IMAGE_MAX_DIMENSION,
	max_encoded: int = READ_IMAGE_MAX_ENCODED,
) -> tuple[str, dict[str, Any]]:
	"""缩放/转码后返回 data URL + 元数据。"""
	from media_store import MediaError, _inspect_image, _require_pillow

	if len(raw) > READ_IMAGE_MAX_BYTES:
		raise MediaError(
			f"image file exceeds {READ_IMAGE_MAX_BYTES} bytes "
			f"({len(raw)} bytes); shrink the file or raise "
			"XEYO_READ_IMAGE_MAX_BYTES"
		)

	fmt, width, height, mime = _inspect_image(raw)
	Image, ImageOps = _require_pillow()
	with Image.open(io.BytesIO(raw)) as source:
		image = ImageOps.exif_transpose(source)
		w, h = image.size
		long_edge = max(w, h)
		if long_edge > max_dimension:
			ratio = max_dimension / float(long_edge)
			size = (max(1, int(round(w * ratio))), max(1, int(round(h * ratio))))
			image = image.resize(size, Image.Resampling.LANCZOS)
			w, h = size

		# 统一走 JPEG/PNG：GIF 取首帧；有 alpha 用 PNG，否则 JPEG
		qualities = (85, 70, 55)
		out_bytes = b""
		out_mime = mime
		for q in qualities:
			buf = io.BytesIO()
			has_alpha = image.mode in ("RGBA", "LA") or (
				image.mode == "P" and "transparency" in image.info
			)
			if has_alpha and fmt != "JPEG":
				rgba = image.convert("RGBA")
				rgba.save(buf, format="PNG", optimize=True)
				out_mime = "image/png"
			else:
				rgb = image.convert("RGB")
				rgb.save(buf, format="JPEG", quality=q, optimize=True)
				out_mime = "image/jpeg"
			out_bytes = buf.getvalue()
			if len(out_bytes) <= max_encoded:
				break

	if not out_bytes:
		raise MediaError("image compression produced empty output")

	meta = {
		"original_format": fmt,
		"original_bytes": len(raw),
		"encoded_bytes": len(out_bytes),
		"width": w,
		"height": h,
		"mime": out_mime,
	}
	return _to_data_url(out_bytes, out_mime), meta


def read_pdf_for_llm(
	path: str,
	*,
	page: int = 1,
	max_dimension: int = READ_IMAGE_MAX_DIMENSION,
) -> tuple[str, list[str], dict[str, Any]]:
	"""返回 (text_summary, images_data_urls, meta)。

	优先 pymupdf 渲染指定页为图；若无 pymupdf 则仅尝试文本提取（无图）。
	"""
	page_i = max(1, int(page or 1))
	meta: dict[str, Any] = {"page": page_i, "path": path}

	try:
		import fitz  # type: ignore[import-untyped]
	except ImportError:
		# 无渲染库：尽量抽文本，明确告知无法出图
		text = _pdf_text_fallback(path, page_i)
		note = (
			"PDF image render unavailable (install pymupdf for page images). "
			"Showing extracted text only."
		)
		return f"{note}\n\n{text}".strip(), [], {**meta, "mode": "text_only"}

	doc = fitz.open(path)
	try:
		n = doc.page_count
		if page_i > n:
			raise ValueError(f"PDF has {n} pages; requested page {page_i}")
		pg = doc.load_page(page_i - 1)
		text = (pg.get_text("text") or "").strip()
		# 目标最长边 ≈ max_dimension
		zoom = max_dimension / max(pg.rect.width, pg.rect.height, 1.0)
		zoom = min(max(zoom, 0.5), 3.0)
		mat = fitz.Matrix(zoom, zoom)
		pix = pg.get_pixmap(matrix=mat, alpha=False)
		png = pix.tobytes("png")
	finally:
		doc.close()

	data_url, img_meta = compress_image_for_llm(png, max_dimension=max_dimension)
	summary = (
		f"PDF page {page_i}/{page_i} "
		f"rendered as image"
		+ (f"\n\n--- text layer ---\n{text[:4000]}" if text else "")
	)
	# 重新短暂打开以统计页数用于摘要
	try:
		doc2 = fitz.open(path)
		try:
			summary = (
				f"PDF page {page_i}/{doc2.page_count} rendered as image"
				+ (f"\n\n--- text layer ---\n{text[:4000]}" if text else "")
			)
			meta["pages"] = doc2.page_count
		finally:
			doc2.close()
	except Exception:
		pass
	meta.update(img_meta)
	meta["mode"] = "render"
	return summary, [data_url], meta


def _pdf_text_fallback(path: str, page: int) -> str:
	try:
		from pypdf import PdfReader  # type: ignore[import-untyped]
	except ImportError:
		return (
			"(no text extractor: install pymupdf or pypdf, "
			"or convert the page to PNG and Read the image)"
		)
	reader = PdfReader(path)
	n = len(reader.pages)
	idx = max(0, min(n - 1, page - 1))
	text = (reader.pages[idx].extract_text() or "").strip()
	header = f"PDF page {page}/{n} (text extract)\n"
	return header + (text[:8000] if text else "(empty text layer)")
