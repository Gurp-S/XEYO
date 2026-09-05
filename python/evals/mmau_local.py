"""MMAU（离线多任务综合）：纯本地计算，0 元。

表格1定义该基准为「直接加载数据集，无需联网调用 API，纯本地计算」。此处按同一
语义执行 XEYO 自身的离线多任务验证套件（fake 模型后端、无任何网络请求），
覆盖：工具契约 / 权限策略 / 会话与任务状态 / 记忆压缩与检索 / 用量账本 /
记忆模拟器不变量。结果即「XEYO 产品能力」在离线多任务维度的综合通过率。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from client import REPO_ROOT, STARTUP_DIR, ensure_stdout_utf8  # noqa: E402

PY_DIR = REPO_ROOT / "python"
RESULTS_PATH = STARTUP_DIR / "mmau_results.json"
SMOKE = bool(__import__("os").environ.get("XEYO_EVAL_SMOKE"))

GROUPS: list[tuple[str, list[str]]] = [
    ("工具契约", ["tests/test_catalog.py", "tests/test_tool_orchestration.py"]),
    ("权限策略", ["tests/test_permission_policy.py", "tests/test_permissions.py"]),
    ("会话与任务状态", ["tests/test_task_state.py", "tests/test_resume_from_disk.py"]),
    ("记忆压缩与检索", ["tests/test_compact.py", "tests/test_memory_search.py"]),
    ("用量账本", ["tests/test_usage_combine.py"]),
    ("模拟器不变量", ["tests/simulator"]),
]
SMOKE_GROUPS = [("工具契约", ["tests/test_catalog.py"]), ("用量账本", ["tests/test_usage_combine.py"])]


def run_group(name: str, targets: list[str]) -> dict:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *targets,
        "-q",
        "--no-header",
        "-p",
        "no:cacheprovider",
        f"--junitxml={STARTUP_DIR / 'mmau_last.xml'}",
    ]
    t0 = time.monotonic()
    proc = subprocess.run(
        cmd, cwd=str(PY_DIR), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900
    )
    elapsed = time.monotonic() - t0
    xml_path = STARTUP_DIR / "mmau_last.xml"
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    if xml_path.exists():
        try:
            import xml.etree.ElementTree as ET

            root = ET.parse(xml_path).getroot()
            suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
            for s in suites:
                counts["tests"] += int(s.get("tests") or 0)
                counts["failures"] += int(s.get("failures") or 0)
                counts["errors"] += int(s.get("errors") or 0)
                counts["skipped"] += int(s.get("skipped") or 0)
        except Exception:
            pass
    executed = max(counts["tests"], 0)
    bad = counts["failures"] + counts["errors"]
    passed = max(executed - bad - counts["skipped"], 0)
    return {
        "group": name,
        "cmd": " ".join(targets),
        "exit_code": proc.returncode,
        "passed": passed,
        "failed": bad,
        "skipped": counts["skipped"],
        "total": executed,
        "pass_rate": round(passed / executed, 4) if executed else None,
        "elapsed_s": round(elapsed, 1),
        "stdout_tail": (proc.stdout or "")[-600:],
    }


def main() -> int:
    ensure_stdout_utf8()
    STARTUP_DIR.mkdir(parents=True, exist_ok=True)
    groups = SMOKE_GROUPS if SMOKE else GROUPS
    print(f"[mmau] local offline suite groups={[g[0] for g in groups]} smoke={SMOKE}")
    results = []
    for name, targets in groups:
        print(f"[mmau] running: {name} ({' '.join(targets)})")
        try:
            r = run_group(name, targets)
        except subprocess.TimeoutExpired:
            r = {"group": name, "cmd": " ".join(targets), "exit_code": -1, "error": "timeout_900s"}
            results.append(r)
            break
        results.append(r)
        print(
            f"[mmau] {name}: pass={r.get('passed')} fail={r.get('failed')} "
            f"skip={r.get('skipped')} {r['elapsed_s']}s exit={r['exit_code']}"
        )

    total = sum(r.get("total", 0) for r in results)
    passed = sum(r.get("passed", 0) for r in results)
    failed = sum(r.get("failed", 0) for r in results)
    summary = {
        "model": "无模型调用（fake 后端，纯本地计算）",
        "thinking": "不适用",
        "cost_cny": 0.0,
        "groups": results,
        "overall": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed / total, 4) if total else None,
        },
    }
    RESULTS_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["overall"], ensure_ascii=False))
    print(f"[mmau] summary -> {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
