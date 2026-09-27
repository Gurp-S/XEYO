"""把 ``<repo>/python`` 同步进 Tauri 的打包资源快照 ``gui/src-tauri/resources/python``。

结构性根因（2026-09-27 查清）：release 后端跑的是这个快照，而快照由人**手工**刷新。
于是"新增一个顶层包"没有任何机制会把它带进产物 —— 实测仓库有 24 个可导入的顶层包，
过期快照里只有 18 个：``diagnostics``（诊断中心整个层）、``bridge``、``coord``、
``localmodels``、``synaptic`` 全部静默缺失。#80 只是其中被发现的那个。

所以这里的规则不是"记住要拷哪些目录"，而是**默认全拷**：白名单由"仓库里带
``__init__.py`` 的顶层目录"推导出来，新包自动纳入；不想进产物的必须在这里显式列
``NOT_SHIPPED`` 并写明理由。方向反过来才不会漏 —— 多拷一个小包只花体积，
少拷一个包会让发布版静默少一整个功能。

三道护栏：
1. 绝不整目录复制：``python/`` 下有开发残渣与本机数据（实测 ``.xy-shadow-git`` 202 MB、
   ``tests`` 54 MB、``.xeyo_filehelper`` 52 MB、``.cgraph_v7`` 32 MB、``.tmp_audit_a`` 4.2 MB），
   整拷会把它们烤进分发产物。只拷顶层包目录，跳过任何点开头与顶层散文件。
2. 快照自带的 venv 是**带外产出的厚壳**（``lib.rs:288`` 记着"薄壳 venv 装完 MSI 连不上后端"），
   仓库里没有生成脚本 —— 所以这里永远搬动它、不重建它，旧快照整体重命名留作回滚点。
3. 拷完必须用**快照自己的解释器**验证：可启动 + 关键路由在位。验不过就还原，
   绝不留"看起来同步成功了"的中间态。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "python"
SNAPSHOT = REPO_ROOT / "gui" / "src-tauri" / "resources" / "python"

#: 明确不进产物的顶层包 —— 必须写理由，空集合是默认且正确的状态。
NOT_SHIPPED: dict[str, str] = {}

#: 同步后必须能在产物里解析出来的路由前缀。少一个就是功能在发布版里不存在。
REQUIRED_ROUTE_PREFIXES = ("/v1/diagnostics/", "/health")

#: 校验时顺带确认存在的模块属性：钉住"这层代码真的进来了"，不是只钉目录名。
REQUIRED_SYMBOLS = (
	("diagnostics.collect", "list_ledger_sessions"),
	("diagnostics.rules", "RULES"),
)


def discover_packages(src: Path = SRC) -> list[str]:
	"""仓库里可被 ``import`` 的顶层包名。

	判据是"目录里有 ``__init__.py``"，不是名字白名单：这样新增包会自动进入产物，
	而 ``tests`` / ``scripts``（无 ``__init__.py``）与任何点开头的目录自动排除。
	"""
	out: list[str] = []
	for child in sorted(src.iterdir()):
		if not child.is_dir() or child.name.startswith("."):
			continue
		if (child / "__init__.py").is_file():
			out.append(child.name)
	return out


@dataclass
class Plan:
	copy: list[str] = field(default_factory=list)
	already_there: list[str] = field(default_factory=list)
	dropped: list[str] = field(default_factory=list)  # 快照里有、源码里没有的包
	skipped: list[str] = field(default_factory=list)  # NOT_SHIPPED 命中
	has_venv: bool = False


def plan(src: Path = SRC, dst: Path = SNAPSHOT) -> Plan:
	"""算出这次要拷哪些包，以及快照会被删掉什么（只报，不删）。"""
	p = Plan()
	pkgs = discover_packages(src)
	for name in pkgs:
		if name in NOT_SHIPPED:
			p.skipped.append(name)
		elif (dst / name).is_dir():
			p.already_there.append(name)
		else:
			p.copy.append(name)
	if dst.is_dir():
		present = {c.name for c in dst.iterdir() if c.is_dir() and not c.name.startswith(".")}
		p.dropped = sorted(present - set(pkgs) - {"Scripts", "bin", "Lib", "include", "libs", "DLLs"})
		p.has_venv = (dst / ".venv").is_dir()
	return p


def dirty_report() -> list[str]:
	"""产物会带上哪些"未提交"的源码 —— 让操作者知道自己打包的是工作树还是版本。"""
	try:
		r = subprocess.run(
			["git", "status", "--porcelain", "--", "python"],
			cwd=str(REPO_ROOT),
			capture_output=True,
			text=True,
			shell=True,
			encoding="utf-8",
			errors="replace",
		)
	except OSError:
		return []
	return [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]


def _copy_package(src_dir: Path, dst_dir: Path) -> int:
	"""按目录复制，跳过 __pycache__ 与 .pyc。返回复制的文件数。"""
	n = 0
	dst_dir.mkdir(parents=True, exist_ok=True)
	for root, dirs, files in os.walk(src_dir):
		dirs[:] = [d for d in dirs if d != "__pycache__"]
		rel = Path(root).relative_to(src_dir)
		for f in files:
			if f.endswith((".pyc", ".pyo")):
				continue
			target = dst_dir / rel / f
			target.parent.mkdir(parents=True, exist_ok=True)
			shutil.copy2(Path(root) / f, target)
			n += 1
	return n


#: 用 `-c` 执行，前缀从 argv 传入 —— 不把代码拼成字符串（今天就是这样写漏一个括号，
#: 症状是"产物 import 失败"，其实失败的是校验器自己）。
_VERIFY_SCRIPT = """
import json, sys
sys.path.insert(0, '.')
import server.app as m
paths = sorted(m.app.openapi()['paths'])
missing = [p for p in sys.argv[1:] if not any(q.startswith(p) for q in paths)]
print(json.dumps({'paths': len(paths), 'missing': missing}))
"""


def verify(snapshot: Path = SNAPSHOT, *, prefixes=REQUIRED_ROUTE_PREFIXES, symbols=REQUIRED_SYMBOLS) -> list[str]:
	"""用快照**自带**的解释器验证产物。返回问题清单，空 = 通过。"""
	problems: list[str] = []
	py = snapshot_python(snapshot)
	if py is None:
		return [f"快照里没有可用的解释器（.venv 缺失或只是薄壳）：{snapshot}"]
	r = subprocess.run([str(py), "-c", _VERIFY_SCRIPT, *prefixes], cwd=str(snapshot),
	                   capture_output=True, text=True, encoding="utf-8", errors="replace")
	if r.returncode != 0:
		problems.append(f"产物里的后端 import 失败：{(r.stderr or '').strip()[-300:]}")
		return problems
	try:
		info = json.loads((r.stdout or "").strip().splitlines()[-1])
	except (ValueError, IndexError):
		problems.append(f"校验输出无法解析：{(r.stdout or '')[:200]}")
		return problems
	for p in info.get("missing", []):
		problems.append(f"发布产物里没有路由前缀 {p}")
	for mod, attr in symbols:
		chk = subprocess.run(
			[str(py), "-c", f"import sys;sys.path.insert(0,'.');import {mod} as x;raise SystemExit(0 if hasattr(x,{attr!r}) else 1)"],
			cwd=str(snapshot), capture_output=True, text=True, encoding="utf-8", errors="replace")
		if chk.returncode != 0:
			problems.append(f"{mod}.{attr} 在产物里取不到")
	return problems


def snapshot_python(snapshot: Path = SNAPSHOT) -> Path | None:
	"""找出快照自带的解释器，并确认它真的能跑（厚壳 venv 判据同 lib.rs::python_exe_usable）。"""
	for cand in (snapshot / ".venv" / "python.exe", snapshot / ".venv" / "bin" / "python",
	            snapshot / ".venv" / "Scripts" / "python.exe"):
		if cand.is_file():
			try:
				r = subprocess.run([str(cand), "-c", "import sys;sys.stdout.write(str(sys.version_info[0]))"],
				                   capture_output=True, text=True, timeout=60)
			except (OSError, subprocess.TimeoutExpired):
				continue
			if r.returncode == 0 and r.stdout.strip():
				return cand
	return None


def sync(*, dry_run: bool = False, allow_dirty: bool = False, src: Path = SRC, dst: Path = SNAPSHOT) -> int:
	dirty = dirty_report()
	if dirty and not allow_dirty:
		print("python/ 有未提交改动，产物会把它们一起带上（要接受请加 --allow-dirty）：")
		for ln in dirty[:20]:
			print("  ", ln)
		return 2
	p = plan(src, dst)
	if not p.has_venv:
		print(f"快照里没有 .venv：{dst}。拒绝继续 —— 依赖是带外产出的，这里不猜。")
		return 2
	print("将同步：", " ".join(p.copy) or "（没有缺失的包，只做覆盖刷新）")
	if p.dropped:
		print("快照里多出（本工具不删，只提示）：", " ".join(p.dropped))
	if p.skipped:
		print("显式排除：", " ".join(f"{k}(理由:{NOT_SHIPPED[k]})" for k in p.skipped))
	if dry_run:
		print("dry-run：未改动任何文件。")
		return 0

	rollback = dst.parent / f"{dst.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
	dst.rename(rollback)
	print("回滚点：", rollback)
	try:
		dst.mkdir(parents=True)
		moved = False
		for name in discover_packages(src):
			n = _copy_package(src / name, dst / name)
			print(f"  {name}: {n} 文件")
		shutil.move(str(rollback / ".venv"), str(dst / ".venv"))
		moved = True
		problems = verify(dst)
		if problems:
			for x in problems:
				print("校验失败：", x)
			if moved:
				shutil.move(str(dst / ".venv"), str(rollback / ".venv"))
			shutil.rmtree(dst, ignore_errors=True)
			rollback.rename(dst)
			print("已还原到回滚点。")
			return 1
		print("同步完成并通过校验。")
		return 0
	except BaseException:
		if dst.is_dir() and not (dst / "server").is_dir():
			shutil.rmtree(dst, ignore_errors=True)
		if rollback.is_dir() and not dst.exists():
			rollback.rename(dst)
		raise


def main(argv: list[str] | None = None) -> int:
	ap = argparse.ArgumentParser(description="同步 Tauri 的 python 打包快照")
	ap.add_argument("--dry-run", action="store_true", help="只报告要拷什么，不改文件")
	ap.add_argument("--allow-dirty", action="store_true", help="接受把未提交改动烤进产物")
	args = ap.parse_args(argv)
	return sync(dry_run=args.dry_run, allow_dirty=args.allow_dirty)


if __name__ == "__main__":
	raise SystemExit(main())
