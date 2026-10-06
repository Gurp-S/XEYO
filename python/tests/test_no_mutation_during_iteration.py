"""静态门：不许"边迭代容器边改它"（RuntimeError / 静默漏项）。

这族在本仓真炸过两次：
- `permissions/ask_store.py::_prune`（10-03 结案的真产品缺陷）：边 `for r, it in self._items.items()`
  边 `pop` ⇒ 只要有一条过期未决项，之后每次 `create()` 都抛 RuntimeError，整条提问通路变成工具错误。
- `tools/orchestration.py:290` 的注释里留着那次竞态（`dictionary changed size during iteration`）。

判据（宁可窄、不许是装饰）：
- `for <targets> in <容器视图>`：容器 = `X.items()/.keys()/.values()`，且没被
  `list()/sorted()/tuple()/dict()/set()/reversed()/.copy()` 物化过；
- 或 `for <t> in <容器>`（容器是 Name/Attribute 表达式）；
- 同一循环体内对**同一个容器表达式**做会增删元素的操作（`pop/del/clear/update/setdefault/popitem`
  或 `del c[...]`）。**不**判 `c[k] = v`：`for key in d: d[key] = 0` 是清零的标准写法，
  对已有键赋值不改大小，不会抛。
排除：`enumerate/zip/map/filter` 包过的迭代（按索引写回是合法形状），以及物化过的。
"""

import ast
import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROD_DIRS = (
    "audit", "channels", "coord", "diagnostics", "engine", "extension", "memory",
    "model", "permissions", "prompt", "rewind", "server", "session", "slash",
    "synaptic", "tools", "usage",
)

#: 全树当前 0 命中 ⇒ 新出现即为回归；有在途文件被判红时先记在这里（必须写清归属与摘除条件）。
KNOWN: set[str] = set()

MUT_METHODS = ("pop", "clear", "setdefault", "update", "popitem", "add", "discard")
VIEWS = ("items", "keys", "values")
MATERIALIZED = ("list", "sorted", "tuple", "set", "dict", "reversed")
GENEROUS = ("enumerate", "zip", "map", "filter", "itertools")


def _callee_text(call):
    return ast.unparse(call.func)


def _iter_container(it):
    """返回被迭代容器的表达式文本；若该迭代形状豁免则返回 None。"""
    if not isinstance(it, ast.Call):
        if isinstance(it, (ast.Name, ast.Attribute, ast.Subscript)):
            return ast.unparse(it)
        return None
    head = _callee_text(it)
    # list(d.items()) / sorted(...) / enumerate(...) 等：物化或按索引写回，豁免
    if isinstance(it.func, ast.Name) and (
        it.func.id in MATERIALIZED or it.func.id in GENEROUS
    ):
        return None
    # d.copy().items() 豁免
    if isinstance(it.func, ast.Attribute) and it.func.attr in VIEWS:
        inner = it.func.value
        if isinstance(inner, ast.Call) and _callee_text(inner).endswith(".copy"):
            return None
        if isinstance(inner, (ast.Name, ast.Attribute, ast.Call, ast.Subscript)):
            return ast.unparse(inner)
        return None
    if isinstance(it.func, ast.Attribute) and it.func.attr == "copy":
        return None
    return None


def _mutations(body):
    """循环体内会**改变容器大小**的修改（容器表达式 → 形式）。

    故意不认 `c[k] = v`：`for key in d: d[key] = 0` 是"清零"的标准写法，
    对已有键赋值不改大小 ⇒ 不抛。判红只留给真会增删元素的操作。
    """
    out = {}
    for sub in ast.walk(body if isinstance(body, ast.AST) else ast.Module(body, [])):
        if isinstance(sub, ast.Delete):
            for t in sub.targets:
                if isinstance(t, ast.Subscript):
                    out.setdefault(ast.unparse(t.value), set()).add("del []")
        elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            if sub.func.attr in MUT_METHODS:
                # 容器身份 = 被调用方法挂在谁身上（func.value），不是 func 本身
                out.setdefault(ast.unparse(sub.func.value), set()).add(sub.func.attr)
    return out


def _for_hits(node):
    hits = []
    for stmt in ast.walk(node):
        if not isinstance(stmt, ast.For):
            continue
        container = _iter_container(stmt.iter)
        if not container:
            continue
        muts = _mutations(stmt)
        if container in muts:
            hits.append((stmt.lineno, container, ",".join(sorted(muts[container]))))
    return hits


def scan_source(src):
    tree = ast.parse(src)
    out = []
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for ln, container, form in _for_hits(fn):
                out.append((ln, fn.name, container, form))
    return out


# --- 探测器自己的控制组（0 命中必须先证明它能命中）------------------------------

_CTL_BAD = '''
def _prune(self):
    for rid, it in self._items.items():
        if it.expired:
            self._items.pop(rid)
'''

_CTL_BAD_KEYS = '''
def gc(store):
    for k in d.keys():
        del d[k]
'''

_CTL_BAD_PLAIN_DICT = '''
def sweep(entries):
    for k in entries:
        if entries[k] < 0:
            del entries[k]
'''

_CTL_GOOD = [
    '''
def _prune(self):
    for rid, it in list(self._items.items()):
        self._items.pop(rid)
''',
    '''
def _prune(self):
    stale = [r for r, it in self._items.items() if it.expired]
    for rid in stale:
        self._items.pop(rid)
''',
    '''
def _prune(self):
    for rid, it in self._items.copy().items():
        self._items.pop(rid)
''',
    '''
def _norm(items):
    for i, v in enumerate(items):
        items[i] = v.strip()
''',
    '''
def total(d):
    s = 0
    for k, v in d.items():
        s += v
    return s
''',
    # 清零的标准写法：赋值不改变大小
    '''
def reset_stats():
    for key in _stats:
        _stats[key] = 0
''',
    '''
def other(a, b):
    for k in a.keys():
        b.pop(k)
''',
]


def test_detector_has_teeth():
    for i, src in enumerate([_CTL_BAD, _CTL_BAD_KEYS, _CTL_BAD_PLAIN_DICT]):
        assert scan_source(src), f"坏形状 #{i} 必须被判红"
    for i, src in enumerate(_CTL_GOOD):
        assert not scan_source(src), f"安全形状 #{i} 不许被判红：{scan_source(src)}"


def test_production_has_no_mutation_during_iteration():
    found = set()
    files = []
    for d in PROD_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(str(base)):
            dirnames[:] = [x for x in dirnames if x not in ("__pycache__", ".venv")]
            for f in filenames:
                if f.endswith(".py"):
                    files.append(os.path.join(dirpath, f))
    files.extend(str(p) for p in sorted(ROOT.glob("*.py")))
    root_str = str(ROOT).replace("\\", "/")
    for path in files:
        rel = path.replace("\\", "/")[len(root_str) + 1:]
        # utf-8-sig：仓里有 BOM 源文件，utf-8 读会把 U+FEFF 交给 ast.parse 当场 SyntaxError
        src = io.open(path, encoding="utf-8-sig", errors="replace").read()
        try:
            hits = scan_source(src)
        except SyntaxError:
            hits = [(0, "UNPARSEABLE", "-", "-")]
        for ln, fn, container, form in hits:
            found.add(f"{rel}::{fn}")
    assert found == KNOWN, (
        "边迭代边改同一容器会抛 RuntimeError（本仓炸过两次，见模块 docstring）。\n"
        f"新出现: {sorted(found - KNOWN)}\n可以摘账: {sorted(KNOWN - found) or '无'}"
    )
