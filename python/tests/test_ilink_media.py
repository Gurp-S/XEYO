"""iLink 图片/文件：AES、CDN 报文、入站拼装。"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from channels.ilink.client import ILinkClient
from channels.ilink.crypto import (
	aes_ecb_padded_size,
	decrypt_aes_ecb,
	encode_cdn_aes_key,
	encrypt_aes_ecb,
	parse_aes_key,
)
from channels.ilink.media import (
	InboundMedia,
	file_item,
	image_item,
	inbound_prompt,
	upload_local,
)


def test_aes_ecb_roundtrip_and_padding():
	assert aes_ecb_padded_size(0) == 16
	assert aes_ecb_padded_size(1) == 16
	assert aes_ecb_padded_size(15) == 16
	assert aes_ecb_padded_size(16) == 32
	assert aes_ecb_padded_size(32) == 48
	key = bytes(range(16))
	plain = b"hello world 1234"
	ct = encrypt_aes_ecb(plain, key)
	assert len(ct) == 32
	assert decrypt_aes_ecb(ct, key) == plain


def test_aes_stdlib_nist_and_matches_cryptography():
	from channels.ilink.crypto import (
		_decrypt_block,
		_encrypt_block,
		_expand_key,
		decrypt_aes_ecb_stdlib,
		encrypt_aes_ecb_stdlib,
	)

	key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
	plain_block = bytes.fromhex("00112233445566778899aabbccddeeff")
	rk = _expand_key(key)
	ct_block = _encrypt_block(plain_block, rk)
	assert ct_block.hex() == "69c4e0d86a7b0430d8cdb78070b4c55a"
	assert _decrypt_block(ct_block, rk) == plain_block

	plain = b"hello world 1234"
	stdlib_ct = encrypt_aes_ecb_stdlib(plain, key)
	assert decrypt_aes_ecb_stdlib(stdlib_ct, key) == plain
	assert encrypt_aes_ecb(plain, key) == stdlib_ct
	assert decrypt_aes_ecb(stdlib_ct, key) == plain


def test_aes_key_encodings():
	raw = bytes.fromhex("00112233445566778899aabbccddeeff")
	fmt_a = base64.b64encode(raw).decode("ascii")
	fmt_b = encode_cdn_aes_key(raw)
	assert fmt_b == base64.b64encode(raw.hex().encode("ascii")).decode("ascii")
	assert parse_aes_key(aes_key_b64=fmt_a) == raw
	assert parse_aes_key(aes_key_b64=fmt_b) == raw
	assert parse_aes_key(aeskey_hex=raw.hex()) == raw


def test_inbound_prompt_image_and_file(tmp_path: Path):
	img = tmp_path / "a.png"
	fil = tmp_path / "note.txt"
	img.write_bytes(b"x")
	fil.write_bytes(b"y")
	body, urls = inbound_prompt(
		"看看",
		[
			InboundMedia(
				kind="image",
				path=img,
				name="a.png",
				mime="image/png",
				data_url="data:image/png;base64,xx",
			),
			InboundMedia(kind="file", path=fil, name="note.txt", mime="text/plain"),
		],
	)
	assert "看看" in body
	assert str(img) in body
	assert "note.txt" in body
	assert urls == ["data:image/png;base64,xx"]


@pytest.mark.asyncio
async def test_sendmessage_image_item_shape():
	captured: list[dict] = []

	def handler(request: httpx.Request) -> httpx.Response:
		if "sendmessage" in str(request.url):
			captured.append(json.loads(request.content.decode("utf-8")))
			return httpx.Response(200, json={"ret": 0})
		return httpx.Response(404, json={"ret": -1})

	client = ILinkClient(transport=httpx.MockTransport(handler))
	info_key = encode_cdn_aes_key(bytes(range(16)))
	from channels.ilink.media import UploadInfo

	item = image_item(
		UploadInfo(
			download_param="dl-param",
			aes_key_b64=info_key,
			raw_size=10,
			cipher_size=16,
			raw_md5="abc",
			file_name="x.png",
		)
	)
	await client.sendmessage(
		"tok",
		to_user_id="u1",
		context_token="ctx",
		items=[item],
	)
	msg = captured[0]["msg"]
	assert msg["context_token"] == "ctx"
	assert msg["item_list"][0]["type"] == 2
	assert msg["item_list"][0]["image_item"]["media"]["encrypt_query_param"] == "dl-param"
	assert file_item(
		UploadInfo(
			download_param="dl",
			aes_key_b64=info_key,
			raw_size=3,
			cipher_size=16,
			raw_md5="d",
			file_name="a.bin",
		)
	)["type"] == 4
	await client.aclose()


@pytest.mark.asyncio
async def test_upload_local_getuploadurl_and_cdn(tmp_path: Path):
	src = tmp_path / "pic.png"
	src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"hello")
	calls: list[str] = []

	def handler(request: httpx.Request) -> httpx.Response:
		url = str(request.url)
		calls.append(url)
		if "getuploadurl" in url:
			body = json.loads(request.content.decode("utf-8"))
			assert body["media_type"] == 1
			assert body["no_need_thumb"] is True
			assert body["rawsize"] == src.stat().st_size
			assert len(body["aeskey"]) == 32
			assert body["filesize"] == aes_ecb_padded_size(body["rawsize"])
			return httpx.Response(200, json={"ret": 0, "upload_param": "up-1"})
		if "/c2c/upload" in url or "upload?encrypted" in url:
			assert request.headers.get("content-type") == "application/octet-stream"
			assert len(request.content) == aes_ecb_padded_size(src.stat().st_size)
			return httpx.Response(
				200,
				headers={"x-encrypted-param": "dl-1"},
				content=b"",
			)
		return httpx.Response(404, json={"ret": -1, "errmsg": url})

	client = ILinkClient(transport=httpx.MockTransport(handler))
	info = await upload_local(client, "tok", "user-1", src, media_type=1)
	assert info.download_param == "dl-1"
	assert info.raw_size == src.stat().st_size
	assert any("getuploadurl" in u for u in calls)
	await client.aclose()


@pytest.mark.asyncio
async def test_collect_inbound_image_decrypts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
	from channels.ilink import media as media_mod

	monkeypatch.setattr(media_mod, "inbound_dir", lambda: tmp_path)
	key = bytes(range(16))
	png = b"\x89PNG\r\n\x1a\n" + b"abc"
	ct = encrypt_aes_ecb(png, key)

	def handler(request: httpx.Request) -> httpx.Response:
		if "download" in str(request.url):
			return httpx.Response(200, content=ct)
		return httpx.Response(404)

	client = ILinkClient(transport=httpx.MockTransport(handler))
	got = await media_mod.collect_inbound_media(
		client,
		{
			"item_list": [
				{
					"type": 2,
					"image_item": {
						"aeskey": key.hex(),
						"media": {
							"encrypt_query_param": "dl",
							"aes_key": encode_cdn_aes_key(key),
						},
					},
				}
			]
		},
	)
	assert len(got) == 1
	assert got[0].kind == "image"
	assert got[0].path.read_bytes() == png
	assert got[0].data_url and got[0].data_url.startswith("data:image/png")
	await client.aclose()


@pytest.mark.asyncio
async def test_collect_inbound_accepts_itemList_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
	from channels.ilink import media as media_mod

	monkeypatch.setattr(media_mod, "inbound_dir", lambda: tmp_path)
	key = bytes(range(16))
	png = b"\x89PNG\r\n\x1a\n" + b"abc"
	ct = encrypt_aes_ecb(png, key)

	def handler(request: httpx.Request) -> httpx.Response:
		if "download" in str(request.url):
			return httpx.Response(200, content=ct)
		return httpx.Response(404)

	client = ILinkClient(transport=httpx.MockTransport(handler))
	got = await media_mod.collect_inbound_media(
		client,
		{
			"itemList": [
				{
					"type": 2,
					"image_item": {
						"aeskey": key.hex(),
						"media": {
							"encrypt_query_param": "dl",
							"aes_key": encode_cdn_aes_key(key),
						},
					},
				}
			]
		},
	)
	assert len(got) == 1
	assert got[0].path.read_bytes() == png
	await client.aclose()
