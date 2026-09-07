#!/usr/bin/env python3
"""复制并精简 .venv 到 gui/src-tauri/resources/python/.venv/。

策略：
- 复制整个 .venv（去 __pycache__/.pyc/.pyd/share/doc 等）
- 删 ray / sqlalchemy / pytest / playwright 等大包或运行时不用
- 补拷被 ignore 模式误伤的 .pyd 文件（Rust 编译扩展）

要求源 .venv 在 python/.venv/（项目 dev venv）。
"""
import os
import shutil
import subprocess
import sys

SRC = os.path.join(os.path.dirname(__file__), "..", "python", ".venv")
DST = os.path.join(
    os.path.dirname(__file__),
    "..", "gui", "src-tauri", "resources", "python", ".venv",
)

CUT_PACKAGES = [
    "ray",       # 118M，运行时无引用（确认 grep）
    "sqlalchemy",  # 19M，运行时无引用
    "pytest", "pytest_asyncio", "pytest_timeout", "pluggy", "iniconfig",
    # playwright 保留：channels/filehelper/bridge.py 运行时用 sync_playwright
]


def main():
    if not os.path.isdir(SRC):
        print(f"ERR: 源 venv 不存在 {SRC}", file=sys.stderr)
        sys.exit(1)
    if os.path.exists(DST):
        shutil.rmtree(DST)
    print("复制 .venv → resources/python/.venv (含 .pyd) ...")
    shutil.copytree(
        SRC, DST,
        ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", "*.pyo",
            "share/doc", "share/man", "share/info",
            "pip/_vendor",
            "pip/_internal/__pycache__",
        ),
    )
    sp = os.path.join(DST, "Lib" if os.name == "nt" else "lib", "site-packages")
    print("裁剪大包...")
    for pkg in CUT_PACKAGES:
        p = os.path.join(sp, pkg)
        if os.path.isdir(p):
            sz = sum(
                os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(p) for f in fs
            )
            shutil.rmtree(p, ignore_errors=True)
            print(f"  - {pkg} (-{sz/1024/1024:.0f}M)")
    print("补拷 .pyd 文件（Rust 编译扩展，未被 ignore 误伤）...")
    src_sp = os.path.join(SRC, "Lib" if os.name == "nt" else "lib", "site-packages")
    n = 0
    for r, _, fs in os.walk(src_sp):
        for f in fs:
            if f.endswith(".pyd"):
                rel = os.path.relpath(os.path.join(r, f), src_sp)
                dst_p = os.path.join(sp, rel)
                if not os.path.exists(dst_p):
                    os.makedirs(os.path.dirname(dst_p), exist_ok=True)
                    shutil.copy2(os.path.join(r, f), dst_p)
                    n += 1
    print(f"  补拷 {n} 个 .pyd")
    total = sum(
        os.path.getsize(os.path.join(r, f))
        for r, _, fs in os.walk(DST) for f in fs
    )
    print(f"=== 精简后 .venv 大小: {total/1024/1024:.0f}M ===")


if __name__ == "__main__":
    main()