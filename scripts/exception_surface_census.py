"""静默失败面判别器（只读）：给 A3「宽 except 收口」提供分档依据。

对每个 `except Exception/BaseException/bare` 处理器记录：
- 模块归属（python/ 顶层包）与所在文件/行；
- 处理器体形态：`pass`（静默）/ `pass+前导注释`（有意静默）/ 只记日志 /
  return·continue·break（控制流）/ raise（重抛）/ 其他；
- 行上是否带 `# noqa: BLE001`；
- 是否在 `try` 外还有兄弟 `except`（多个处理器意味着有更窄的兜底）。

输出：控制台分档统计 + top 文件 + 静默 pass 清单（前 60）+ `reports/exception-surface-census.json`。
"""

from __future__ import annotations

import ast
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1] / "python"
SKIP_DIRS = {"tests", "scripts", "evals", "__pycache__", ".venv", "node_modules", ".pytest_cache"}

LOG_FUNCS = {"debug", "info", "warning", "warn", "error", "exception", "critical"}
LOW_LEVEL = {"debug", "info"}


def body_shape(handler: ast.ExceptHandler, lines: list[str]) -> str:
    body = handler.body
    if len(body) == 1 and isinstance(body[0], ast.Pass):
        prev = lines[handler.lineno - 2] if handler.lineno - 2 >= 0 else ""
        return "commented_pass" if prev.strip().startswith("#") else "silent_pass"
    kinds = set()
    for st in body:
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call):
            f = st.value.func
            name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if name in LOG_FUNCS:
                # 项目从不配置 logging handler ⇒ debug/info 在产线等价于静默
                # （见 project-no-logging-handler）；按级别分档。
                kinds.add("log_low" if name in LOW_LEVEL else "log_high")
        elif isinstance(st, (ast.Return, ast.Continue, ast.Break)):
            kinds.add("control")
        elif isinstance(st, ast.Raise):
            kinds.add("raise")
        elif isinstance(st, ast.Pass):
            kinds.add("pass")
    if "raise" in kinds and len(kinds) == 1:
        return "reraise"
    if "log_high" in kinds:
        return "logged_warn_plus"
    if "log_low" in kinds:
        return "logged_debug"
    if "control" in kinds:
        return "control"
    if "pass" in kinds:
        return "mixed_pass"
    return "other"


def main() -> None:
    tally: Counter = Counter()
    per_pkg: dict[str, Counter] = defaultdict(Counter)
    per_file: Counter = Counter()
    silent_sites: list[dict] = []
    parse_fail = 0

    for p in sorted(ROOT.rglob("*.py")):
        rel = p.relative_to(ROOT)
        if set(rel.parts) & SKIP_DIRS or any(x.startswith(".") for x in rel.parts[:-1]):
            continue
        pkg = rel.parts[0] if len(rel.parts) > 1 else "_root"
        try:
            src = p.read_text(encoding="utf-8-sig")
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            parse_fail += 1
            continue
        lines = src.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for h in node.handlers:
                t = h.type
                tname = ""
                if t is None:
                    tname = "bare"
                elif isinstance(t, ast.Name):
                    tname = t.id
                elif isinstance(t, ast.Attribute):
                    tname = t.attr
                elif isinstance(t, ast.Tuple):
                    tname = "+".join(
                        (e.id if isinstance(e, ast.Name) else getattr(e, "attr", "?"))
                        for e in t.elts
                    )
                if tname not in {"Exception", "BaseException", "bare"}:
                    continue
                shape = body_shape(h, lines)
                hline = lines[h.lineno - 1] if h.lineno - 1 < len(lines) else ""
                noqa = "noqa" in hline and "BLE001" in hline
                key = f"{shape}{'|noqa' if noqa else ''}"
                tally[key] += 1
                per_pkg[pkg][shape] += 1
                per_file[str(rel).replace('\\', '/')] += 1
                if shape == "silent_pass":
                    silent_sites.append(
                        {
                            "pkg": pkg,
                            "file": str(rel).replace("\\", "/"),
                            "line": h.lineno,
                            "noqa": noqa,
                            "snippet": hline.strip()[:100],
                        }
                    )

    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tally": dict(tally),
        "silent_total": tally.get("silent_pass", 0),
        "silent_sites": silent_sites,
        "top_files": per_file.most_common(20),
        "per_pkg": {k: dict(v) for k, v in sorted(per_pkg.items())},
        "parse_fail": parse_fail,
    }
    outp = ROOT.parent / "reports" / "exception-surface-census.json"
    outp.parent.mkdir(parents=True, exist_ok=True)
    with open(outp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    print(f"parse_fail={parse_fail}")
    print("== 分档 ==")
    for k, v in tally.most_common():
        print(f"  {k:20s} {v}")
    print("\n== 静默 pass 按包 ==")
    for pkg, c in sorted(per_pkg.items(), key=lambda kv: -kv[1].get("silent_pass", 0)):
        if c.get("silent_pass"):
            print(f"  {pkg:14s} silent={c['silent_pass']:4d}  commented={c.get('commented_pass', 0):3d}  logged={c.get('logged', 0):4d}")
    print("\n== top 文件（宽 except 总数）==")
    for f, n in per_file.most_common(12):
        print(f"  {n:4d}  {f}")
    print(f"\n静默 pass 清单 {len(silent_sites)} 条 → {outp}")
    for s in silent_sites[:40]:
        print(f"  [{s['pkg']}] {s['file']}:{s['line']}{'  (noqa)' if s['noqa'] else ''}")


if __name__ == "__main__":
    main()
