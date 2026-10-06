"""代码“AI 味”普查器（只读）。

统计对象：python/ 生产代码、gui/src、tui/src（测试/脚本/评估单独分桶，不混入生产口径）。
口径：
- 注释用 tokenize 与字符串严格区分（Python）；emoji 在注释里与在字符串里分开计数。
- banner=注释文本以 4+ 个 [=\-─═*] 连排开头（分隔条）。
- 长注释=注释文本 ≥100 字符；叙述词=我们/咱们/注意/记住/务必/千万不要/这里。
- docstring 用 AST 定位（module/class/function 体首部 Expr-Str）。
- 宽 except：`except Exception` / `except BaseException` 出现次数；`# noqa: BLE001` 次数。
- TS/TSX：行扫描识别 // 与 /* */ 注释；*.test.* 归测试桶。

用法：py -3.11 scripts/ai_flavor_census.py [--out reports/ai-flavor-census.json]
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import tokenize
from collections import defaultdict
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]

PY_CORE_DIRS = {
    "engine", "memory", "server", "tools", "session", "prompt", "model",
    "synaptic", "channels", "extension", "permissions", "rewind", "slash",
    "usage", "diagnostics", "cli", "bridge", "msgtypes", "common", "audit",
    "codeindex", "coord", "localmodels",
}
SKIP_DIRS = {
    "__pycache__", ".venv", "venv", "node_modules", "target", "dist",
    "build", ".pytest_cache", ".mypy_cache", ".ruff_cache",
}

BANNER_RE = re.compile(r"^[=\-─═*•·#]{4,}")
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u2705\u274C\u26A0]"
)
TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX|WIP)\b", re.I)
NARRATIVE = ["我们", "咱们", "注意", "记住", "务必", "千万不要", "这里"]
LONG_COMMENT_CHARS = 100


def line_of(text: str, token_line: int) -> str:
    return text.splitlines()[token_line - 1] if token_line - 1 < len(text.splitlines()) else ""


def scan_python(path: Path) -> dict:
    src = path.read_text(encoding="utf-8", errors="replace")
    out: dict = {
        "loc": len(src.splitlines()),
        "code_lines": 0,
        "comment_lines": 0,
        "comment_chars": 0,
        "banner": 0,
        "emoji_comment": 0,
        "emoji_string": 0,
        "todo": 0,
        "narrative": {k: 0 for k in NARRATIVE},
        "long_comments": [],
        "section_ref": 0,
        "except_wide": 0,
        "noqa_broad": 0,
        "functions": 0,
        "funcs_with_doc": 0,
        "docstring_lines": 0,
        "module_docstring_lines": 0,
        "max_doc": ("", 0),
    }
    lines = src.splitlines()
    comment_lines: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type != tokenize.COMMENT:
                continue
            comment_lines.add(tok.start[0])
            text = tok.string.lstrip("#").strip()
            out["comment_lines"] += 1
            out["comment_chars"] += len(text)
            if BANNER_RE.match(text):
                out["banner"] += 1
            if EMOJI_RE.search(text):
                out["emoji_comment"] += 1
            if TODO_RE.search(text):
                out["todo"] += 1
            for k in NARRATIVE:
                out["narrative"][k] += text.count(k)
            out["section_ref"] += text.count("§")
            if len(text) >= LONG_COMMENT_CHARS:
                out["long_comments"].append({"line": tok.start[0], "len": len(text), "head": text[:60]})
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    # 字符串内 emoji（含 docstring）
    str_lits: list[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                str_lits.append(node.value)
            doc = None
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                        and isinstance(body[0].value.value, str):
                    doc = body[0].value.value
                    dlines = doc.count("\n") + 1
                    out["docstring_lines"] += dlines
                    if isinstance(node, ast.Module):
                        out["module_docstring_lines"] = dlines
                    if len(doc) > out["max_doc"][1]:
                        name = getattr(node, "name", "<module>")
                        out["max_doc"] = (f"{name}@{getattr(node, 'lineno', 1)}", len(doc))
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        out["funcs_with_doc"] += 1
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out["functions"] += 1
            if isinstance(node, ast.ExceptHandler) and node.type is not None:
                t = node.type
                nm = t.id if isinstance(t, ast.Name) else (t.attr if isinstance(t, ast.Attribute) else "")
                if nm in ("Exception", "BaseException"):
                    out["except_wide"] += 1
        for lit in str_lits:
            if EMOJI_RE.search(lit):
                out["emoji_string"] += 1
    out["code_lines"] = len(lines) - len(comment_lines) - sum(1 for l in lines if not l.strip())
    out["noqa_broad"] = src.count("noqa: BLE001")
    out["max_doc"] = list(out["max_doc"])
    return out


TS_LINE_COMMENT = re.compile(r"//")
TS_BLOCK_OPEN = re.compile(r"/\*")


def scan_ts(path: Path) -> dict:
    src = path.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    out: dict = {
        "loc": len(lines), "comment_lines": 0, "code_lines": 0, "comment_chars": 0,
        "banner": 0, "emoji_comment": 0, "emoji_string": 0, "todo": 0,
        "narrative": {k: 0 for k in NARRATIVE}, "long_comments": [],
        "section_ref": 0, "except_wide": 0, "noqa_broad": 0,
        "functions": 0, "funcs_with_doc": 0, "docstring_lines": 0,
        "module_docstring_lines": 0, "max_doc": ["", 0],
    }
    in_block = False
    for i, raw in enumerate(lines, 1):
        line = raw.strip()
        text = ""
        if in_block:
            text = line.split("*/", 1)[0]
            if "*/" in line:
                in_block = False
        elif line.startswith("/*"):
            text = line[2:].split("*/", 1)[0]
            in_block = "*/" not in line
        elif line.startswith("//"):
            text = line[2:]
        # 行尾 // 注释（粗略：跳过含 :// 的 URL 行）
        elif "//" in line and "://" not in line:
            text = line.split("//", 1)[1]
        if not text:
            continue
        text = text.strip().lstrip("*").strip()
        out["comment_lines"] += 1
        out["comment_chars"] += len(text)
        if BANNER_RE.match(text):
            out["banner"] += 1
        if EMOJI_RE.search(text):
            out["emoji_comment"] += 1
        if TODO_RE.search(text):
            out["todo"] += 1
        for k in NARRATIVE:
            out["narrative"][k] += text.count(k)
        out["section_ref"] += text.count("§")
        if len(text) >= LONG_COMMENT_CHARS:
            out["long_comments"].append({"line": i, "len": len(text), "head": text[:60]})
    # 字符串内 emoji（粗略：去注释后全行搜；注释已有文本时整体跳过）
    code_only = "\n".join(l for l in lines if not l.strip().startswith(("//", "/*", "*")))
    out["emoji_string"] = len(EMOJI_RE.findall(code_only))
    out["code_lines"] = len(lines) - out["comment_lines"] - sum(1 for l in lines if not l.strip())
    return out


def bucket_of(rel: Path) -> str:
    parts = rel.parts
    if parts[0] == "python":
        if len(parts) > 1 and parts[1] in PY_CORE_DIRS:
            return "py-core"
        if len(parts) > 1 and parts[1] == "tests":
            return "py-tests"
        return "py-dev"
    if parts[0] == "gui":
        return "gui-tests" if ("e2e" in parts[:2] or ".test." in rel.name) else "gui-src"
    if parts[0] == "tui":
        return "tui-tests" if ".test." in rel.name else "tui-src"
    return "other"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/ai-flavor-census.json")
    args = ap.parse_args()

    files: list[dict] = []
    roots = [ROOT / "python", ROOT / "gui" / "src", ROOT / "tui" / "src"]
    for root in roots:
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(ROOT)
            if set(p.parts) & SKIP_DIRS:
                continue
            if p.suffix == ".py":
                m = scan_python(p)
            elif p.suffix in (".ts", ".tsx"):
                m = scan_ts(p)
            else:
                continue
            m["path"] = str(rel).replace("\\", "/")
            m["bucket"] = bucket_of(rel)
            files.append(m)

    agg: dict = defaultdict(lambda: defaultdict(float))
    for f in files:
        b = agg[f["bucket"]]
        for k in ("loc", "code_lines", "comment_lines", "comment_chars", "banner",
                  "emoji_comment", "emoji_string", "todo", "section_ref",
                  "except_wide", "noqa_broad", "functions", "funcs_with_doc",
                  "docstring_lines", "module_docstring_lines"):
            b[k] += f[k]
        for k, v in f["narrative"].items():
            b[f"nar_{k}"] += v
        if f["long_comments"]:
            b["long_comment_lines"] += len(f["long_comments"])

    def top(key=None, n=25, bucket=None, fn=None):
        if fn is None:
            fn = lambda f: f.get(key, 0)  # noqa: E731
        pool = [f for f in files if (bucket is None or f["bucket"] == bucket)]
        return sorted(pool, key=fn, reverse=True)[:n]

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "buckets": {k: dict(v) for k, v in sorted(agg.items())},
        "top_banner": [(f["path"], f["banner"]) for f in top("banner") if f["banner"]],
        "top_long_comments": [(f["path"], len(f["long_comments"])) for f in top("long_comments", fn=lambda f: len(f["long_comments"])) if f["long_comments"]],
        "top_emoji_string": [(f["path"], f["emoji_string"]) for f in top("emoji_string") if f["emoji_string"]],
        "top_except_wide": [(f["path"], f["except_wide"]) for f in top("except_wide") if f["except_wide"]],
        "top_noqa": [(f["path"], f["noqa_broad"]) for f in top("noqa_broad") if f["noqa_broad"]],
        "todo_sites": [f["path"] for f in files if f["todo"]],
    }
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"summary": summary, "files": files}, fh, ensure_ascii=False, indent=1)

    print("== 分桶汇总 ==")
    for k, v in sorted(agg.items()):
        cl = int(v["comment_lines"])
        ratio = (cl / v["code_lines"] * 100) if v["code_lines"] else 0
        print(f"[{k}] files loc={int(v['loc'])} code={int(v['code_lines'])} comment={cl} "
              f"({ratio:.1f}% 注释密度) banner={int(v['banner'])} emoji_c={int(v['emoji_comment'])} "
              f"emoji_s={int(v['emoji_string'])} todo={int(v['todo'])} long={int(v['long_comment_lines'])} "
              f"except_wide={int(v['except_wide'])} noqa={int(v['noqa_broad'])} "
              f"funcs={int(v['functions'])} 带doc={int(v['funcs_with_doc'])} doc_lines={int(v['docstring_lines'])}")
        nar = {k2[4:]: int(v2) for k2, v2 in v.items() if k2.startswith("nar_") and v2}
        if nar:
            print(f"    叙述词: {nar}")
    print(f"\nJSON → {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
