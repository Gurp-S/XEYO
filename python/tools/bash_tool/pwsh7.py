"""pwsh7 — PowerShell 7 内置引导器（阶段二）。

三条获取路径（``locate`` 顺序）：
1. ``XEYO_PWSH`` — 直接指定 pwsh.exe 路径（GUI/安装器注入）
2. ``XEYO_PWSH_DIR`` — 指定含 pwsh.exe 的目录（Tauri 分发 zip 的解压处）
3. 内置缓存 ``%LOCALAPPDATA%\\XEYO\\runtimes\\pwsh\\pwsh-<ver>\\pwsh.exe``
   （懒下载落点 / install_from_zip 落点）
4. PATH 上的 ``pwsh``（用户自装）

下载红线（冻结）：
- 固定 LTS 版本（``PINNED_VERSION``），不追新
- 只取官方 GitHub Release 资产；zip 必须与同 release 的 ``hashes.sha256``
  清单比对，缺清单/不匹配 → 拒绝安装（fail-closed）
- 自动下载默认**关**（``XEYO_PWSH_AUTO_DOWNLOAD=1`` 显式开启）；
  网络失败静默返回 None，上层落回 PowerShell 5.1，绝不阻塞 Bash 主路径
"""

from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
from pathlib import Path

PINNED_VERSION = "7.4.6"
_GITHUB_RELEASE = f"https://github.com/PowerShell/PowerShell/releases/download/v{PINNED_VERSION}"
_ZIP_NAME = f"PowerShell-{PINNED_VERSION}-win-x64.zip"
_HASHES_NAME = "hashes.sha256"
_DOWNLOAD_TIMEOUT_S = 120


def _cache_root() -> Path:
	local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
	return Path(local) / "XEYO" / "runtimes" / "pwsh" / f"pwsh-{PINNED_VERSION}"


def _sha256_file(p: Path) -> str:
	h = hashlib.sha256()
	with open(p, "rb") as f:
		for chunk in iter(lambda: f.read(1 << 20), b""):
			h.update(chunk)
	return h.hexdigest()


def _parse_hashes_txt(text: str, filename: str) -> str | None:
	"""官方 hashes.sha256：每行 ``<sha256>  <filename>``。"""
	fn = filename.lower()
	for line in text.splitlines():
		line = line.strip()
		if not line or " " not in line:
			continue
		digest, _, name = line.partition(" ")
		name = name.strip().lstrip("*").lower()
		if name == fn and len(digest.strip()) == 64:
			return digest.strip().lower()
	return None


def _extract_zip_safe(zip_path: Path, dest: Path) -> list[str]:
	"""解压并防 zip-slip：解析后不在 dest 内的成员跳过。返回已写成员名。"""
	written: list[str] = []
	dest_resolved = dest.resolve()
	with zipfile.ZipFile(zip_path) as zf:
		for info in zf.infolist():
			name = info.filename.replace("\\", "/")
			if name.startswith("/") or ".." in Path(name).parts:
				continue  # 绝对路径/上跳成员一律跳过
			target = (dest / name).resolve()
			if target != dest_resolved and dest_resolved not in target.parents:
				continue
			if info.is_dir():
				target.mkdir(parents=True, exist_ok=True)
				continue
			target.parent.mkdir(parents=True, exist_ok=True)
			with zf.open(info) as src, open(target, "wb") as out:
				for chunk in iter(lambda: src.read(1 << 20), b""):
					out.write(chunk)
			written.append(info.filename)
	return written


def install_from_zip(zip_path: str | Path, expected_sha256: str | None = None) -> Path:
	"""安装包内置路线：校验（可选固定哈希）→ 解压到内置缓存 → 返回 pwsh.exe。

	Human 操作流：Tauri 安装器把官方 zip 放好 → 调本函数 → 重启会话生效。
	哈希不符/成员不安全抛 ``ValueError``。
	"""
	src = Path(zip_path)
	if not src.is_file():
		raise ValueError(f"zip not found: {src}")
	if expected_sha256 is not None:
		actual = _sha256_file(src)
		if actual.lower() != expected_sha256.lower():
			raise ValueError(
				f"pwsh zip hash mismatch: expected {expected_sha256}, got {actual}"
			)
	dest = _cache_root()
	_extract_zip_safe(src, dest)
	exe = dest / "pwsh.exe"
	if not exe.is_file():
		raise ValueError(f"pwsh.exe missing after extract: {dest}")
	return exe


def _fetch(url: str) -> bytes:
	import urllib.request

	req = urllib.request.Request(url, headers={"User-Agent": "XEYO-pwsh-bootstrapper"})
	with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT_S) as resp:
		return resp.read()


def download_and_install() -> Path:
	"""懒下载路线：官方 zip + 官方 hashes.sha256 校验 → 解压。失败抛 RuntimeError。"""
	import tempfile

	zip_url = f"{_GITHUB_RELEASE}/{_ZIP_NAME}"
	hash_url = f"{_GITHUB_RELEASE}/{_HASHES_NAME}"
	try:
		hashes_text = _fetch(hash_url).decode("utf-8", errors="replace")
	except Exception as exc:  # noqa: BLE001 — 缺清单即拒绝（fail-closed）
		raise RuntimeError(f"cannot fetch official hash list ({_HASHES_NAME}): {exc}") from exc
	expected = _parse_hashes_txt(hashes_text, _ZIP_NAME)
	if not expected:
		raise RuntimeError(f"{_ZIP_NAME} not listed in official hash list; refusing to install")
	with tempfile.TemporaryDirectory(prefix="xeyo-pwsh-") as td:
		zip_path = Path(td) / _ZIP_NAME
		try:
			zip_path.write_bytes(_fetch(zip_url))
		except Exception as exc:  # noqa: BLE001
			raise RuntimeError(f"download failed: {exc}") from exc
		actual = _sha256_file(zip_path)
		if actual != expected:
			raise RuntimeError(
				f"pwsh zip hash mismatch: expected {expected}, got {actual}; refusing to install"
			)
		return install_from_zip(zip_path, expected_sha256=expected)


def locate() -> Path | None:
	"""定位 pwsh.exe；找不到返回 None（不下载、不阻塞）。非 Windows 恒 None。"""
	if os.name != "nt":
		return None
	direct = os.environ.get("XEYO_PWSH", "").strip()
	if direct and Path(direct).is_file():
		return Path(direct)
	dir_env = os.environ.get("XEYO_PWSH_DIR", "").strip()
	if dir_env:
		cand = Path(dir_env) / "pwsh.exe"
		if cand.is_file():
			return cand
	cache = _cache_root() / "pwsh.exe"
	if cache.is_file():
		return cache
	which = shutil.which("pwsh")
	if which:
		return Path(which)
	return None


def ensure() -> Path | None:
	"""locate；缺且允许自动下载（env 显式开）→ 下载安装；任何失败返回 None。"""
	found = locate()
	if found is not None:
		return found
	auto = os.environ.get("XEYO_PWSH_AUTO_DOWNLOAD", "").strip().lower() in ("1", "true", "yes")
	if not auto:
		return None
	try:
		download_and_install()
	except Exception:  # noqa: BLE001 — 下载失败不致命，落回 5.1
		return None
	return locate()
