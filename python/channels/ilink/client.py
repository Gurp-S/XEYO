"""iLink HTTP 客户端：QR 登录、长轮询、发文本/图片/文件。"""

from __future__ import annotations

import base64
import json
import random
import re
import uuid
from typing import Any
from urllib.parse import quote

import httpx

from channels.ilink import (
	APP_CLIENT_VERSION,
	BOT_AGENT,
	CDN_BASE_URL,
	CHANNEL_VERSION,
	ILINK_BASE_URL,
)

_DATA_URI_RE = re.compile(r"^data:image/(\w+);base64,(.+)$", re.I | re.S)


def make_uin() -> str:
	uin = str(random.randint(0, 0xFFFFFFFF))
	return base64.b64encode(uin.encode("ascii")).decode("ascii")


def base_info() -> dict[str, str]:
	return {"channel_version": CHANNEL_VERSION, "bot_agent": BOT_AGENT}


def make_headers(token: str | None = None) -> dict[str, str]:
	headers = {
		"Content-Type": "application/json",
		"AuthorizationType": "ilink_bot_token",
		"X-WECHAT-UIN": make_uin(),
		"iLink-App-Id": "bot",
		"iLink-App-ClientVersion": APP_CLIENT_VERSION,
		"SKRouteTag": "1001",
	}
	if token:
		headers["Authorization"] = f"Bearer {token}"
	return headers


def extract_text(msg: dict[str, Any]) -> str:
	items = msg.get("item_list") or msg.get("itemList") or []
	parts: list[str] = []
	for item in items:
		if isinstance(item, str) and item.strip():
			parts.append(item.strip())
			continue
		if not isinstance(item, dict):
			continue
		text_item = item.get("text_item") or item.get("textItem")
		if isinstance(text_item, str) and text_item.strip():
			parts.append(text_item.strip())
			continue
		if isinstance(text_item, dict):
			t = str(
				text_item.get("text") or text_item.get("content") or ""
			).strip()
			if t:
				parts.append(t)
				continue
		direct = str(item.get("text") or item.get("content") or "").strip()
		if direct:
			parts.append(direct)
			continue
		voice = item.get("voice_item") or item.get("voiceItem") or {}
		if isinstance(voice, dict):
			t = str(voice.get("text") or "").strip()
			if t:
				parts.append(t)
	if not parts:
		for key in ("text", "content", "plain_text", "plainText"):
			t = str(msg.get(key) or "").strip()
			if t:
				parts.append(t)
				break
	return "\n".join(parts)


def rpc_ok(data: dict[str, Any] | None) -> bool:
	"""ret / errcode 把 0 与 \"0\" 都当成功。"""
	if not isinstance(data, dict):
		return False
	ret = data.get("ret")
	errcode = data.get("errcode")
	return ret in (None, 0, "0") and errcode in (None, 0, "0")


def collect_update_msgs(result: dict[str, Any]) -> list[dict[str, Any]]:
	"""兼容 msgs / msg / msg_list / data.msgs。"""
	if not isinstance(result, dict):
		return []
	raw = result.get("msgs")
	if raw is None:
		raw = result.get("msg_list") or result.get("message_list")
	if raw is None:
		one = result.get("msg")
		if isinstance(one, dict):
			raw = [one]
		elif isinstance(one, list):
			raw = one
	data = result.get("data")
	if raw is None and isinstance(data, dict):
		raw = data.get("msgs") or data.get("msg_list") or data.get("msg")
		if isinstance(raw, dict):
			raw = [raw]
	if not isinstance(raw, list):
		return []
	return [m for m in raw if isinstance(m, dict)]


def decode_qr_payload(raw: str) -> tuple[bytes | None, str | None]:
	"""返回 (png_bytes, http_url)。"""
	content = (raw or "").strip()
	if not content:
		return None, None
	if content.startswith("http://") or content.startswith("https://"):
		return None, content
	m = _DATA_URI_RE.match(content)
	if m:
		try:
			return base64.b64decode(m.group(2)), None
		except Exception:
			return None, None
	if content.startswith("<svg"):
		return content.encode("utf-8"), None
	try:
		blob = base64.b64decode(content, validate=True)
		if blob:
			return blob, None
	except Exception:
		pass
	return None, None


class ILinkClient:
	def __init__(
		self,
		*,
		base_url: str = ILINK_BASE_URL,
		timeout: float = 20.0,
		transport: httpx.AsyncBaseTransport | None = None,
	) -> None:
		self.base_url = base_url.rstrip("/")
		self._timeout = timeout
		self._transport = transport
		self._http: httpx.AsyncClient | None = None
		self._poll_http: httpx.AsyncClient | None = None

	async def __aenter__(self) -> ILinkClient:
		await self._ensure()
		return self

	async def __aexit__(self, *_exc: object) -> None:
		await self.aclose()

	def _client_kwargs(self, *, poll: bool) -> dict[str, Any]:
		if poll:
			timeout = httpx.Timeout(connect=15.0, read=43.0, write=20.0, pool=20.0)
			limits = httpx.Limits(
				max_connections=2,
				max_keepalive_connections=1,
				keepalive_expiry=90.0,
			)
		else:
			timeout = httpx.Timeout(
				connect=10.0,
				read=self._timeout,
				write=15.0,
				pool=5.0,
			)
			limits = httpx.Limits(max_connections=12, max_keepalive_connections=6)
		kwargs: dict[str, Any] = {
			"timeout": timeout,
			"follow_redirects": True,
			"limits": limits,
		}
		if self._transport is not None:
			kwargs["transport"] = self._transport
		return kwargs

	async def _ensure(self) -> httpx.AsyncClient:
		if self._http is None:
			self._http = httpx.AsyncClient(**self._client_kwargs(poll=False))
		return self._http

	async def _ensure_poll(self) -> httpx.AsyncClient:
		if self._poll_http is None:
			self._poll_http = httpx.AsyncClient(**self._client_kwargs(poll=True))
		return self._poll_http

	async def reset_poll_http(self) -> None:
		"""关掉长轮询 TCP，避免超时后僵尸连接占着微信的唯一 getupdates 槽。"""
		http = self._poll_http
		self._poll_http = None
		if http is not None:
			try:
				await http.aclose()
			except Exception:
				pass

	async def aclose(self) -> None:
		await self.reset_poll_http()
		if self._http is not None:
			await self._http.aclose()
			self._http = None

	def set_base_url(self, url: str) -> None:
		u = (url or "").strip().rstrip("/")
		if u:
			self.base_url = u

	async def _parse(self, res: httpx.Response) -> dict[str, Any]:
		raw = await res.aread()
		text = raw.decode("utf-8", errors="replace") if raw else ""
		try:
			data = json.loads(text) if text else {}
		except json.JSONDecodeError:
			data = {}
		if not isinstance(data, dict):
			data = {"raw": data}
		if res.status_code >= 400 and not data.get("errmsg"):
			data["errmsg"] = f"HTTP {res.status_code}"
			data.setdefault("ret", res.status_code)
		return data

	async def request(
		self,
		method: str,
		path: str,
		*,
		token: str | None = None,
		params: dict[str, Any] | None = None,
		body: dict[str, Any] | None = None,
		timeout: float | httpx.Timeout | None = None,
	) -> dict[str, Any]:
		http = await self._ensure()
		url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
		res = await http.request(
			method.upper(),
			url,
			params=params,
			json=body,
			headers=make_headers(token),
			timeout=timeout if timeout is not None else self._timeout,
		)
		return await self._parse(res)

	async def fetch_bytes(self, url: str) -> tuple[bytes, str]:
		http = await self._ensure()
		res = await http.get(url, timeout=20.0, follow_redirects=True)
		res.raise_for_status()
		ctype = res.headers.get("content-type", "")
		return res.content, ctype

	async def get_bot_qrcode(self, local_tokens: list[str] | None = None) -> dict[str, Any]:
		body = {"local_token_list": list(local_tokens or []), "base_info": base_info()}
		data = await self.request(
			"POST",
			"ilink/bot/get_bot_qrcode",
			params={"bot_type": "3"},
			body=body,
		)
		if not data.get("qrcode"):
			data = await self.request(
				"GET",
				"ilink/bot/get_bot_qrcode",
				params={"bot_type": "3"},
			)
		return data

	async def get_qrcode_status(self, qrcode: str, *, base_url: str | None = None) -> dict[str, Any]:
		prev = self.base_url
		if base_url:
			self.set_base_url(base_url)
		try:
			return await self.request(
				"GET",
				"ilink/bot/get_qrcode_status",
				params={"qrcode": qrcode},
				timeout=8.0,
			)
		except httpx.TimeoutException:
			return {"status": "wait"}
		finally:
			if base_url:
				self.base_url = prev

	async def getupdates(
		self,
		token: str,
		buf: str = "",
		*,
		timeout: float | httpx.Timeout = 40.0,
	) -> dict[str, Any]:
		if isinstance(timeout, (int, float)):
			req_timeout: httpx.Timeout | float = httpx.Timeout(
				connect=15.0,
				read=float(timeout),
				write=20.0,
				pool=20.0,
			)
		else:
			req_timeout = timeout
		http = await self._ensure_poll()
		url = f"{self.base_url}/ilink/bot/getupdates"
		res = await http.request(
			"POST",
			url,
			json={"get_updates_buf": buf, "base_info": base_info()},
			headers=make_headers(token),
			timeout=req_timeout,
		)
		return await self._parse(res)

	async def notifystart(self, token: str) -> dict[str, Any]:
		return await self.request(
			"POST",
			"ilink/bot/msg/notifystart",
			token=token,
			body={"base_info": base_info()},
			timeout=8.0,
		)

	async def notifystop(self, token: str) -> dict[str, Any]:
		return await self.request(
			"POST",
			"ilink/bot/msg/notifystop",
			token=token,
			body={"base_info": base_info()},
			timeout=5.0,
		)

	async def getconfig(self, token: str, user_id: str, context_token: str) -> dict[str, Any]:
		return await self.request(
			"POST",
			"ilink/bot/getconfig",
			token=token,
			body={
				"ilink_user_id": user_id,
				"context_token": context_token,
				"base_info": base_info(),
			},
			timeout=2.5,
		)

	async def sendtyping(
		self,
		token: str,
		*,
		user_id: str,
		typing_ticket: str,
		status: int,
	) -> dict[str, Any]:
		return await self.request(
			"POST",
			"ilink/bot/sendtyping",
			token=token,
			body={
				"ilink_user_id": user_id,
				"typing_ticket": typing_ticket,
				"status": status,
				"base_info": base_info(),
			},
			timeout=3.0,
		)

	async def getuploadurl(
		self,
		token: str,
		*,
		filekey: str,
		media_type: int,
		to_user_id: str,
		rawsize: int,
		rawfilemd5: str,
		filesize: int,
		aeskey_hex: str,
		no_need_thumb: bool = True,
	) -> dict[str, Any]:
		return await self.request(
			"POST",
			"ilink/bot/getuploadurl",
			token=token,
			body={
				"filekey": filekey,
				"media_type": media_type,
				"to_user_id": to_user_id,
				"rawsize": rawsize,
				"rawfilemd5": rawfilemd5,
				"filesize": filesize,
				"no_need_thumb": no_need_thumb,
				"aeskey": aeskey_hex,
				"base_info": base_info(),
			},
		)

	async def cdn_upload(
		self,
		*,
		ciphertext: bytes,
		filekey: str,
		upload_param: str = "",
		upload_full_url: str = "",
		cdn_base: str = CDN_BASE_URL,
	) -> str:
		http = await self._ensure()
		full = (upload_full_url or "").strip()
		if full:
			url = full
		elif upload_param:
			url = (
				f"{cdn_base.rstrip('/')}/upload"
				f"?encrypted_query_param={quote(upload_param, safe='')}"
				f"&filekey={quote(filekey, safe='')}"
			)
		else:
			raise RuntimeError("CDN upload URL missing (need upload_full_url or upload_param)")
		last_err = "CDN upload failed"
		for attempt in range(3):
			res = await http.post(
				url,
				content=ciphertext,
				headers={"Content-Type": "application/octet-stream"},
				timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=5.0),
			)
			if 400 <= res.status_code < 500:
				err = res.headers.get("x-error-message") or res.text[:200]
				raise RuntimeError(f"CDN upload client error {res.status_code}: {err}")
			if res.status_code == 200:
				param = res.headers.get("x-encrypted-param") or ""
				if param:
					return param
				last_err = "CDN upload response missing x-encrypted-param header"
			else:
				last_err = res.headers.get("x-error-message") or f"CDN upload status {res.status_code}"
			if attempt == 2:
				break
		raise RuntimeError(last_err)

	async def cdn_download(
		self,
		*,
		encrypt_query_param: str = "",
		full_url: str = "",
		cdn_base: str = CDN_BASE_URL,
	) -> bytes:
		http = await self._ensure()
		full = (full_url or "").strip()
		if full:
			url = full
		elif encrypt_query_param:
			url = (
				f"{cdn_base.rstrip('/')}/download"
				f"?encrypted_query_param={quote(encrypt_query_param, safe='')}"
			)
		else:
			raise RuntimeError("CDN download URL missing")
		res = await http.get(
			url,
			timeout=httpx.Timeout(connect=10.0, read=60.0, write=15.0, pool=5.0),
		)
		res.raise_for_status()
		return res.content

	async def sendmessage(
		self,
		token: str,
		*,
		to_user_id: str,
		context_token: str,
		text: str | None = None,
		items: list[dict[str, Any]] | None = None,
		timeout: float | None = 12.0,
	) -> dict[str, Any]:
		client_id = f"xeyo-{uuid.uuid4().hex[:12]}"
		item_list = items
		if item_list is None:
			item_list = [{"type": 1, "text_item": {"text": text or ""}}]
		return await self.request(
			"POST",
			"ilink/bot/sendmessage",
			token=token,
			body={
				"msg": {
					"from_user_id": "",
					"to_user_id": to_user_id,
					"client_id": client_id,
					"message_type": 2,
					"message_state": 2,
					"context_token": context_token,
					"item_list": item_list,
				},
				"base_info": base_info(),
			},
			timeout=timeout,
		)
