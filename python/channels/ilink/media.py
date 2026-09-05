"""iLink 图片/文件：CDN 上传、下载、落盘。"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from channels.ilink.client import ILinkClient
from channels.ilink.crypto import (
	aes_ecb_padded_size,
	decrypt_aes_ecb,
	encode_cdn_aes_key,
	encrypt_aes_ecb,
	parse_aes_key,
)
from channels.ilink.qr_png import sniff_image
from channels.ilink.store import credentials_dir

log = logging.getLogger("xeyo.ilink.media")

MEDIA_IMAGE = 1
MEDIA_FILE = 3
ITEM_TEXT = 1
ITEM_IMAGE = 2
ITEM_VOICE = 3
ITEM_FILE = 4
ITEM_VIDEO = 5

_UNSAFE_NAME = re.compile(r"[^\w.\-()+]+", re.UNICODE)
_MAX_BYTES = 100 * 1024 * 1024
_VISION_MAX = 400_000


@dataclass
class UploadInfo:
	download_param: str
	aes_key_b64: str
	raw_size: int
	cipher_size: int
	raw_md5: str
	file_name: str


@dataclass
class InboundMedia:
	kind: str  # image | file
	path: Path
	name: str
	mime: str
	data_url: str | None = None


def inbound_dir() -> Path:
	d = credentials_dir() / "inbound"
	d.mkdir(parents=True, exist_ok=True)
	return d


def _safe_name(name: str, fallback: str) -> str:
	base = Path(name or "").name or fallback
	cleaned = _UNSAFE_NAME.sub("_", base).strip("._") or fallback
	return cleaned[:120]


def _data_url(blob: bytes, mime: str) -> str | None:
	if not blob or len(blob) > _VISION_MAX:
		return None
	import base64

	return f"data:{mime};base64,{base64.b64encode(blob).decode('ascii')}"


async def upload_local(
	client: ILinkClient,
	token: str,
	to_user_id: str,
	path: Path,
	*,
	media_type: int,
) -> UploadInfo:
	data = path.read_bytes()
	if not data:
		raise RuntimeError(f"empty file: {path}")
	if len(data) > _MAX_BYTES:
		raise RuntimeError(f"file too large ({len(data)} bytes): {path}")
	rawsize = len(data)
	raw_md5 = hashlib.md5(data).hexdigest()
	cipher_size = aes_ecb_padded_size(rawsize)
	filekey = secrets.token_hex(16)
	aeskey = secrets.token_bytes(16)
	resp = await client.getuploadurl(
		token,
		filekey=filekey,
		media_type=media_type,
		to_user_id=to_user_id,
		rawsize=rawsize,
		rawfilemd5=raw_md5,
		filesize=cipher_size,
		aeskey_hex=aeskey.hex(),
		no_need_thumb=True,
	)
	ret = resp.get("ret")
	errcode = resp.get("errcode")
	if (ret not in (None, 0, "0")) or (errcode not in (None, 0, "0")):
		raise RuntimeError(resp.get("errmsg") or f"getuploadurl failed: {resp}")
	ciphertext = encrypt_aes_ecb(data, aeskey)
	if len(ciphertext) != cipher_size:
		raise RuntimeError(
			f"ciphertext size mismatch: got {len(ciphertext)} expected {cipher_size}"
		)
	download_param = await client.cdn_upload(
		ciphertext=ciphertext,
		filekey=filekey,
		upload_param=str(resp.get("upload_param") or ""),
		upload_full_url=str(resp.get("upload_full_url") or ""),
	)
	return UploadInfo(
		download_param=download_param,
		aes_key_b64=encode_cdn_aes_key(aeskey),
		raw_size=rawsize,
		cipher_size=cipher_size,
		raw_md5=raw_md5,
		file_name=path.name,
	)


def image_item(info: UploadInfo) -> dict[str, Any]:
	return {
		"type": ITEM_IMAGE,
		"image_item": {
			"media": {
				"encrypt_query_param": info.download_param,
				"aes_key": info.aes_key_b64,
				"encrypt_type": 1,
			},
			"mid_size": info.cipher_size,
		},
	}


def file_item(info: UploadInfo) -> dict[str, Any]:
	return {
		"type": ITEM_FILE,
		"file_item": {
			"media": {
				"encrypt_query_param": info.download_param,
				"aes_key": info.aes_key_b64,
				"encrypt_type": 1,
			},
			"file_name": info.file_name,
			"md5": info.raw_md5,
			"len": str(info.raw_size),
		},
	}


def _cdn_ref(media: dict[str, Any] | None) -> tuple[str, str, str]:
	if not isinstance(media, dict):
		return "", "", ""
	return (
		str(media.get("encrypt_query_param") or ""),
		str(media.get("aes_key") or ""),
		str(media.get("full_url") or ""),
	)


async def _download_decrypt(
	client: ILinkClient,
	*,
	encrypt_query_param: str,
	aes_key_b64: str,
	full_url: str,
	aeskey_hex: str | None = None,
) -> bytes:
	blob = await client.cdn_download(
		encrypt_query_param=encrypt_query_param,
		full_url=full_url,
	)
	if not blob:
		return b""
	try:
		key = parse_aes_key(aes_key_b64=aes_key_b64 or None, aeskey_hex=aeskey_hex)
	except ValueError:
		return blob
	try:
		return decrypt_aes_ecb(blob, key)
	except Exception:
		log.warning("ilink media decrypt failed, keeping ciphertext")
		return blob


def _save_inbound(blob: bytes, name: str) -> Path:
	if len(blob) > _MAX_BYTES:
		raise RuntimeError("inbound media too large")
	stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
	dest = inbound_dir() / f"{stamp}-{_safe_name(name, 'file.bin')}"
	n = 0
	while dest.exists():
		n += 1
		dest = dest.with_name(f"{stamp}-{n}-{_safe_name(name, 'file.bin')}")
	dest.write_bytes(blob)
	return dest


async def collect_inbound_media(
	client: ILinkClient | None,
	msg: dict[str, Any],
) -> list[InboundMedia]:
	if client is None:
		return []
	out: list[InboundMedia] = []
	items = msg.get("item_list") or msg.get("itemList") or []
	for item in items:
		if not isinstance(item, dict):
			continue
		try:
			kind = int(item.get("type") or 0)
		except (TypeError, ValueError):
			continue
		try:
			if kind == ITEM_IMAGE:
				img = item.get("image_item") or {}
				if not isinstance(img, dict):
					continue
				media = img.get("media") if isinstance(img.get("media"), dict) else {}
				param, aes_b64, full = _cdn_ref(media)
				if not param and not full:
					continue
				blob = await _download_decrypt(
					client,
					encrypt_query_param=param,
					aes_key_b64=aes_b64,
					full_url=full,
					aeskey_hex=str(img.get("aeskey") or "") or None,
				)
				mime = sniff_image(blob) or "image/jpeg"
				ext = {
					"image/png": ".png",
					"image/jpeg": ".jpg",
					"image/gif": ".gif",
					"image/webp": ".webp",
				}.get(mime, ".jpg")
				path = _save_inbound(blob, f"image{ext}")
				# 小图继续沿用现有 data URL 行为；大图只传引用，模型发送前按
				# 当前供应商上限物化，避免 iLink 入站直接制造巨型请求。
				data_url = _data_url(blob, mime)
				if data_url is None:
					try:
						from media_store import save_image

						data_url = save_image(
							blob,
							filename=path.name,
							declared_mime=mime,
						).media_ref
					except Exception as exc:  # noqa: BLE001
						log.warning("save large inbound image failed: %s", exc)
				out.append(
					InboundMedia(
						kind="image",
						path=path,
						name=path.name,
						mime=mime,
						data_url=data_url,
					)
				)
			elif kind == ITEM_FILE:
				fi = item.get("file_item") or {}
				if not isinstance(fi, dict):
					continue
				media = fi.get("media") if isinstance(fi.get("media"), dict) else {}
				param, aes_b64, full = _cdn_ref(media)
				if not param and not full:
					continue
				blob = await _download_decrypt(
					client,
					encrypt_query_param=param,
					aes_key_b64=aes_b64,
					full_url=full,
				)
				name = str(fi.get("file_name") or "file.bin")
				path = _save_inbound(blob, name)
				mime = "application/octet-stream"
				out.append(
					InboundMedia(
						kind="file",
						path=path,
						name=path.name,
						mime=mime,
					)
				)
		except Exception as e:  # noqa: BLE001
			log.warning("ilink inbound media failed: %s", e)
	return out


def inbound_prompt(text: str, media: list[InboundMedia]) -> tuple[str, list[str]]:
	"""拼给 Agent 的文字 + vision data URL。"""
	parts: list[str] = []
	if text.strip():
		parts.append(text.strip())
	images: list[str] = []
	for m in media:
		if m.kind == "image":
			parts.append(f"[图片] 已保存: {m.path}")
			if m.data_url:
				images.append(m.data_url)
			else:
				parts.append("（图较大，请用 Read 打开上述路径）")
		else:
			parts.append(f"[文件] {m.name}\n已保存: {m.path}\n需要时用 Read 查看。")
	body = "\n".join(parts).strip()
	if not body:
		body = "[图片]" if images else ""
	return body, images
