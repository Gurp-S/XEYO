"""架构耦合清点器（只读，可复跑）。

口径：
- 节点 = `python/` 下顶层代码目录（engine/server/memory/... 与根文件桶 `_root`）；
- 边 = 生产文件里的绝对 import（`import X...` / `from X... import ...`），
  按 (from_pkg, to_pkg) 去重计数；相对 import 单列不建边；
- 排除 tests/scripts/evals/__pycache__/.venv 等非生产面；
- SCC = 包级有向图强连通分量（Tarjan，忽略自环）；"巨石" = 物理行数 top。
输出：控制台摘要 + `reports/arch-coupling-census.json`。
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
SKIP_DIRS = {
    "tests", "scripts", "evals", "__pycache__", ".venv", "node_modules",
    ".pytest_cache", "_wsc_out", ".xeyo_offload",
}


def pkg_of(rel: Path) -> str:
    return rel.parts[0] if len(rel.parts) > 1 else "_root"


def collect_files() -> list[Path]:
    out = []
    for p in sorted(ROOT.rglob("*.py")):
        rel = p.relative_to(ROOT)
        if set(rel.parts) & SKIP_DIRS:
            continue
        # 点前缀目录 = 临时/缓存/夹具污染（.pytest_tmp*/.tmp*/.xeyo* 等），一律不算生产面
        if any(part.startswith(".") for part in rel.parts[:-1]):
            continue
        out.append(p)
    return out


def main() -> None:
    files = collect_files()
    nodes: set[str] = set()
    loc: dict[str, int] = defaultdict(int)
    file_locs: list[tuple[int, str]] = []
    edges: dict[tuple[str, str], set[str]] = defaultdict(set)
    relative = 0
    parse_fail: list[str] = []

    for p in files:
        rel = p.relative_to(ROOT)
        src_pkg = pkg_of(rel)
        nodes.add(src_pkg)
        try:
            src = p.read_text(encoding="utf-8-sig")
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            parse_fail.append(str(rel))
            continue
        n = len(src.splitlines())
        loc[src_pkg] += n
        file_locs.append((n, str(rel).replace("\\", "/")))

        for node in ast.walk(tree):
            mod = ""
            if isinstance(node, ast.Import):
                for a in node.names:
                    mod = a.name.split(".")[0]
                    if mod:
                        nodes.add(mod)
                        if mod != src_pkg:
                            edges[(src_pkg, mod)].add(str(rel))
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    relative += 1
                    continue
                if node.module:
                    mod = node.module.split(".")[0]
                    nodes.add(mod)
                    if mod != src_pkg:
                        edges[(src_pkg, mod)].add(str(rel))

    # 仅保留"真实存在的包"为节点（外部库名不构成图节点）
    real = {pkg_of(p.relative_to(ROOT)) for p in files}
    edges = {k: v for k, v in edges.items() if k[0] in real and k[1] in real}
    nodes = real

    adj: dict[str, set[str]] = {n: set() for n in nodes}
    for (a, b) in edges:
        adj[a].add(b)

    # Tarjan SCC
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    onstack: set[str] = set()
    stack: list[str] = []
    sccs: list[list[str]] = []
    counter = [0]

    def strong(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        onstack.add(v)
        for w in adj.get(v, ()):
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in onstack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                onstack.discard(w)
                comp.append(w)
                if w == v:
                    break
            sccs.append(sorted(comp))

    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(10000)
    for v in sorted(nodes):
        if v not in index:
            strong(v)
    sys.setrecursionlimit(old_limit)

    multi = [c for c in sccs if len(c) > 1]
    in_deg = Counter(b for _, b in edges)
    out_deg = Counter(a for a, _ in edges)
    heavy = sorted(edges.items(), key=lambda kv: -len(kv[1]))[:15]

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "files": len(files),
        "packages": sorted(nodes),
        "package_edges": len(edges),
        "scc_multi": multi,
        "scc_multi_count": len(multi),
        "relative_imports": relative,
        "parse_fail": parse_fail,
        "loc_by_package": dict(sorted(loc.items(), key=lambda kv: -kv[1])),
        "top_files": [{"loc": n, "path": s} for n, s in sorted(file_locs, reverse=True)[:25]],
        "in_degree": in_deg.most_common(12),
        "out_degree": out_deg.most_common(12),
        "heavy_edges": [
            {"from": a, "to": b, "files": len(v)} for (a, b), v in heavy
        ],
    }
    out_path = ROOT.parent / "reports" / "arch-coupling-census.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)

    print(f"files={len(files)} packages={len(nodes)} package_edges={len(edges)} "
          f"relative_imports={relative} parse_fail={len(parse_fail)}")
    print(f"SCC>1: {len(multi)} 个 -> {multi}")
    print("\n== LOC top 包 ==")
    for k, v in list(summary["loc_by_package"].items())[:12]:
        print(f"  {k:14s} {v:>7} 行")
    print("\n== 巨石 top15 ==")
    for row in summary["top_files"][:15]:
        print(f"  {row['loc']:>6}  {row['path']}")
    print("\n== 入度 top（谁最被依赖）==")
    for k, v in summary["in_degree"]:
        print(f"  {k:14s} <- {v} 个包")
    print("\n== 重边 top10（包 A 引包 B 的文件数）==")
    for row in summary["heavy_edges"][:10]:
        print(f"  {row['from']:12s} -> {row['to']:12s} {row['files']} files")
    print(f"\nJSON → {out_path}")


if __name__ == "__main__":
    main()
