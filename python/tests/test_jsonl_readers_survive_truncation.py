"""JSONL 读数器必须扛住"半个多字节序列"（进程被杀留下的截断尾）。

事故形状（不是理论担忧）：`rewind/journal.py` 的注释自己写着
"进程被杀可能留下最后一行残页"，而它只在 **JSON 层**容忍坏行；文本模式
`open(..., encoding="utf-8")` 只要撞上一个坏字节就整文件抛
`UnicodeDecodeError`（它不是 `OSError`，那些 `except OSError` 拦不住），于是
"跳过坏行"退化成"整本读不出来"。落点按后果排：

- `session/record_transcript.py`：`_load_written_ids` 在**每一次落盘**上被调用
  ⇒ 该会话之后再也写不进转录；`load_transcript` 是 resume / `session_pool` 的入口
  ⇒ 会话直接打不开。
- `audit/log.py::read_all`：全局审计档 ⇒ 诊断中心整页 500。
- `rewind/{index,journal,revision,blob_gc}.py`：rewind 读不到自己的账本。

口径：坏字节只报废它所在的那一行，其余行一律照原样可用。
"""

import ast
import io
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit.log import AuditLog  # noqa: E402
from memory.simulator.replay import load_jsonl as sim_load_jsonl  # noqa: E402
from rewind.blob_gc import _iter_jsonl  # noqa: E402
from rewind.index import _read_rows  # noqa: E402
from rewind.journal import _parse_jsonl  # noqa: E402
from rewind.revision import _read_jsonl  # noqa: E402
from session.record_transcript import _load_written_ids, load_transcript  # noqa: E402
from synaptic.replay import load_jsonl as syn_load_jsonl  # noqa: E402

_GOOD = [
    {"id": "m1", "role": "user", "content": "你好世界"},
    {"id": "m2", "role": "assistant", "content": "ok 中文"},
]


def _truncated_tail(rows):
    """好行若干 + 末行截在某个多字节字符中间（真实的强杀形状）。"""
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8")
    tail = json.dumps(
        {"id": "m3", "role": "tool", "content": "中断"}, ensure_ascii=False
    ).encode("utf-8")
    cut = tail.index("中".encode("utf-8")[0])  # 落进「中」的字节序列里
    return body + tail[: cut + 1]


def _bad_line_midfile(rows):
    """坏字节夹在中间一行（外来写手/编码错乱的形状），前后都是好行。"""
    lines = [json.dumps(r, ensure_ascii=False).encode("utf-8") for r in rows]
    junk = b'{"id": "mX", "content": "\xc3\xa5\xbc\x82\xe5\x8a"}'
    return b"\n".join(lines[:1] + [junk] + lines[1:]) + b"\n"


def _write(tmp_path, payload, name="f.jsonl"):
    p = tmp_path / name
    p.write_bytes(payload)
    return p


_READERS = [
    ("session.record_transcript.load_transcript", lambda p: load_transcript(p)),
    ("session.record_transcript._load_written_ids", lambda p: _load_written_ids(p)),
    ("rewind.index._read_rows", lambda p: _read_rows(p)),
    ("rewind.journal._parse_jsonl", lambda p: _parse_jsonl(p)),
    ("rewind.revision._read_jsonl", lambda p: _read_jsonl(p)),
    ("rewind.blob_gc._iter_jsonl", lambda p: list(_iter_jsonl(p))),
    ("memory.simulator.replay.load_jsonl", lambda p: sim_load_jsonl(p)),
    ("synaptic.replay.load_jsonl", lambda p: syn_load_jsonl(p, hydrate=False)),
]
_IDS = {name: (lambda res: sorted(res) if isinstance(res, set) else [str(r.get("id")) for r in res])
        for name, _ in _READERS}


def _ids_of(name, res):
    return _IDS[name](res)


@pytest.mark.parametrize("name,reader", _READERS, ids=[n for n, _ in _READERS])
def test_truncated_tail_does_not_brick_the_reader(tmp_path, name, reader):
    payload = _truncated_tail(_GOOD)
    p = _write(tmp_path, payload)
    # 前置自证：夹具确实是非法 UTF-8，否则这条门是装饰（文本模式读它必抛）。
    with pytest.raises(UnicodeDecodeError):
        payload.decode("utf-8")
    with pytest.raises(UnicodeDecodeError):
        p.read_text(encoding="utf-8")

    res = reader(p)  # 修前：UnicodeDecodeError 从这里逃出
    assert _ids_of(name, res) == ["m1", "m2"], f"{name}: 好行必须全部留住"


@pytest.mark.parametrize("name,reader", _READERS, ids=[n for n, _ in _READERS])
def test_midfile_bad_bytes_only_cost_their_own_line(tmp_path, name, reader):
    p = _write(tmp_path, _bad_line_midfile(_GOOD))
    with pytest.raises(UnicodeDecodeError):
        p.read_text(encoding="utf-8")
    res = reader(p)
    got = _ids_of(name, res)
    assert "m1" in got and "m2" in got, f"{name}: 坏行前后的好行都要可用"
    # 坏行本身按 errors="replace" 解码：多数形状解析不出 JSON 就被跳过，
    # 少数（替换符落在字符串值里）仍是一条合法 JSON——两种都不许把整本带走。
    assert len(got) >= 2, f"{name}: 只该多/少它自己那一行，实际={got}"


def test_audit_read_all_survives_truncated_tail(tmp_path):
    """审计档是全局单文件：一处坏字节会让诊断中心整页 500。"""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record("k1")
    log.record("k2", note="中文备注")
    p = tmp_path / "audit.jsonl"
    junk = json.dumps({"kind": "k3", "note": "中文"}, ensure_ascii=False).encode("utf-8")
    p.write_bytes(p.read_bytes() + junk[: junk.index("中".encode("utf-8")[0]) + 1])
    with pytest.raises(UnicodeDecodeError):
        p.read_text(encoding="utf-8")
    rows = log.read_all()
    kinds = [r.get("kind") for r in rows]
    assert kinds == ["k1", "k2"], f"坏行只该报废它自己，实际={kinds}"


# --- 静态门：这个形状不许再以生产形态出现 -----------------------------------

PROD_DIRS = (
    "audit", "coord", "engine", "memory", "model", "permissions", "prompt",
    "rewind", "server", "session", "synaptic", "tools", "usage", "channels",
    "extension", "diagnostics", "media_store", "slash", "hooks", "mcp",
)
#: 2026-10-05：两处历史欠账（10-03 挂的 action_journal._latest / rewind._read_jsonl）
#: 已按家族形状修复（逐行取字节 + decode(replace)，各自的行级严格校验语义不变），
#: 摘账 ⇒ 本门零欠账。
KNOWN: set[str] = set()


def _call_open_info(call):
    """返回 (mode, encoding 关键字, errors 关键字)。

    `Path.open(mode, ...)` 的首个位置参就是 mode，而内置 `open(file, mode, ...)`
    的 mode 在第 2 个——混用会把 "w" 当成 "r"，门于是去咬写盘调用、又放过真读数器。
    """
    is_method = isinstance(call.func, ast.Attribute)
    mode, enc, errs = None, None, None
    if call.args:
        first = call.args[0] if is_method else (call.args[1] if len(call.args) >= 2 else None)
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            mode = first.value
    for k in call.keywords:
        if k.arg == "mode" and isinstance(k.value, ast.Constant):
            mode = k.value.value
        elif k.arg == "encoding":
            enc = k.value
        elif k.arg == "errors":
            errs = k.value
    return mode, enc, errs


def _offenders(src):
    tree = ast.parse(src)
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        has_json = any(
            isinstance(s, ast.Call) and ast.unparse(s.func).endswith("loads")
            for s in ast.walk(fn)
        )
        catches = {
            ast.unparse(s.type) if s.type else "" for s in ast.walk(fn) if isinstance(s, ast.ExceptHandler)
        }
        if catches & {"UnicodeDecodeError", "ValueError", "BaseException", "Exception"}:
            continue
        if not has_json:
            continue
        for s in ast.walk(fn):
            if not isinstance(s, ast.Call):
                continue
            callee = ast.unparse(s.func)
            if not (callee.endswith(".open") or callee in ("open", "io.open")):
                continue
            mode, enc, errs = _call_open_info(s)
            mode = mode if isinstance(mode, str) else "r"
            if not mode.startswith("r") or "b" in mode:
                continue
            utf8 = isinstance(enc, ast.Constant) and enc.value == "utf-8"
            if utf8 and errs is None:
                out.append(f"{fn.name}:{s.lineno}")
    return out


def test_gate_detector_has_teeth():
    """门的正控：旧形状必须被判红、按行字节解码的形状不许判红。

    没有这一段，"全树 0 命中"完全可能只是探针永不匹配（本仓撞过多次）。
    """
    old = (
        "import json\n"
        "def _read(path):\n"
        "    out = []\n"
        "    with path.open('r', encoding='utf-8') as fh:\n"
        "        for line in fh:\n"
        "            try:\n"
        "                out.append(json.loads(line))\n"
        "            except json.JSONDecodeError:\n"
        "                continue\n"
        "    return out\n"
    )
    assert [h.split(":")[0] for h in _offenders(old)] == ["_read"], "旧形状必须判红"
    fixed = old.replace("path.open('r', encoding='utf-8')", "path.open('rb')").replace(
        "json.loads(line)", 'json.loads(line.decode("utf-8", errors="replace"))'
    )
    assert _offenders(fixed) == [], "逐行字节解码的形状不许判红"
    # 写盘调用不是这一族的成员（mode="w"）
    writer = (
        "import json\n"
        "def _write(path, rows):\n"
        "    with path.open('w', encoding='utf-8', newline='\\n') as fh:\n"
        "        fh.write(json.dumps(rows))\n"
    )
    assert _offenders(writer) == [], "写模式不许判红"


def test_no_unblessed_utf8_jsonl_readers():
    """生产码里禁止"文本模式 utf-8 读 + json.loads 且不兜 UnicodeDecodeError"。"""
    found = set()
    root = Path(__file__).resolve().parents[1]
    targets = []
    for d in PROD_DIRS:
        base = root / d
        if base.is_dir():
            for dirpath, dirnames, filenames in os.walk(str(base)):
                dirnames[:] = [x for x in dirnames if x != "__pycache__"]
                for f in filenames:
                    if f.endswith(".py"):
                        targets.append(os.path.join(dirpath, f))
    targets.extend(str(p) for p in sorted(root.glob("*.py")))
    root_str = str(root).replace("\\", "/")
    for path in targets:
        rel = path.replace("\\", "/")[len(root_str) + 1:]
        # utf-8-sig：仓里有带 BOM 的源文件，用 utf-8 读会把 U+FEFF 留给 ast.parse 并当场炸。
        src = io.open(path, encoding="utf-8-sig", errors="replace").read()
        try:
            hits = _offenders(src)
        except SyntaxError:
            # 不静默跳过：解析不了的档会挂在这里，逼我逐条判它是语法新式还是我的探针太旧。
            hits = ["UNPARSEABLE"]
        for hit in hits:
            found.add(f"{rel}::{hit.split(':', 1)[0]}")
    assert found == KNOWN, (
        "JSONL 读数器必须逐行按字节解码（见本文件 docstring 的事故形状）。\n"
        f"新出现: {sorted(found - KNOWN)}\n可以摘账: {sorted(KNOWN - found) or '无'}"
    )
