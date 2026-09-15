#!/usr/bin/env python
"""拉取本地模型运行期依赖：llama.cpp 可执行文件 + GGUF 权重。

为什么需要脚本而不是让用户手点：本机默认要下 ~8GB（两支 Q4_K_M 权重 + CUDA 版
llama.cpp）。手工做这件事的失败模式很多——下到半截的文件看起来"已经在了"、
解压层级搞错导致引擎探测不到 llama-server、用 CPU 版跑导致速度差 10 倍。
脚本把这些都收敛成一次可重复执行的动作。

单一事实来源：模型清单直接读 ``python/localmodels/catalog.py``，不另抄一份。
从这里加一支模型，脚本与设置面板同时可见。

用法::

    py -3.11 scripts/fetch-local-models.py                 # 全部拉齐
    py -3.11 scripts/fetch-local-models.py --only gguf     # 只拉权重
    py -3.11 scripts/fetch-local-models.py --model lfm25-8b-a1b
    py -3.11 scripts/fetch-local-models.py --llama-variant cpu-x64

环境变量：
- ``XEYO_HF_ENDPOINT``：HF 镜像地址（默认 ``https://hf-mirror.com``；
  直连可达时设为 ``https://huggingface.co``）。
- ``XEYO_GH_ENDPOINT``：GitHub 加速前缀（默认空 = 直连 github.com）。
  实测直连 release 资产会被限速到 ~0.04MB/s，516MB 的 CUDA 包要跑几小时；
  设成 ``https://gh-proxy.com/`` 这类前缀可到 MB/s 级。格式为
  ``<前缀>https://github.com/...``。
- ``XEYO_MODELS_DIR``：落盘目录（默认 ``~/.xeyo/local-models``）。
- ``GITHUB_TOKEN``（可选）：GitHub API 未鉴权限额 60 次/小时，超限时用
  ``--llama-tag b10950`` 直接指定版本即可绕过（不查 API）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))

from localmodels import catalog  # noqa: E402

HF_ENDPOINT = os.environ.get("XEYO_HF_ENDPOINT", "https://hf-mirror.com").rstrip("/")
#: GitHub 加速前缀（空 = 直连）。用法见模块 docstring。
GH_ENDPOINT = (os.environ.get("XEYO_GH_ENDPOINT") or "").strip()
GITHUB_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
CHUNK = 1 << 20


def _gh(url: str) -> str:
	"""把 release 资产 URL 套上加速前缀（未配置则原样返回）。"""
	return f"{GH_ENDPOINT}{url}" if GH_ENDPOINT else url


def models_dir() -> Path:
	raw = (os.environ.get("XEYO_MODELS_DIR") or "").strip()
	if raw:
		return Path(raw).expanduser()
	from localmodels import config

	return config.models_dir()


def _download(url: str, dest: Path, *, expect: int | None = None) -> bool:
	"""带续传的下载；返回"落盘文件是否与 ``expect`` 精确吻合"。

	为什么要求**精确**而不是"不小于"：续传竞态（两个进程写同一文件）或镜像返回
	错体都会让文件**偏大**，而偏大的 GGUF 能通过 `>=` 检查却在 llama.cpp 侧加载
	失败——"文件明明在，就是起不来"。偏大偏小一律视为未就绪并重下。
	"""
	if dest.is_file():
		have0 = dest.stat().st_size
		if expect is None and have0:
			print(f"  [skip] {dest.name} 已存在（{have0} 字节）")
			return True
		if expect is not None and have0 == expect:
			print(f"  [skip] {dest.name} 已就绪（{have0} 字节）")
			return True
		if expect is not None and have0 > expect:
			print(f"  [redo] {dest.name} 偏大（{have0} > {expect}），删除重下")
			_rm(dest)
	dest.parent.mkdir(parents=True, exist_ok=True)
	have = dest.stat().st_size if dest.is_file() else 0
	req = urllib.request.Request(url, headers={"User-Agent": "xeyo-fetch-local-models"})
	if have:
		req.add_header("Range", f"bytes={have}-")
	print(f"  [get ] {dest.name}" + (f"（续传 {have} 字节）" if have else ""))
	try:
		with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 — 固定上游
			# 只有服务端确认了 Range（206）才追加；否则从头写，避免把全文接在半截后面。
			mode = "ab" if have and resp.status == 206 else "wb"
			if mode == "wb":
				have = 0
			with open(dest, mode) as fh:
				done = have
				while True:
					chunk = resp.read(CHUNK)
					if not chunk:
						break
					fh.write(chunk)
					done += len(chunk)
					if expect:
						pct = min(100.0, done * 100.0 / expect)
						print(f"\r         {pct:5.1f}%  {done / 1048576:.0f}MB", end="")
		print()
	except (urllib.error.URLError, OSError) as exc:
		print(f"\n  [fail] {dest.name}: {exc}")
		return False
	if not dest.is_file():
		return False
	if expect is not None and dest.stat().st_size != expect:
		print(f"  [warn] {dest.name} 大小 {dest.stat().st_size} != 期望 {expect}")
		return False
	return True


def fetch_gguf(only: str | None) -> int:
	"""下载登记表里的 GGUF 权重。"""
	root = models_dir()
	print(f"[gguf] 目标目录 {root}  （镜像 {HF_ENDPOINT}）")
	fail = 0
	for m in catalog.LOCAL_MODELS:
		if only and m.id != only:
			continue
		url = f"{HF_ENDPOINT}/{m.repo}/resolve/main/{m.repo_file}"
		if not _download(url, root / m.filename, expect=m.size_bytes):
			fail += 1
	return fail


LLAMA_VARIANTS = (
	"cuda-13.3-x64",
	"cuda-12.4-x64",
	"cpu-x64",
	"vulkan-x64",
)


def _llama_release(variant: str) -> tuple[str, list[str]]:
	"""(发布标签, 需要下载的 zip 资产 URL 列表)。

	为什么查 releases 列表而不是 ``/releases/latest``：llama.cpp 的 latest 指向
	一个只放 ``nightly-tag.txt`` 的占位发布（``v0.4.0``），真正的 Windows 构建挂在
	``b10950`` 这类 nightly 标签上。所以按"哪个发布里真的有目标资产"来挑。

	GitHub 未鉴权 API 限额 60 次/小时，超了会返回 ``{"message": ...}`` 而不是列表。
	那种情况直接报错并提示改用 ``--llama-tag``（不查 API，直接拼资产 URL）。

	Windows 的 CUDA 包与 CUDA 运行时分两个 zip：没装 CUDA Toolkit 的机器必须把
	``cudart-*`` 那份也解到同一目录，否则 llama-server 起不来（缺 cudart64_*.dll）。
	"""
	req = urllib.request.Request(
		GITHUB_API,
		headers={
			"User-Agent": "xeyo-fetch-local-models",
			"Accept": "application/vnd.github+json",
			**({"Authorization": f"Bearer {GH_TOKEN}"} if GH_TOKEN else {}),
		},
	)
	with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 — 固定上游
		payload = json.load(resp)
	if isinstance(payload, dict):
		raise SystemExit(
			f"GitHub API 未返回发布列表（{payload.get('message') or payload}）；"
			"改用 --llama-tag <tag> 直接指定版本，或设 GITHUB_TOKEN 提高限额"
		)
	for rel in payload:
		assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
		tag = str(rel.get("tag_name") or "")
		main = f"llama-{tag}-bin-win-{variant}.zip"
		if main not in assets:
			continue
		cudart = f"cudart-llama-bin-win-{variant}.zip"
		want = [assets[main]] + ([assets[cudart]] if cudart in assets else [])
		return tag, want
	seen = sorted(
		n for n in (a["name"] for a in (payload[0].get("assets", []) if payload else []))
		if "bin-win" in n
	)
	raise SystemExit(f"近 30 个发布里没有 {variant} 资产；最近一个发布的可选项：{', '.join(seen)}")


def _llama_urls(tag: str, variant: str) -> tuple[str, list[str]]:
	"""不查 API 直接拼资产 URL（API 限流 / 离线场景用）。"""
	base = f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}"
	want = [
		f"{base}/llama-{tag}-bin-win-{variant}.zip",
		f"{base}/cudart-llama-bin-win-{variant}.zip",
	]
	return tag, want


def _rm(path: Path) -> None:
	"""尽力删除临时/损坏文件；删不掉不算失败。

	删除失败是常见且无害的（文件被占用、回收站不可用——本机沙箱就会把 unlink
	转到回收站并失败）。为此中断整条拉取链毫无道理：真正重要的判据是
	"llama-server 在不在、权重字节数对不对"。
	"""
	try:
		path.unlink(missing_ok=True)
	except OSError as exc:
		print(f"  [warn] 清理 {path.name} 失败（不影响结果）：{exc}")


def fetch_llama(variant: str, force: bool, tag: str | None = None) -> int:
	"""下载并解压 llama.cpp 到 ``<models_dir>/bin``。"""
	bindir = models_dir() / "bin"
	if not force:
		done = _installed(bindir, variant)
		if done is not None:
			print(f"[bin ] 已就绪 llama-server：{done}")
			return 0
	resolved, urls = _llama_urls(tag, variant) if tag else _llama_release(variant)
	print(f"[bin ] llama.cpp {resolved} · {variant} → {bindir}")
	bindir.mkdir(parents=True, exist_ok=True)
	for url in urls:
		name = url.rsplit("/", 1)[-1]
		zip_path = bindir / name
		if not _download(_gh(url), zip_path, expect=_asset_size(url)):
			return 1
		try:
			with zipfile.ZipFile(zip_path) as zf:
				zf.extractall(bindir)
		except zipfile.BadZipFile as exc:
			print(f"  [fail] {name} 不是完整 zip（{exc}）")
			_rm(zip_path)
			return 1
		_rm(zip_path)
	found = _find_server(bindir)
	print(f"[bin ] llama-server: {found or '未找到（解压层级异常）'}")
	return 0 if found else 1


def _installed(bindir: Path, variant: str) -> Path | None:
	"""已装齐则返回 llama-server 路径，否则 None（表示仍需下载）。

	CUDA 变体要额外确认 CUDA 运行时 DLL 在：官方把 ``llama-*.zip``（含 exe）与
	``cudart-*.zip``（含 cudart64_*.dll / cublas64_*.dll）拆成两份。只看 exe 在不在
	会把"只差运行时"误判成已完成，然后 llama-server 一启动就因缺 DLL 秒退。
	"""
	server = _find_server(bindir)
	if server is None:
		return None
	if variant.startswith("cuda"):
		has_cudart = any(bindir.rglob("cudart64*.dll")) or any(
			bindir.rglob("cublas64*.dll")
		)
		if not has_cudart:
			return None
	return server


def _asset_size(url: str) -> int | None:
	"""资产字节数（用于精确完成判定）；取不到返回 None（那就只按存在性判）。"""
	try:
		req = urllib.request.Request(
			url, method="HEAD", headers={"User-Agent": "xeyo-fetch-local-models"}
		)
		with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — 固定上游
			length = resp.headers.get("Content-Length")
		return int(length) if length and int(length) > 0 else None
	except Exception:  # noqa: BLE001 — 拿不到就退化为存在性判定
		return None


def _find_server(bindir: Path) -> Path | None:
	if not bindir.is_dir():
		return None
	for p in sorted(bindir.rglob("llama-server.exe")):
		return p
	return None


def main() -> int:
	ap = argparse.ArgumentParser(description="拉取本地模型运行期依赖")
	ap.add_argument("--only", choices=("gguf", "bin", "all"), default="all")
	ap.add_argument("--model", default=None, help="只拉某支模型（catalog id）")
	ap.add_argument(
		"--llama-variant",
		default="cuda-13.3-x64",
		help="llama.cpp Windows 构建变体（RTX 50 系用 CUDA 13.x）",
	)
	ap.add_argument(
		"--llama-tag",
		default=None,
		help="指定 llama.cpp 版本标签（如 b10950），跳过 GitHub API 查询",
	)
	ap.add_argument("--force", action="store_true", help="忽略已就绪判断，重新下载")
	args = ap.parse_args()

	rc = 0
	if args.only in ("gguf", "all"):
		rc |= fetch_gguf(args.model)
	if args.only in ("bin", "all"):
		try:
			rc |= fetch_llama(args.llama_variant, args.force, args.llama_tag)
		except SystemExit as exc:
			print(f"[bin ] {exc}")
			rc = 1

	root = models_dir()
	print()
	print("落盘结果：")
	for m in catalog.LOCAL_MODELS:
		path = root / m.filename
		got = path.stat().st_size if path.is_file() else 0
		state = "就绪" if got >= m.size_bytes else ("缺失" if got == 0 else "不完整")
		print(f"  {m.id:24s} {state:6s} {got / 1048576:8.1f}MB / {m.size_bytes / 1048576:.1f}MB")
	print(f"  llama-server             {'找到' if _find_server(root / 'bin') else '缺失'}")
	print()
	print("下一步：XEYO → 设置 → 模型与账号 → 本地模型 → 启用并选择模型。")
	return rc


if __name__ == "__main__":
	raise SystemExit(main())
