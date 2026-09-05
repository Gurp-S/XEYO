"""冒烟 Runner：发现 scenarios/ 下每个模块并执行，产出 report.md。

用法：
    python scripts/smoke_p0p1/run.py --task t9      # 跑单个
    python scripts/smoke_p0p1/run.py --all          # 全量
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from scripts.smoke_p0p1.harness import Harness  # noqa: E402

SCENARIOS_DIR = pathlib.Path(__file__).resolve().parent / "scenarios"


def _load_scenario(path: pathlib.Path) -> tuple[str, Any]:
    name = path.stem
    spec = importlib.util.spec_from_file_location(f"smoke_scen_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return name, mod


def _discover() -> list[tuple[str, Any]]:
    return [_load_scenario(p) for p in sorted(SCENARIOS_DIR.glob("*.py")) if p.stem != "__init__"]


def _report(task: str, checks: list[tuple[str, bool, str]]) -> None:
    passed = sum(1 for _, ok, _ in checks if ok)
    status = "PASS" if passed == len(checks) and checks else "FAIL"
    print(f"\n== {task}: {status} ({passed}/{len(checks)}) ==")
    for name, ok, detail in checks:
        mark = "OK " if ok else "FAIL"
        print(f"  [{mark}] {name}: {detail}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default=None)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    all_lines: list[str] = []
    for name, mod in _discover():
        if args.task and name != args.task:
            continue
        if not getattr(mod, "RUN", True):  # 支持场景自声明跳过
            print(f"\n== {name}: SKIP ==")
            continue
        responses = (getattr(mod, "responses", None)
                     or getattr(mod, "RESPONSES", None))
        if responses is None:
            print(f"\n== {name}: no responses, skip ==")
            continue
        h = Harness(name, responses)
        try:
            h.up()
            checks = mod.run(h)
        except Exception as e:  # noqa: BLE001
            checks = [("run-error", False, repr(e))]
        finally:
            h.down()
        _report(name, checks)
        for n, ok, d in checks:
            all_lines.append(f"- {name}: {n} -> {'PASS' if ok else 'FAIL'} ({d})")

    report_path = pathlib.Path(__file__).resolve().parent / "report.md"
    report_path.write_text("# P0/P1 端到端冒烟报告\n\n" + "\n".join(all_lines) + "\n",
                           encoding="utf-8")
    print(f"\nreport written: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
