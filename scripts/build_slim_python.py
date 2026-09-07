#!/usr/bin/env python3
"""精简 Python 代码到 gui/src-tauri/resources/python/。

复制运行时必需目录（server/engine/cli/tools/prompt/slash/permissions/
session/msgtypes/memory(部分)/channels/rewind/audit/codeindex/common/
model/extension/usage），去除 evals/bridge/scripts/tests/_shadow 与
__pycache__/*.pyc/out/simulator/out 等。

重复运行会先清理目标目录再复制。
"""
import os
import shutil
import sys

SRC = os.path.join(os.path.dirname(__file__), "..", "python")
DST = os.path.join(os.path.dirname(__file__), "..", "gui", "src-tauri", "resources", "python")

KEEP_TOP = {
    "server", "engine", "cli", "tools", "prompt", "slash", "permissions",
    "session", "msgtypes", "model", "channels", "rewind", "audit",
    "codeindex", "common", "extension", "usage",
}
# memory 单独处理：保留运行时引用的子模块，去 simulator/out
CUT_TOP = {"evals", "bridge", "scripts", "tests"}
MEMORY_KEEP_SUB = {
    "__init__.py", "instruction.py", "l.py", "l", "runtime.py", "token.py",
    "working.py", "governance.py", "agent_scope.py", "cache_profile.py",
    "citation.py", "failure_note.py", "fidelity_segmenter.py",
    "memory_switches.py", "notebook.py",
}
MEMORY_DROP_SUB = {"simulator", "simulator.py", "shadow*.py", "out"}


def main():
    if os.path.exists(DST):
        shutil.rmtree(DST)
    os.makedirs(DST, exist_ok=True)
    for item in sorted(os.listdir(SRC)):
        sp = os.path.join(SRC, item)
        if not os.path.isdir(sp):
            continue
        if item in CUT_TOP:
            print(f"  SKIP {item}")
            continue
        if item == "memory":
            dp = os.path.join(DST, "memory")
            os.makedirs(dp, exist_ok=True)
            for sub in sorted(os.listdir(sp)):
                if sub.startswith(".") or sub in MEMORY_DROP_SUB or sub.endswith("shadow.py"):
                    continue
                sp2 = os.path.join(sp, sub)
                dp2 = os.path.join(dp, sub)
                if os.path.isdir(sp2):
                    shutil.copytree(
                        sp2, dp2,
                        ignore=shutil.ignore_patterns(
                            "__pycache__", "*.pyc", "out", "shadow_*.py",
                        ),
                    )
                else:
                    shutil.copy2(sp2, dp2)
            print(f"  COPY memory/ (精选子模块)")
            continue
        if item in KEEP_TOP:
            dp = os.path.join(DST, item)
            shutil.copytree(
                sp, dp,
                ignore=shutil.ignore_patterns(
                    "__pycache__", "*.pyc", "*.shadow.py",
                    "out", "shadow_*.py", "_shadow*", "tests",
                ),
            )
            print(f"  COPY {item}")
    print(f"=== 精简完成: {DST} ===")


if __name__ == "__main__":
    main()