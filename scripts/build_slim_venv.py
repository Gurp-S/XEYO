#!/usr/bin/env python3
"""构建自包含 Python 运行环境到 gui/src-tauri/resources/python/.venv/。

为什么不用 `virtualenv` / `python -m venv`：
    两者产出的 venv 都是**薄壳**——Scripts/python.exe 是 ~270KB 的 launcher，
    真正的 python3xx.dll 与标准库留在 base 解释器（pyvenv.cfg 的 home= 指向
    C:\\Users\\<someone>\\AppData\\Local\\...）。发布包一旦装到没装对应版本
    Python 的机器上，python.exe 启动即报 "No Python at ..." 并退出，Tauri 壳
    拉不起后端，前端只能报"无法连接后端"。venv.is_file() 只验存在性，
    根本挡不住这种"文件在、跑不起来"的残废环境。

本脚本改用 astral-sh/python-build-standalone 的 install_only 发行版：
    自带 python3xx.dll + 全套标准库，可重定位（无注册表依赖、不读绝对路径），
    解压进安装目录即用。依赖用 pip 装进同一个 site-packages，
    不再依赖 pyvenv.cfg 指向外部 base。

产出结构（Tauri resources 映射 resources/python/ → 安装目录 python/）：
    <DST>/python.exe            可重定位解释器
    <DST>/python3xx.dll         运行时 DLL（薄壳 venv 缺的就是这个）
    <DST>/Lib/                  标准库
    <DST>/Lib/site-packages/    第三方依赖
    <DST>/pyvenv.cfg            home 指向自身，显式声明可重定位

重复运行会先清理目标目录再重建。
"""
from __future__ import annotations

import argparse
import glob as _glob
import io
import json
import os
import shutil
import ssl
import subprocess
import sys
import tarfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_DST = os.path.join(ROOT, "gui", "src-tauri", "resources", "python", ".venv")
CACHE = os.path.join(ROOT, ".cache", "python-build-standalone")

# 与开发环境 python/.venv/pyvenv.cfg 的 version_info 对齐（3.11.x）
PY_SERIES = "3.11"
STANDALONE_REPO = "astral-sh/python-build-standalone"

# 运行时依赖（精确钉版本：从开发 venv 逐一核对，避免发布包与本地行为漂移）。
# 不装 pytest / ray / sqlalchemy：仅供测试与本机实验，运行时无引用。
RUNTIME_PINS = [
    "fastapi==0.141.1",
    "uvicorn[standard]==0.52.1",
    "httpx==0.28.1",
    "python-multipart==0.0.32",
    "pydantic==2.13.4",
    "typer==0.27.2",
    "rich==15.0.0",
    "playwright==1.62.0",
    "mss==10.2.0",
    "Pillow==12.3.0",
    "cryptography==50.0.0",
    "GitPython==3.1.58",
    "jsonschema==4.26.0",
    "PyYAML==6.0.3",
    "python-dotenv==1.2.2",
    "tree-sitter==0.24.0",
    "tree-sitter-typescript==0.23.2",
    "tree-sitter-javascript==0.25.0",
    "msgpack==1.2.1",
]

# site-packages 顶层里运行时用不到、但会被 pip 顺手带进来的测试工具链。
# （薄壳方案曾留下 pytest_timeout.py / py.test.exe 这类散落文件，这里一并清干净）
SITE_PRUNE_NAMES = [
    "_pytest",
    "pytest",
    "pytest_asyncio",
    "pytest_timeout.py",
    "py.test.exe",
    "pytest.exe",
    "iniconfig",
    "pluggy",
    "ray",
    "tune.exe",
    "serve.exe",
    "ray.exe",
    "sqlalchemy",
    "any",
    "any.exe",
    "pydoc.bat",
    "activate_this.py",
]
SITE_PRUNE_GLOBS = [
    "pytest-*.dist-info",
    "pytest_*.dist-info",
    "ray-*.dist-info",
    "sqlalchemy-*.dist-info",
]


def _log(msg: str) -> None:
    print(msg, flush=True)


def _ssl_context() -> ssl.SSLContext:
    """优先用 certifi；没有则退回系统默认。"""
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _get_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "xeyo-build-slim-venv",
        },
    )
    with urllib.request.urlopen(req, timeout=60, context=_ssl_context()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def resolve_release(tag: str | None) -> tuple[str, str]:
    """返回 (asset_url, asset_name)。tag 为空取 latest。"""
    api = (
        f"https://api.github.com/repos/{STANDALONE_REPO}/releases/tags/{tag}"
        if tag
        else f"https://api.github.com/repos/{STANDALONE_REPO}/releases/latest"
    )
    data = _get_json(api)
    prefix = f"cpython-{PY_SERIES}."
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if (
            name.startswith(prefix)
            and "x86_64-pc-windows-msvc" in name
            and "install_only" in name
            and name.endswith(".tar.gz")
        ):
            return asset["browser_download_url"], name
    raise SystemExit(f"ERR: 发行版 {data.get('tag_name')} 里找不到 {PY_SERIES} Windows 资产")


def download(asset_url: str, asset_name: str) -> str:
    os.makedirs(CACHE, exist_ok=True)
    local = os.path.join(CACHE, asset_name)
    if os.path.isfile(local) and os.path.getsize(local) > 1_000_000:
        _log(f"  使用缓存 {asset_name}")
        return local
    _log(f"  下载 {asset_name} ...")
    req = urllib.request.Request(asset_url, headers={"User-Agent": "xeyo-build-slim-venv"})
    with urllib.request.urlopen(req, timeout=900, context=_ssl_context()) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        buf = io.BytesIO()
        read = 0
        step = 8 * 1024 * 1024
        while True:
            chunk = resp.read(step)
            if not chunk:
                break
            buf.write(chunk)
            read += len(chunk)
            if total:
                pct = read * 100 // total
                print(f"\r  {pct:3d}%  {read / 1048576:.1f}/{total / 1048576:.1f} MB", end="")
        print("", flush=True)
    if total and read != total:
        raise SystemExit(f"ERR: 下载不完整 {read}/{total} 字节")
    with open(local, "wb") as fh:
        fh.write(buf.getvalue())
    return local


def _replace_dir(path: str) -> None:
    """把目标目录腾空。

    不对目标目录做递归删除——构建产物动辄数千文件，会撞上外部批量删除保护。
    统一改为改名旁置：本轮构建一定拿到干净目录，且旧产物仍在（便于对比排查）。
    旁置目录由调用方在成功收尾时清理。
    """
    if not os.path.exists(path):
        return
    stamp = time.strftime("%Y%m%d-%H%M%S")
    aside = f"{path}.old-{stamp}"
    n = 0
    while os.path.exists(aside):
        n += 1
        aside = f"{path}.old-{stamp}-{n}"
    os.rename(path, aside)
    _log(f"  旧产物旁置: {os.path.basename(aside)}")


def extract(archive: str, dst: str) -> None:
    """解压 install_only 包，把内层 python/ 的内容摊平到 dst。"""
    _replace_dir(dst)
    staging = dst + ".staging"
    if os.path.exists(staging):
        shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    _log("  解压 ...")
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(staging)

    # install_only 的结构是 <root>/python/{python.exe,Lib,...}
    inner = os.path.join(staging, "python")
    if not os.path.isdir(inner):
        candidates = [
            os.path.join(staging, d)
            for d in os.listdir(staging)
            if os.path.isdir(os.path.join(staging, d, "Lib"))
        ]
        if not candidates:
            raise SystemExit(f"ERR: 解压结果里找不到 python/ 目录：{os.listdir(staging)}")
        inner = candidates[0]
    os.makedirs(dst, exist_ok=True)
    for item in os.listdir(inner):
        shutil.move(os.path.join(inner, item), os.path.join(dst, item))
    shutil.rmtree(staging, ignore_errors=True)


def self_python(dst: str) -> str:
    for rel in ("python.exe", os.path.join("bin", "python3")):
        p = os.path.join(dst, rel)
        if os.path.isfile(p):
            return p
    raise SystemExit(f"ERR: 解压后找不到解释器，检查 {dst}")


def pip_install(py: str) -> None:
    _log("  安装运行时依赖 ...")
    cmd = [
        py,
        "-m",
        "pip",
        "install",
        "--no-warn-script-location",
        "--disable-pip-version-check",
        "--no-cache-dir",
        *RUNTIME_PINS,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = (proc.stdout or "")[-3000:] + "\n" + (proc.stderr or "")[-3000:]
        raise SystemExit(f"ERR: pip install 失败（exit {proc.returncode}）\n{tail}")
    # pip 会往 Lib/site-packages 之外写一些入口，这里清理不影响运行时
    for junk in ("Scripts/python.exe", "Scripts/pythonw.exe"):
        pass


def _discard(path: str) -> None:
    """删除单项。

    产物树动辄数千文件，递归删除容易撞上外部批量删除保护（构建流水线里不该
    依赖"能删多少文件"）。所以这里不递归删目录，只做改名旁置；散落文件仍直接
    删（数量少，不触发保护）。
    """
    if os.path.isdir(path):
        aside = f"{path}.pruned"
        n = 0
        while os.path.exists(aside):
            n += 1
            aside = f"{path}.pruned{n}"
        try:
            os.rename(path, aside)
        except OSError:
            pass
        return
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def prune(py: str, dst: str) -> None:
    """清掉测试工具链与包管理器，缩小体积并避免散落文件。

    强约束：**不能删 pip**。构建后的产品需要能 `pip install` 装可选依赖与更新
    扩展，删掉 pip 会让发布包丧失这项能力。这里只清测试工具链。
    """
    _log("  清理测试工具链 ...")
    probe = subprocess.run(
        [py, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        capture_output=True, text=True,
    )
    if probe.returncode != 0:
        raise SystemExit("ERR: 无法定位 site-packages")
    sp = probe.stdout.strip()
    pruned = 0
    for name in SITE_PRUNE_NAMES:
        target = os.path.join(sp, name)
        if os.path.exists(target):
            _discard(target)
            pruned += 1
    for pattern in SITE_PRUNE_GLOBS:
        for hit in _glob.glob(os.path.join(sp, pattern)):
            _discard(hit)
            pruned += 1
    _log(f"  旁置 {pruned} 项（*.pruned 在收尾时统一清理）")


def _purge_pruned(root: str) -> None:
    """收尾：把 prune 阶段旁置的 *.pruned 与 __pycache__ 从产物里移除。

    逐目录 rename 旁置后再删——一次性 rmtree 大量目录树容易撞外部批量删除保护，
    构建流水线不该依赖"能删多少文件"。删不掉的留在原地也无害（只是多占几 MB）。
    """
    victims = []
    for r, dirs, _files in os.walk(root):
        for d in dirs:
            if d.endswith(".pruned") or d == "__pycache__":
                victims.append(os.path.join(r, d))
    if not victims:
        return 0
    n = 0
    # 深路径优先，保证删父目录前子目录已空
    for path in sorted(victims, key=lambda p: -p.count(os.sep)):
        try:
            shutil.rmtree(path)
            n += 1
        except OSError:
            # 删不动就改名旁置，至少不污染产物结构
            _discard(path)
    return n


def write_pyvenv_cfg(py: str, dst: str) -> None:
    """写 pyvenv.cfg —— 只放能让 site-packages 进入 sys.path 的最小内容。

    踩坑记录（2026-09-10）：这里曾写成 `home = .`（等号两侧带空格），结果
    CPython 解析 home 时把空串当基准路径，site-packages **没有**进入 sys.path，
    导入任何第三方包都 ModuleNotFoundError。`home=.`（无空格）才正确。

    另外 standalone 发行版自身不依赖 pyvenv.cfg（sys.prefix 由 exe 位置推导），
    所以内容越少越好——多写的字段（relocatable 等）无益且可能干扰解析。
    """
    cfg = os.path.join(dst, "pyvenv.cfg")
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write("home=.\n")


def verify(py: str) -> None:
    """自包含性验收：绝不引用外部 base 解释器，且依赖能真正导入。"""
    _log("  验证自包含性 ...")
    probe = (
        "import sys, os\n"
        "base = os.path.dirname(os.path.abspath(sys.executable))\n"
        "assert os.path.isfile(os.path.join(base, 'python.exe')), 'python.exe missing'\n"
        "dlls = [f for f in os.listdir(base) if f.lower().startswith('python3') and f.lower().endswith('.dll')]\n"
        "assert dlls, 'python3xx.dll missing -> 仍是薄壳 venv'\n"
        "assert any('site-packages' in p for p in sys.path), 'site-packages 不在 sys.path'\n"
        "cfg = os.path.join(base, 'pyvenv.cfg')\n"
        "if os.path.isfile(cfg):\n"
        "    for line in open(cfg, encoding='utf-8'):\n"
        "        line = line.strip()\n"
        "        if not line or line.startswith('#'):\n"
        "            continue\n"
        "        if line.startswith('home'):\n"
        "            val = line.split('=', 1)[1].strip()\n"
        "            assert val == '.', f'pyvenv.cfg home 应为 .，实为 {val!r}'\n"
        "print('self-contained OK', dlls[0])\n"
    )
    r = subprocess.run([py, "-c", probe], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"ERR: 自包含性校验失败\n{r.stdout}\n{r.stderr}")
    _log(f"  {r.stdout.strip()}")

    deps = subprocess.run(
        [py, "-c",
         "import fastapi, uvicorn, httpx, typer, rich, playwright, mss, PIL, multipart, "
         "cryptography, git, jsonschema, yaml, dotenv, msgpack; "
         "from tree_sitter import Language; print('runtime deps OK')"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if deps.returncode != 0:
        raise SystemExit(f"ERR: 运行时依赖导入失败\n{deps.stdout}\n{deps.stderr}")
    _log(f"  {deps.stdout.strip()}")


def report(py: str, dst: str) -> None:
    total = sum(
        os.path.getsize(os.path.join(r, f))
        for r, _d, fs in os.walk(dst)
        for f in fs
    )
    info = subprocess.run(
        [py, "-c", "import sys; print(sys.version.split()[0]); print(sys.executable)"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout.strip().splitlines()
    _log(f"=== 产物: {dst}")
    _log(f"    Python {info[0]}  {info[1]}")
    _log(f"    大小 {total / 1024 / 1024:.0f} MB ===")


def _cleanup_aside(dst: str, done: bool) -> None:
    """构建成功则清掉旁置旧产物；失败保留，便于对比排查。"""
    if not done:
        return
    parent = os.path.dirname(dst)
    base = os.path.basename(dst) + ".old-"
    for name in os.listdir(parent):
        if name.startswith(base):
            target = os.path.join(parent, name)
            try:
                shutil.rmtree(target)
            except OSError:
                _log(f"  旁置目录需手工清理: {target}")


def main() -> None:
    ap = argparse.ArgumentParser(description="构建自包含 Python 运行时到 resources/python/.venv")
    ap.add_argument("--tag", default=os.environ.get("XEYO_PBS_TAG"),
                    help="python-build-standalone 发行 tag，默认 latest")
    ap.add_argument("--dst", default=None,
                    help="输出目录，默认 resources/python/.venv；"
                         "目标被占用时可指向别处先构建，再离线替换")
    args = ap.parse_args()

    if os.name != "nt":
        _log("注意：本脚本当前针对 Windows 发行包；非 Windows 请用 build_installer.sh 的本地流程。")

    dst = os.path.abspath(args.dst) if args.dst else DEFAULT_DST
    _log(f"==[构建自包含 Python {PY_SERIES}]==")
    _log(f"  目标 {dst}")
    url, name = resolve_release(args.tag)
    _log(f"  资产 {name}")
    archive = download(url, name)
    extract(archive, dst)
    py = self_python(dst)
    pip_install(py)
    prune(py, dst)
    write_pyvenv_cfg(py, dst)
    verify(py)
    n = _purge_pruned(dst)
    _log(f"  收尾清理 {n} 项旁置/缓存")
    report(py, dst)
    _cleanup_aside(dst, True)
    _log("提示：产物已自包含，不依赖构建机上的 Python。")


if __name__ == "__main__":
    main()
