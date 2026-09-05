"""把登录 URL 编成 QR PNG（stdlib only）。

iLink 的 qrcode_img_content 是微信可识别的 URL，不是图片。
"""

from __future__ import annotations

import struct
import zlib

# ECC-M：每块 (data_codewords, ec_codewords)
_BLOCKS_M: dict[int, list[tuple[int, int]]] = {
	1: [(16, 10)],
	2: [(28, 16)],
	3: [(44, 26)],
	4: [(32, 18), (32, 18)],
	5: [(43, 24), (43, 24)],
	6: [(27, 16), (27, 16), (27, 16), (27, 16)],
}

_ALIGN: dict[int, list[int]] = {
	1: [],
	2: [6, 18],
	3: [6, 22],
	4: [6, 26],
	5: [6, 30],
	6: [6, 34],
}

_EXP = [0] * 512
_LOG = [0] * 256


def _init_gf() -> None:
	x = 1
	for i in range(255):
		_EXP[i] = x
		_LOG[x] = i
		x <<= 1
		if x & 0x100:
			x ^= 0x11D
	for i in range(255, 512):
		_EXP[i] = _EXP[i - 255]


_init_gf()


def _gf_mul(a: int, b: int) -> int:
	if a == 0 or b == 0:
		return 0
	return _EXP[_LOG[a] + _LOG[b]]


def _poly_mul(p: list[int], q: list[int]) -> list[int]:
	out = [0] * (len(p) + len(q) - 1)
	for i, a in enumerate(p):
		for j, b in enumerate(q):
			out[i + j] ^= _gf_mul(a, b)
	return out


def _rs_encode(data: list[int], nsym: int) -> list[int]:
	gen = [1]
	for i in range(nsym):
		gen = _poly_mul(gen, [1, _EXP[i]])
	out = list(data) + [0] * nsym
	for i in range(len(data)):
		coef = out[i]
		if coef == 0:
			continue
		for j in range(1, len(gen)):
			out[i + j] ^= _gf_mul(gen[j], coef)
	return out[len(data) :]


def _size(version: int) -> int:
	return 21 + 4 * (version - 1)


def _capacity_bytes(version: int) -> int:
	data_cw = sum(d for d, _e in _BLOCKS_M[version])
	# 模式(4) + 长度(8) + 终止符(4) ≈ 2 个码字
	return data_cw - 2


def _pick_version(n: int) -> int:
	for v in range(1, 7):
		if _capacity_bytes(v) >= n:
			return v
	raise ValueError(f"QR payload too long ({n} bytes)")


def _encode_data(payload: bytes, version: int) -> list[int]:
	data_cw = sum(d for d, _e in _BLOCKS_M[version])
	bits: list[int] = []

	def put(val: int, n: int) -> None:
		for i in range(n - 1, -1, -1):
			bits.append((val >> i) & 1)

	put(0b0100, 4)
	put(len(payload), 8)
	for b in payload:
		put(b, 8)
	put(0, min(4, data_cw * 8 - len(bits)))
	while len(bits) % 8:
		bits.append(0)
	bytes_out = []
	for i in range(0, len(bits), 8):
		v = 0
		for b in bits[i : i + 8]:
			v = (v << 1) | b
		bytes_out.append(v)
	pad = (0xEC, 0x11)
	pi = 0
	while len(bytes_out) < data_cw:
		bytes_out.append(pad[pi % 2])
		pi += 1
	return bytes_out[:data_cw]


def _interleave(data: list[int], version: int) -> list[int]:
	blocks_spec = _BLOCKS_M[version]
	blocks: list[tuple[list[int], list[int]]] = []
	i = 0
	for dlen, elen in blocks_spec:
		chunk = data[i : i + dlen]
		i += dlen
		blocks.append((chunk, _rs_encode(chunk, elen)))
	out: list[int] = []
	max_d = max(len(d) for d, _e in blocks)
	max_e = max(len(e) for _d, e in blocks)
	for j in range(max_d):
		for d, _e in blocks:
			if j < len(d):
				out.append(d[j])
	for j in range(max_e):
		for _d, e in blocks:
			if j < len(e):
				out.append(e[j])
	return out


def _finder(m: list[list[int]], x: int, y: int) -> None:
	for dy in range(7):
		for dx in range(7):
			border = dx in (0, 6) or dy in (0, 6)
			core = 2 <= dx <= 4 and 2 <= dy <= 4
			m[y + dy][x + dx] = 1 if (border or core) else 0


def _align(m: list[list[int]], cx: int, cy: int) -> None:
	for dy in range(-2, 3):
		for dx in range(-2, 3):
			xx, yy = cx + dx, cy + dy
			m[yy][xx] = 1 if max(abs(dx), abs(dy)) in (0, 2) else 0


def _reserved(version: int) -> list[list[bool]]:
	n = _size(version)
	r = [[False] * n for _ in range(n)]

	def mark(x: int, y: int, w: int, h: int) -> None:
		for yy in range(y, y + h):
			for xx in range(x, x + w):
				if 0 <= xx < n and 0 <= yy < n:
					r[yy][xx] = True

	mark(0, 0, 9, 9)
	mark(n - 8, 0, 8, 9)
	mark(0, n - 8, 9, 8)
	mark(6, 0, 1, n)
	mark(0, 6, n, 1)
	for a in _ALIGN[version]:
		for b in _ALIGN[version]:
			if (a == 6 and b == 6) or (a == 6 and b == n - 7) or (a == n - 7 and b == 6):
				continue
			mark(a - 2, b - 2, 5, 5)
	return r


def _place_function(m: list[list[int]], version: int) -> None:
	n = len(m)
	for i in range(n):
		m[6][i] = 1 if i % 2 == 0 else 0
		m[i][6] = 1 if i % 2 == 0 else 0
	_finder(m, 0, 0)
	_finder(m, n - 7, 0)
	_finder(m, 0, n - 7)
	for a in _ALIGN[version]:
		for b in _ALIGN[version]:
			if (a <= 8 and b <= 8) or (a <= 8 and b >= n - 9) or (a >= n - 9 and b <= 8):
				continue
			_align(m, a, b)
	m[n - 8][8] = 1


def _place_data(m: list[list[int]], reserved: list[list[bool]], data: list[int]) -> None:
	n = len(m)
	bits: list[int] = []
	for b in data:
		for i in range(7, -1, -1):
			bits.append((b >> i) & 1)
	bi = 0
	up = True
	x = n - 1
	while x > 0:
		if x == 6:
			x -= 1
		ys = range(n - 1, -1, -1) if up else range(n)
		for y in ys:
			for dx in (0, -1):
				xx = x + dx
				if reserved[y][xx]:
					continue
				m[y][xx] = bits[bi] if bi < len(bits) else 0
				bi += 1
		up = not up
		x -= 2


def _mask_fn(mask: int):
	fns = [
		lambda x, y: (x + y) % 2 == 0,
		lambda x, y: y % 2 == 0,
		lambda x, y: x % 3 == 0,
		lambda x, y: (x + y) % 3 == 0,
		lambda x, y: (y // 2 + x // 3) % 2 == 0,
		lambda x, y: (x * y) % 2 + (x * y) % 3 == 0,
		lambda x, y: ((x * y) % 2 + (x * y) % 3) % 2 == 0,
		lambda x, y: ((x + y) % 2 + (x * y) % 3) % 2 == 0,
	]
	return fns[mask]


def _apply_mask(m: list[list[int]], reserved: list[list[bool]], mask: int) -> list[list[int]]:
	n = len(m)
	fn = _mask_fn(mask)
	out = [row[:] for row in m]
	for y in range(n):
		for x in range(n):
			if not reserved[y][x] and fn(x, y):
				out[y][x] ^= 1
	return out


def _format_bits(mask: int) -> int:
	data = (0b00 << 3) | mask  # M = 00
	rem = data << 10
	g = 0b10100110111
	for i in range(4, -1, -1):
		if rem & (1 << (i + 10)):
			rem ^= g << i
	return ((data << 10) | rem) ^ 0b101010000010010


def _place_format(m: list[list[int]], mask: int) -> None:
	n = len(m)
	bits = _format_bits(mask)
	for i in range(6):
		m[i][8] = (bits >> i) & 1
	m[7][8] = (bits >> 6) & 1
	m[8][8] = (bits >> 7) & 1
	m[8][7] = (bits >> 8) & 1
	for i in range(9, 15):
		m[8][14 - i] = (bits >> i) & 1
	for i in range(8):
		m[8][n - 1 - i] = (bits >> i) & 1
	for i in range(8, 15):
		m[n - 15 + i][8] = (bits >> i) & 1


def _penalty(m: list[list[int]]) -> int:
	n = len(m)
	score = 0
	for y in range(n):
		run = 1
		for x in range(1, n):
			if m[y][x] == m[y][x - 1]:
				run += 1
			else:
				if run >= 5:
					score += 3 + (run - 5)
				run = 1
		if run >= 5:
			score += 3 + (run - 5)
	for x in range(n):
		run = 1
		for y in range(1, n):
			if m[y][x] == m[y - 1][x]:
				run += 1
			else:
				if run >= 5:
					score += 3 + (run - 5)
				run = 1
		if run >= 5:
			score += 3 + (run - 5)
	for y in range(n - 1):
		for x in range(n - 1):
			if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
				score += 3
	pat = (1, 0, 1, 1, 1, 0, 1)
	for y in range(n):
		row = m[y]
		for x in range(n - 6):
			if tuple(row[x : x + 7]) == pat:
				score += 40
	for x in range(n):
		col = [m[y][x] for y in range(n)]
		for y in range(n - 6):
			if tuple(col[y : y + 7]) == pat:
				score += 40
	dark = sum(sum(row) for row in m)
	k = abs(dark * 20 - n * n * 10) // (n * n)
	score += k * 10
	return score


def qr_matrix(payload: str) -> list[list[int]]:
	raw = payload.encode("utf-8")
	version = _pick_version(len(raw))
	data = _interleave(_encode_data(raw, version), version)
	n = _size(version)
	base = [[0] * n for _ in range(n)]
	reserved = _reserved(version)
	_place_function(base, version)
	_place_data(base, reserved, data)
	best = None
	best_score = 10**9
	for mask in range(8):
		cand = _apply_mask(base, reserved, mask)
		_place_function(cand, version)
		_place_format(cand, mask)
		s = _penalty(cand)
		if s < best_score:
			best_score = s
			best = cand
	assert best is not None
	return best


def _png(matrix: list[list[int]], *, scale: int = 8, border: int = 3) -> bytes:
	n = len(matrix)
	dim = (n + border * 2) * scale
	rows = []
	for y in range(dim):
		my = y // scale - border
		row = bytearray(dim + 1)
		row[0] = 0
		for x in range(dim):
			mx = x // scale - border
			black = 0 <= mx < n and 0 <= my < n and matrix[my][mx]
			row[x + 1] = 0 if black else 255
		rows.append(bytes(row))
	raw = b"".join(rows)

	def chunk(tag: bytes, data: bytes) -> bytes:
		crc = zlib.crc32(tag + data) & 0xFFFFFFFF
		return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

	ihdr = struct.pack(">IIBBBBB", dim, dim, 8, 0, 0, 0, 0)
	return (
		b"\x89PNG\r\n\x1a\n"
		+ chunk(b"IHDR", ihdr)
		+ chunk(b"IDAT", zlib.compress(raw, 9))
		+ chunk(b"IEND", b"")
	)


def render_qr_png(payload: str) -> bytes:
	text = (payload or "").strip()
	if not text:
		raise ValueError("empty QR payload")
	return _png(qr_matrix(text))


def sniff_image(blob: bytes) -> str | None:
	if not blob:
		return None
	if blob.startswith(b"\x89PNG\r\n\x1a\n"):
		return "image/png"
	if blob.startswith(b"\xff\xd8\xff"):
		return "image/jpeg"
	s = blob.lstrip()
	if s.startswith(b"<svg") or (s.startswith(b"<?xml") and b"<svg" in s[:240]):
		return "image/svg+xml"
	if s.startswith(b"GIF8"):
		return "image/gif"
	return None


def looks_like_image_url(url: str) -> bool:
	path = url.split("?", 1)[0].lower()
	return path.endswith((".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"))
