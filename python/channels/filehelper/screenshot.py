"""主显示器截图 → 仓库根 screenshots/。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def repo_root() -> Path:
	# python/channels/filehelper/screenshot.py → 仓库根
	return Path(__file__).resolve().parents[3]


def screenshots_dir() -> Path:
	d = repo_root() / "screenshots"
	d.mkdir(parents=True, exist_ok=True)
	return d


def _downscale_rgb(rgb: bytes, size: tuple[int, int], max_side: int) -> tuple[bytes, tuple[int, int]]:
	w, h = size
	m = max(w, h)
	if m <= max_side:
		return rgb, size
	scale = max_side / m
	nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
	out = bytearray(nw * nh * 3)
	for y in range(nh):
		src_y = min(h - 1, int(y / scale))
		row = src_y * w
		dst_row = y * nw
		for x in range(nw):
			src_x = min(w - 1, int(x / scale))
			si = (row + src_x) * 3
			di = (dst_row + x) * 3
			out[di : di + 3] = rgb[si : si + 3]
	return bytes(out), (nw, nh)


def capture_primary(*, monitor: int = 1, preview_max_side: int = 1280) -> Path:
	try:
		import mss
		from mss.tools import to_png
	except ImportError as e:
		raise RuntimeError("mss not installed — pip install mss") from e

	dest = screenshots_dir() / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
	with mss.mss() as sct:
		monitors = sct.monitors
		if len(monitors) < 2:
			raise RuntimeError("no primary monitor for screenshot")
		idx = monitor if 0 < monitor < len(monitors) else 1
		grab = sct.grab(monitors[idx])
		to_png(grab.rgb, grab.size, output=str(dest))
		# 预览图供模型；失败不影响主文件
		try:
			rgb, size = _downscale_rgb(grab.rgb, grab.size, preview_max_side)
			preview = dest.with_name(dest.stem + ".preview.png")
			to_png(rgb, size, output=str(preview))
		except Exception:
			pass
	return dest


def preview_png(path: Path, *, max_bytes: int = 280_000) -> bytes:
	preview = path.with_name(path.stem + ".preview.png")
	candidate = preview if preview.is_file() else path
	try:
		data = candidate.read_bytes()
	except OSError:
		return b""
	if len(data) > max_bytes:
		return b""
	return data
