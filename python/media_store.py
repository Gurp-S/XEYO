"""企业级图片媒体存储与按需物化。

设计要点：
- 原始图片只落盘一次，以 SHA-256 引用；不把 Base64 写进会话历史。
- 未超过当前供应商/模型限制时，发送原始字节，不做任何压缩。
- 超过限制时，仅在发送前等比缩放，避免因为切换模型而破坏已保存原图。
- 只接受实际内容可被 Pillow 识别的 JPEG/PNG/GIF/WebP。
"""

from __future__ import annotations

import base64
import io
import os
import re
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

_MEDIA_REF_RE = re.compile(r"^xeyo-media://([0-9a-f]{64})$", re.IGNORECASE)
_MIME_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}
_EXT_BY_FORMAT = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "GIF": ".gif",
    "WEBP": ".webp",
}
_FORMAT_BY_MIME = {value: key for key, value in _MIME_BY_FORMAT.items()}
_MAX_BYTES_DEFAULT = 64 * 1024 * 1024


class _LruCache:
    """简易容量上限 LRU（单线程热路径使用；put 刷新新鲜度）。"""

    def __init__(self, max_entries: int) -> None:
        self._max = max(1, int(max_entries))
        self._data: dict[Any, Any] = {}

    def get(self, key: Any) -> Any:
        value = self._data.get(key)
        if value is not None:
            self._data.pop(key, None)
            self._data[key] = value  # 触碰即刷新
        return value

    def put(self, key: Any, value: Any) -> None:
        self._data.pop(key, None)
        self._data[key] = value
        while len(self._data) > self._max:
            self._data.pop(next(iter(self._data)))

    def clear(self) -> None:
        self._data.clear()


# 物化 data URL 缓存：键 (sha256, max_dimension)。图片不可变（内容寻址），
# 唯一失效场景是缩放维度变化——已并入键。条目可达数 MB，容量必须小。
_data_url_cache = _LruCache(max_entries=8)


class MediaError(ValueError):
    """客户端可理解的媒体输入错误。"""


@dataclass(frozen=True)
class MediaAsset:
    media_ref: str
    mime: str
    width: int
    height: int
    bytes: int
    original_bytes: int
    filename: str

    def to_public(self) -> dict[str, Any]:
        return {
            "media_ref": self.media_ref,
            "mime": self.mime,
            "width": self.width,
            "height": self.height,
            "bytes": self.bytes,
            "original_bytes": self.original_bytes,
            "filename": self.filename,
        }


def _media_root() -> Path:
    configured = os.environ.get("XEYO_MEDIA_DIR", "").strip()
    if configured:
        root = Path(configured).expanduser()
    else:
        upload_root = os.environ.get("XEYO_UPLOAD_DIR", "").strip()
        if upload_root:
            root = Path(upload_root).expanduser() / "media"
        else:
            from session.workspace_path import xeyo_data_root

            root = xeyo_data_root() / "uploads" / "media"
    root.mkdir(parents=True, exist_ok=True)
    return root


def max_media_bytes() -> int:
    raw = os.environ.get("XEYO_MAX_IMAGE_BYTES", "").strip()
    if not raw:
        return _MAX_BYTES_DEFAULT
    try:
        return max(1, min(int(raw), 256 * 1024 * 1024))
    except ValueError:
        return _MAX_BYTES_DEFAULT


def _require_pillow():
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - dependency is installed by requirements
        raise MediaError("图片处理依赖 Pillow 未安装，请重新运行启动脚本安装依赖") from exc
    return Image, ImageOps


def _inspect_image(raw: bytes) -> tuple[str, int, int, str]:
    Image, _ = _require_pillow()
    if not raw:
        raise MediaError("图片内容为空")
    if len(raw) > max_media_bytes():
        raise MediaError(f"图片过大（最大 {max_media_bytes()} bytes）")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            fmt = (image.format or "").upper()
            width, height = image.size
            image.verify()
    except Exception as exc:  # noqa: BLE001
        raise MediaError("图片格式无效或内容已损坏") from exc
    mime = _MIME_BY_FORMAT.get(fmt)
    if mime is None:
        raise MediaError("仅支持 JPEG、PNG、GIF、WebP 图片")
    if width <= 0 or height <= 0:
        raise MediaError("图片尺寸无效")
    return fmt, int(width), int(height), mime


def _path_for_ref(media_ref: str) -> Path:
    match = _MEDIA_REF_RE.fullmatch((media_ref or "").strip())
    if not match:
        raise MediaError("无效的媒体引用")
    digest = match.group(1).lower()
    root = _media_root()
    matches = list(root.glob(f"{digest}.*"))
    if len(matches) != 1 or not matches[0].is_file():
        raise MediaError("媒体引用不存在或已被清理")
    return matches[0]


def save_image(raw: bytes, *, filename: str = "image", declared_mime: str | None = None) -> MediaAsset:
    """校验并保存原图；不在存储阶段改变原图字节。"""
    fmt, width, height, actual_mime = _inspect_image(raw)
    if declared_mime and declared_mime.startswith("image/") and declared_mime != actual_mime:
        # 只把声明作为提示，实际内容以签名/Pillow 识别为准；不因浏览器 MIME 错误误拒绝合法图片。
        pass
    digest = sha256(raw).hexdigest()
    suffix = _EXT_BY_FORMAT[fmt]
    root = _media_root()
    destination = root / f"{digest}{suffix}"
    if not destination.exists():
        fd, temp_name = tempfile.mkstemp(prefix=f".{digest}.", suffix=".tmp", dir=root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, destination)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
    safe_name = Path(filename or f"image{suffix}").name or f"image{suffix}"
    return MediaAsset(
        media_ref=f"xeyo-media://{digest}",
        mime=actual_mime,
        width=width,
        height=height,
        bytes=len(raw),
        original_bytes=len(raw),
        filename=safe_name,
    )


def _resize_image_bytes(raw: bytes, *, max_dimension: int) -> tuple[bytes, str, int, int]:
    fmt, width, height, mime = _inspect_image(raw)
    if max(width, height) <= max_dimension:
        return raw, mime, width, height

    Image, ImageOps = _require_pillow()
    ratio = max_dimension / float(max(width, height))
    size = (max(1, int(round(width * ratio))), max(1, int(round(height * ratio))))
    try:
        with Image.open(io.BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source)
            image = image.resize(size, Image.Resampling.LANCZOS)
            out = io.BytesIO()
            # GIF 动图在供应商视觉输入中通常只取首帧；保留格式比偷偷改成 JPEG 更安全。
            if fmt == "JPEG":
                image = image.convert("RGB")
                image.save(out, format="JPEG", quality=92, optimize=True)
            elif fmt == "WEBP":
                image.save(out, format="WEBP", quality=92, method=6)
            elif fmt == "GIF":
                image.save(out, format="GIF", optimize=True)
            else:
                image.save(out, format="PNG", optimize=True)
    except Exception as exc:  # noqa: BLE001
        raise MediaError("图片缩放失败") from exc
    resized = out.getvalue()
    return resized, mime, size[0], size[1]


def materialize_media_ref(
    media_ref: str,
    *,
    provider: str = "",
    model: str = "",
    image_count: int = 1,
) -> str:
    """把媒体引用物化为 data URL；不超上限时返回原始字节的 data URL。

    结果按 (digest, max_dimension) 做 LRU 缓存：历史中的同一张图在每轮
    请求投影时反复出现，避免每次读盘 + Pillow 校验 + base64 编码。
    """
    match = _MEDIA_REF_RE.fullmatch((media_ref or "").strip())
    if not match:
        raise MediaError("无效的媒体引用")
    digest = match.group(1).lower()
    try:
        from model.openai_compat import image_max_dimension

        max_dimension = image_max_dimension(provider, model, image_count=image_count)
    except Exception:
        # 未知供应商不伪造更严格的业务上限；使用安全的协议上限，保证请求不会带入无限大图片。
        max_dimension = 8192
    # 缓存查询必须先于读盘/Pillow 校验：命中时零 IO。
    cache_key = (digest, max_dimension)
    cached = _data_url_cache.get(cache_key)
    if cached is not None:
        return cached
    path = _path_for_ref(media_ref)
    raw = path.read_bytes()
    fmt, width, height, mime = _inspect_image(raw)
    if max(width, height) > max_dimension:
        raw, mime, _, _ = _resize_image_bytes(raw, max_dimension=max_dimension)
    encoded = base64.b64encode(raw).decode("ascii")
    data_url = f"data:{mime};base64,{encoded}"
    _data_url_cache.put(cache_key, data_url)
    return data_url


def materialize_image_url(
    url: str,
    *,
    provider: str = "",
    model: str = "",
    image_count: int = 1,
) -> str:
    """兼容 xeyo-media URI 与既有 data URL；下限内保持原 URL 不变。"""
    value = (url or "").strip()
    if value.startswith("xeyo-media://"):
        return materialize_media_ref(
            value,
            provider=provider,
            model=model,
            image_count=image_count,
        )
    if not value.startswith("data:image/"):
        return value
    marker = ","
    if marker not in value:
        raise MediaError("无效的图片 data URL")
    header, encoded = value.split(marker, 1)
    try:
        from model.openai_compat import image_max_dimension

        max_dimension = image_max_dimension(provider, model, image_count=image_count)
    except Exception:
        max_dimension = 8192
    # 历史中的同一 data URL 每轮重复出现：先查缓存（键=负载摘要），命中则
    # 免去 b64decode + Pillow 校验/缩放 + 重新编码。
    import hashlib as _hashlib

    payload_key = (
        "data",
        _hashlib.sha1(encoded.encode("ascii", errors="replace")).hexdigest(),
        max_dimension,
        header,
    )
    cached = _data_url_cache.get(payload_key)
    if cached is not None:
        return cached
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise MediaError("无效的图片 Base64 数据") from exc
    _, width, height, _ = _inspect_image(raw)
    if max(width, height) <= max_dimension:
        _data_url_cache.put(payload_key, value)
        return value
    raw, mime, _, _ = _resize_image_bytes(raw, max_dimension=max_dimension)
    out_url = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
    _data_url_cache.put(payload_key, out_url)
    return out_url


def media_exists(media_ref: str) -> bool:
    try:
        return _path_for_ref(media_ref).is_file()
    except MediaError:
        return False


def media_path(media_ref: str) -> Path:
    """供审计或清理任务使用的受校验路径。"""
    return _path_for_ref(media_ref)


__all__ = [
    "MediaAsset",
    "MediaError",
    "materialize_image_url",
    "materialize_media_ref",
    "media_exists",
    "media_path",
    "max_media_bytes",
    "save_image",
]
