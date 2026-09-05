"""iLink CDN：AES-128-ECB（PKCS7）与 aes_key 两种编码。

优先 cryptography；未安装时用纯 Python（系统 Python 3.14 无 wheel 也能发图）。
"""

from __future__ import annotations

import base64
import re

_HEX32 = re.compile(rb"^[0-9a-fA-F]{32}$")

# FIPS-197 AES S 盒
_SBOX = bytes.fromhex(
	"637c777bf26b6fc53001672bfed7ab76"
	"ca82c97dfa5947f0add4a2af9ca472c0"
	"b7fd9326363ff7cc34a5e5f171d83115"
	"04c723c31896059a071280e2eb27b275"
	"09832c1a1b6e5aa0523bd6b329e32f84"
	"53d100ed20fcb15b6acbbe394a4c58cf"
	"d0efaafb434d338545f9027f503c9fa8"
	"51a3408f929d38f5bcb6da2110fff3d2"
	"cd0c13ec5f974417c4a77e3d645d1973"
	"60814fdc222a908846eeb814de5e0bdb"
	"e0323a0a4906245cc2d3ac629195e479"
	"e7c8376d8dd54ea96c56f4ea657aae08"
	"ba78252e1ca6b4c6e8dd741f4bbd8b8a"
	"703eb5664803f60e613557b986c11d9e"
	"e1f8981169d98e949b1e87e9ce5528df"
	"8ca1890dbfe6426841992d0fb054bb16"
)
_INV_ARR = bytearray(256)
for i, v in enumerate(_SBOX):
	_INV_ARR[v] = i
_INV_SBOX = bytes(_INV_ARR)


def aes_ecb_padded_size(plaintext_size: int) -> int:
	"""PKCS7 至少补 1 字节，对齐 16。"""
	return ((plaintext_size + 16) // 16) * 16


def _pkcs7_pad(data: bytes) -> bytes:
	n = 16 - (len(data) % 16)
	return data + bytes([n]) * n


def _pkcs7_unpad(data: bytes) -> bytes:
	if not data or len(data) % 16:
		raise ValueError("invalid PKCS7 ciphertext")
	n = data[-1]
	if n < 1 or n > 16 or data[-n:] != bytes([n]) * n:
		raise ValueError("invalid PKCS7 padding")
	return data[:-n]


def _xtime(a: int) -> int:
	return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else (a << 1) & 0xFF


def _expand_key(key: bytes) -> bytes:
	rk = bytearray(key)
	rcon = 1
	while len(rk) < 176:
		t0, t1, t2, t3 = rk[-4], rk[-3], rk[-2], rk[-1]
		if len(rk) % 16 == 0:
			t0, t1, t2, t3 = _SBOX[t1] ^ rcon, _SBOX[t2], _SBOX[t3], _SBOX[t0]
			rcon = _xtime(rcon)
		base = len(rk) - 16
		rk.append(rk[base] ^ t0)
		rk.append(rk[base + 1] ^ t1)
		rk.append(rk[base + 2] ^ t2)
		rk.append(rk[base + 3] ^ t3)
	return bytes(rk)


def _add(state: bytes, rk: bytes, off: int) -> bytes:
	return bytes(state[i] ^ rk[off + i] for i in range(16))


def _sub(state: bytes, box: bytes) -> bytes:
	return bytes(box[b] for b in state)


def _shift(state: bytes) -> bytes:
	s = bytearray(state)
	s[1], s[5], s[9], s[13] = s[5], s[9], s[13], s[1]
	s[2], s[6], s[10], s[14] = s[10], s[14], s[2], s[6]
	s[3], s[7], s[11], s[15] = s[15], s[3], s[7], s[11]
	return bytes(s)


def _inv_shift(state: bytes) -> bytes:
	s = bytearray(state)
	s[1], s[5], s[9], s[13] = s[13], s[1], s[5], s[9]
	s[2], s[6], s[10], s[14] = s[10], s[14], s[2], s[6]
	s[3], s[7], s[11], s[15] = s[7], s[11], s[15], s[3]
	return bytes(s)


def _mix_col(a: int, b: int, c: int, d: int) -> tuple[int, int, int, int]:
	return (
		_xtime(a) ^ _xtime(b) ^ b ^ c ^ d,
		a ^ _xtime(b) ^ _xtime(c) ^ c ^ d,
		a ^ b ^ _xtime(c) ^ _xtime(d) ^ d,
		_xtime(a) ^ a ^ b ^ c ^ _xtime(d),
	)


def _mix(state: bytes) -> bytes:
	out = bytearray(16)
	for col in range(4):
		i = 4 * col
		out[i], out[i + 1], out[i + 2], out[i + 3] = _mix_col(
			state[i], state[i + 1], state[i + 2], state[i + 3]
		)
	return bytes(out)


def _mul(x: int, y: int) -> int:
	p = 0
	for _ in range(8):
		if y & 1:
			p ^= x
		hi = x & 0x80
		x = (x << 1) & 0xFF
		if hi:
			x ^= 0x1B
		y >>= 1
	return p


def _inv_mix(state: bytes) -> bytes:
	out = bytearray(16)
	for col in range(4):
		i = 4 * col
		a, b, c, d = state[i], state[i + 1], state[i + 2], state[i + 3]
		out[i] = _mul(a, 0x0E) ^ _mul(b, 0x0B) ^ _mul(c, 0x0D) ^ _mul(d, 0x09)
		out[i + 1] = _mul(a, 0x09) ^ _mul(b, 0x0E) ^ _mul(c, 0x0B) ^ _mul(d, 0x0D)
		out[i + 2] = _mul(a, 0x0D) ^ _mul(b, 0x09) ^ _mul(c, 0x0E) ^ _mul(d, 0x0B)
		out[i + 3] = _mul(a, 0x0B) ^ _mul(b, 0x0D) ^ _mul(c, 0x09) ^ _mul(d, 0x0E)
	return bytes(out)


def _encrypt_block(block: bytes, rk: bytes) -> bytes:
	s = _add(block, rk, 0)
	for rnd in range(1, 10):
		s = _mix(_shift(_sub(s, _SBOX)))
		s = _add(s, rk, rnd * 16)
	return _add(_shift(_sub(s, _SBOX)), rk, 160)


def _decrypt_block(block: bytes, rk: bytes) -> bytes:
	s = _inv_shift(_sub(_add(block, rk, 160), _INV_SBOX))
	for rnd in range(9, 0, -1):
		s = _inv_shift(_sub(_inv_mix(_add(s, rk, rnd * 16)), _INV_SBOX))
	return _add(s, rk, 0)


def encrypt_aes_ecb_stdlib(plaintext: bytes, key: bytes) -> bytes:
	rk = _expand_key(key)
	padded = _pkcs7_pad(plaintext)
	out = bytearray()
	for i in range(0, len(padded), 16):
		out.extend(_encrypt_block(padded[i : i + 16], rk))
	return bytes(out)


def decrypt_aes_ecb_stdlib(ciphertext: bytes, key: bytes) -> bytes:
	if not ciphertext or len(ciphertext) % 16:
		raise ValueError("ciphertext must be a multiple of 16")
	rk = _expand_key(key)
	out = bytearray()
	for i in range(0, len(ciphertext), 16):
		out.extend(_decrypt_block(ciphertext[i : i + 16], rk))
	return _pkcs7_unpad(bytes(out))


def _try_cryptography_encrypt(plaintext: bytes, key: bytes) -> bytes | None:
	try:
		from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
		from cryptography.hazmat.primitives.padding import PKCS7
	except ImportError:
		return None
	padder = PKCS7(128).padder()
	padded = padder.update(plaintext) + padder.finalize()
	enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
	return enc.update(padded) + enc.finalize()


def _try_cryptography_decrypt(ciphertext: bytes, key: bytes) -> bytes | None:
	try:
		from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
		from cryptography.hazmat.primitives.padding import PKCS7
	except ImportError:
		return None
	dec = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
	padded = dec.update(ciphertext) + dec.finalize()
	unpad = PKCS7(128).unpadder()
	return unpad.update(padded) + unpad.finalize()


def encrypt_aes_ecb(plaintext: bytes, key: bytes) -> bytes:
	if len(key) != 16:
		raise ValueError("AES-128 key must be 16 bytes")
	got = _try_cryptography_encrypt(plaintext, key)
	if got is not None:
		return got
	return encrypt_aes_ecb_stdlib(plaintext, key)


def decrypt_aes_ecb(ciphertext: bytes, key: bytes) -> bytes:
	if len(key) != 16:
		raise ValueError("AES-128 key must be 16 bytes")
	got = _try_cryptography_decrypt(ciphertext, key)
	if got is not None:
		return got
	return decrypt_aes_ecb_stdlib(ciphertext, key)


def encode_cdn_aes_key(raw16: bytes) -> str:
	"""出站统一用官方格式 B：base64(hex 字符串)。"""
	if len(raw16) != 16:
		raise ValueError("AES-128 key must be 16 bytes")
	return base64.b64encode(raw16.hex().encode("ascii")).decode("ascii")


def parse_aes_key(*, aes_key_b64: str | None = None, aeskey_hex: str | None = None) -> bytes:
	"""入站兼容：image_item.aeskey hex 优先，否则 CDNMedia.aes_key。"""
	hx = (aeskey_hex or "").strip()
	if len(hx) == 32 and all(c in "0123456789abcdefABCDEF" for c in hx):
		return bytes.fromhex(hx)
	raw = (aes_key_b64 or "").strip()
	if not raw:
		raise ValueError("missing aes_key")
	decoded = base64.b64decode(raw)
	if len(decoded) == 16:
		return decoded
	if len(decoded) == 32 and _HEX32.match(decoded):
		return bytes.fromhex(decoded.decode("ascii"))
	raise ValueError(f"aes_key must be 16 raw bytes or 32-char hex, got {len(decoded)}")
