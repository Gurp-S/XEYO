"""面试知识书自检脚本：引用准确率 + 文件级覆盖率。

用法（仓库根下）：
    python docs/面试知识书/_audit_citations.py

输出两节：
  【1】引用核验 —— 抽取全书所有 `文件:行号` 引用，解析到真实文件，判定
        (a) 文件存在 (b) 行号在界内 (c) 书里写的符号是否出现在引用行附近。
  【2】覆盖率   —— 统计各目录「文件名在书中一次都没出现」的源文件数（排除测试）。

设计取舍：
  * 只做**启发式**判定。它能发现「行号越界 / 符号错位」，**发现不了「语义讲反」**。
    语义级错误必须人工回源码逐行读（例：XEYO_L5 的双权威，见 00-README 第四轮 §4）。
  * 裸文件名引用在书里合法（上下文可判），但本脚本无法唯一解析时会挑一个候选，
    因此 OOB 列表中可能出现 `[ambig]` 误报，需人工看一眼。
"""

import collections
import glob
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOOK = os.path.join(ROOT, "docs", "面试知识书")

EXT_SET = (".py", ".ts", ".tsx", ".rs", ".json", ".ps1", ".toml")
SKIP_DIR_NAMES = {"node_modules", ".venv", "target", "__pycache__", "dist", "build",
                  ".pytest_cache", ".git", "out"}
SCAN_ROOTS = ("python", "gui/src", "gui/src-tauri/src", "tui/src", "scripts",
              "tui", "gui/src-tauri")


def _skip(dirname):
    return dirname in SKIP_DIR_NAMES or dirname.startswith((".pytest_tmp", ".tmp-", ".xeyo_test_tmp", ".pytmp"))


def _walk(base):
    """产出 base 下所有源文件（仓库相对路径，正斜杠）。"""
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, base.replace("/", os.sep))):
        dirnames[:] = [d for d in dirnames if not _skip(d)]
        if "eval_sandbox" in dirpath.replace("\\", "/"):
            continue
        for fn in filenames:
            yield os.path.join(dirpath, fn).replace(ROOT + os.sep, "").replace("\\", "/")


def _is_test(rel):
    r = rel.lower()
    return ("/tests/" in r or r.startswith("python/tests") or ".test." in r
            or ".spec." in r or "/e2e/" in r or "/__tests__/" in r)


def build_index():
    idx = collections.defaultdict(list)
    for base in SCAN_ROOTS:
        for rel in _walk(base):
            if rel.endswith(EXT_SET):
                idx[os.path.basename(rel)].append(os.path.join(ROOT, rel.replace("/", os.sep)))
    return idx


def read_text(path):
    return io.open(path, encoding="utf-8", errors="ignore").read()


EXT_RE = r"(?:py|ts|tsx|rs|json|ps1|toml|jsonl)"
CITE = re.compile(r"`([A-Za-z0-9_\-./\\]+\.%s):([0-9][0-9/\-]*)" % EXT_RE + r"`")
IDENT = re.compile(r"`([A-Za-z_][A-Za-z0-9_]{2,})`")
STOP = {"python", "true", "false", "none", "null", "dict", "list", "str", "int", "bool",
        "class", "def", "async", "await", "import", "return", "self", "todo", "v1", "v2",
        "mcp", "api", "json", "env", "gui", "tui", "sse", "sqlite"}


def resolve(idx, ref):
    norm = ref.replace("\\", "/")
    base = os.path.basename(norm)
    cands = idx.get(base, [])
    if not cands:
        return None, "no_basename"
    hits = [c for c in cands if c.replace("\\", "/").endswith("/" + norm)]
    if len(hits) == 1:
        return hits[0], "ok"
    if len(hits) > 1:
        return hits[0], "ambig"
    if len(cands) == 1:
        return cands[0], "basename_only"
    return cands[0], "ambig_basename"


def audit_citations():
    idx = build_index()
    stat = collections.Counter()
    bad, missing, offset = [], [], []
    for f in sorted(glob.glob(os.path.join(BOOK, "*.md"))):
        src = read_text(f)
        name = os.path.basename(f)
        for m in CITE.finditer(src):
            ref, lns = m.group(1), m.group(2)
            full, how = resolve(idx, ref)
            if not full:
                missing.append((name, ref, lns))
                stat["MISSING"] += 1
                continue
            lines = read_text(full).splitlines()
            n = len(lines)
            nums = [int(x) for x in re.split(r"[/\-]", lns) if x.strip().isdigit()]
            if not nums:
                continue
            if max(nums) > n:
                bad.append((name, ref, max(nums), n, how, full.replace(ROOT, ".")))
                stat["OOB"] += 1
                continue
            stat["OK"] += 1
            # 符号邻近（启发式）
            ls = src.rfind("\n", 0, m.start()) + 1
            le = src.find("\n", m.end())
            cat = "\t"
            row = src[ls:le if le > 0 else len(src)]
            cell = next((c for c in row.split("|") if m.group(0)[1:-1] in c.replace("`", "")), row)
            ids = {i for i in IDENT.findall(cell) if i not in STOP}
            if not ids:
                continue
            lo, hi = max(0, min(nums) - 31), min(n, max(nums) + 30)
            window = "\n".join(lines[lo:hi])
            whole = "\n".join(lines)
            for i in sorted(ids):
                if i not in whole:
                    offset.append((name, ref, lns, i, "符号不在该文件", full.replace(ROOT, ".")))
                elif i not in window:
                    offset.append((name, ref, lns, i, "符号在文件中但离引用行 >30 行",
                                   full.replace(ROOT, ".")))
    return stat, bad, missing, offset


def audit_coverage():
    text = "".join(read_text(f) for f in glob.glob(os.path.join(BOOK, "*.md")))
    rows = []
    for label, base, exts in (("python/", "python", (".py",)),
                              ("gui/src", "gui/src", (".ts", ".tsx")),
                              ("tui/src", "tui/src", (".ts", ".tsx")),
                              ("gui/src-tauri/src", "gui/src-tauri/src", (".rs",))):
        tot = 0
        never = []
        for rel in _walk(base):
            if not rel.endswith(exts) or _is_test(rel):
                continue
            tot += 1
            stem = os.path.splitext(os.path.basename(rel))[0]
            if stem != "__init__" and stem not in text:
                never.append(rel)
        rows.append((label, tot, never))
    return rows


def main():
    stat, bad, missing, offset = audit_citations()
    real = [b for b in bad if b[4] in ("ok", "basename_only")]
    ambig = [b for b in bad if b[4] not in ("ok", "basename_only")]
    print("=" * 72)
    print("【1】引用核验")
    print("=" * 72)
    print("  通过                   : %d" % stat["OK"])
    print("  行号越界·**真错**      : %d   ← 只有这个数字需要处理" % len(real))
    print("  行号越界·解析歧义(ambig): %d   ← 裸文件名撞名，多为误报，人工扫一眼即可" % len(ambig))
    print("  未解析到文件           : %d" % stat["MISSING"])
    print("  可疑符号邻近           : %d" % len(offset))
    print()
    if real:
        print("  -- ⚠ 真·行号越界（请修）--")
        for name, ref, mx, n, how, full in real:
            print("     [%s] %s:%s  (总行 %s) -> %s" % (name, ref, mx, n, full))
        print()
    if ambig:
        print("  -- 解析歧义（ambig，多数是误报）--")
        seen = set()
        for name, ref, mx, n, how, full in ambig:
            k = (os.path.basename(ref))
            if k in seen:
                continue
            seen.add(k)
            print("     [%s] %s:%s  (误解析到总行 %s 的 %s)" % (name, ref, mx, n, full))
        print()
    if missing:
        print("  -- 未解析（本脚本索引未覆盖的路径，通常仍有效）--")
        for name, ref, lns in missing:
            print("     [%s] %s:%s" % (name, ref, lns))
        print()
    if offset:
        print("  -- 符号邻近可疑（前 15 条；跨单元格误报较常见）--")
        for name, ref, lns, ident, why, full in offset[:15]:
            print("     [%s] %s:%s  `%s`  %s" % (name, ref, lns, ident, why))
        print()

    print("=" * 72)
    print("【2】文件级覆盖率（「文件名一次未出现」的源文件数，排除测试）")
    print("=" * 72)
    for label, tot, never in audit_coverage():
        print("  %-20s %4d 源文件   未提及 %4d  %5.1f%%" % (label, tot, len(never), 100.0 * len(never) / max(tot, 1)))
    print()
    print("提示：本脚本是启发式。它能发现「越界 / 错位」，发现不了「语义讲反」——")
    print("      语义级错误必须人工回源码逐行读（例见 00-README「第四轮」§4）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
