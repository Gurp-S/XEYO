"""周期门：现网**发射面**上声明出来的取回入口，照抄执行到底能不能成。

判据落在"模型看见的那段文本"上，不落在 `cold.handles` 上。这不是风格问题：
`tests/wsc/test_handle_style.py` 那组绿测的分子分母都取自冷层对象，实测**裁卡面
（热层头部那些入口）不会让任何一条现有测试变红**——因为被裁掉的入口根本不进分母。
本门把分母换成发射文本里的声明数，于是：

- 入口变少 ⇒ 分母变小（会被看见），而不是"通过率照旧 100%"；
- 入口参数坏 ⇒ `fail`；
- 判不了（归档文件已被覆盖 / 越权）⇒ `undecidable`，**既不算通过也不算失败**。

三态是硬要求：把不可判的当失败、或当通过，都是造数。

口径同源：解析用 `synaptic/handles._READ_RE`（生产渲染的同一张正则），
判定用真的 `FileReadTool`（25k token / 2000 行闸门在它里面），都不自己写。

跑法（零成本、只读）::

    cd python && py -3.11 -m evals.wsc_emitted_entries --max 12
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from synaptic.handles import _READ_RE  # 生产渲染 `Read(...)` 用的同一张正则  # noqa: E402

#: 归档缺失时的判法。普查现网账本用 UNDECIDABLE（发射当时是好的，文件后来被覆盖不算现网缺陷）；
#: 自造夹具用 FAIL（夹具里的入口本来就是这次生成的）。
UNDECIDABLE = "undecidable"
FAIL = "fail"

_MISSING = re.compile(r"(no such file|not found|does not exist|ENOENT)", re.I)
_CAP = re.compile(r"exceeds maximum allowed", re.I)
_PERMISSION = re.compile(r"permission", re.I)


@dataclass(frozen=True)
class Declaration:
    """发射文本里一条模型可以照抄的入口。"""

    path: str
    offset: int
    limit: int
    line: str

    def args(self) -> dict:
        return {"file_path": self.path, "offset": self.offset, "limit": self.limit}


def declarations(text: str) -> tuple[Declaration, ...]:
    """只解析发射文本本身（不筛来源 ⇒ 连工具结果里"引用到 Read 的源码/日志"也算进来）。"""
    return tuple(
        Declaration(m.group("path"), int(m.group("offset")), int(m.group("limit")),
                    text[: m.start()].rpartition("\n")[2].strip())
        for m in _READ_RE.finditer(text)
    )


#: 发射面里的 `Read(...)` 有两类来源：引擎在卡面上**声明**的出口，和工具结果正文里
#: **提及**的 `Read(...)`（实测：某个会话的 15 条"声明"里 12 条是被 `<tool_output>` 裹着的
#: 测试源码行，路径自然是假的）。把两类混在一个分母里 = 拿别人的字符串给自己判分。
#: 所以这里按"块"分：剥掉 `<tool_output…>` 包裹与 `cat -n` 行号前缀之后仍在的才算引擎声明。
_TOOL_OUTPUT = re.compile(r"<tool_output\b[^>]*>.*?(?:</tool_output>|\Z)", re.S)
_LINE_NUMBER = re.compile(r"(?m)^\s*\d+[→\-\t] ?")


def engine_declarations(text: str) -> tuple[Declaration, ...]:
    """引擎在卡面上声明的出口：先剥工具结果正文与行号前缀，再解析。"""
    return declarations(_LINE_NUMBER.sub("", _TOOL_OUTPUT.sub("\n", text)))


def flatten_last_x(sent) -> str:
    """`last_x_sent` 是 JSON 序列化容器：**必须先 parse 再展平**（裸子串匹配会被转义打断）。"""
    if isinstance(sent, str):
        try:
            sent = json.loads(sent)
        except json.JSONDecodeError:
            return sent
    parts: list[str] = []
    for msg in sent or ():
        if not isinstance(msg, dict):
            parts.append(str(msg))
            continue
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    body = block.get("text") or block.get("content")
                    if isinstance(body, str):
                        parts.append(body)
    return "\n".join(parts)


@dataclass
class Verdict:
    declared: int = 0
    ok: int = 0
    fail: int = 0
    undecidable: int = 0
    kinds: dict[str, int] = field(default_factory=dict)
    chars_returned: int = 0

    @property
    def judged(self) -> int:
        return self.ok + self.fail

    def fail_rate(self) -> float | None:
        """可判样本上的失败率；**分母为 0 时返回 None**（不许报 0.0 冒充"全绿"）。"""
        return (self.fail / self.judged) if self.judged else None

    def bump(self, kind: str) -> None:
        self.kinds[kind] = self.kinds.get(kind, 0) + 1


def judge(entries: Iterable[Declaration], *, read: Callable[[dict], tuple[bool, str]],
          missing_policy: str = UNDECIDABLE) -> Verdict:
    """逐条照抄执行。``read(args)`` 返回 ``(is_error, text)``，必须是生产工具本身。"""
    v = Verdict()
    for d in entries:
        v.declared += 1
        try:
            is_error, text = read(d.args())
        except Exception as exc:  # noqa: BLE001 - 工具层任何异常都算这条入口的账
            v.fail += 1
            v.bump(f"exception:{type(exc).__name__}")
            continue
        if not is_error:
            v.ok += 1
            v.chars_returned += len(text)
            continue
        kind = "over_cap" if _CAP.search(text) else (
            "permission" if _PERMISSION.search(text) else (
                "missing" if _MISSING.search(text) else "other"))
        if kind == "missing" and missing_policy == UNDECIDABLE:
            v.undecidable += 1
        elif kind == "permission":
            v.undecidable += 1        # 越权不是坏引用，是普查边界
        else:
            v.fail += 1
        v.bump(kind)
    return v


def _production_reader(workspace: Path):
    from engine.abort import AbortController
    from tools.file_read_tool.file_read_tool import FileReadTool

    tool = FileReadTool(cwd=str(workspace))

    def _read(args: dict) -> tuple[bool, str]:
        res = asyncio.run(tool.execute(dict(args), AbortController()))
        return bool(getattr(res, "is_error", False)), str(getattr(res, "content", ""))

    return _read


def _emitted_from_working(path: Path) -> str:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return ""
    return flatten_last_x(raw.get("last_x_sent"))


def census(sessions_dir: Path, workspace: Path, *, max_sessions: int = 12,
           read=None) -> dict:
    """对真实 `*.working.json` 逐会话量一遍，并**自证探针作用域**（分母逐会话打印）。"""
    read = read or _production_reader(workspace)
    rows: list[dict] = []
    scanned = 0
    for wp in sorted(sessions_dir.glob("*.working.json")):
        scanned += 1
        if len(rows) >= max_sessions:
            break
        emitted = _emitted_from_working(wp)
        if not emitted:
            continue
        all_decl = declarations(emitted)
        engine_decl = engine_declarations(emitted)
        if not all_decl:
            continue            # 这份发射面一个入口都没有 ⇒ 只计作用域，不计通过率
        v = judge(engine_decl, read=read)
        rows.append({"session": wp.name[: -len(".working.json")][:26],
                     "emitted_chars": len(emitted), "declared": v.declared,
                     "mentions_not_engine": len(all_decl) - len(engine_decl),
                     "declared_any": len(all_decl),
                     "ok": v.ok, "fail": v.fail, "undecidable": v.undecidable,
                     "fail_rate": v.fail_rate(), "kinds": v.kinds,
                     "chars_returned": v.chars_returned})
    judged = sum(r["ok"] + r["fail"] for r in rows)
    return {
        "working_files_seen": scanned,
        "sessions_with_entries": len(rows),
        "declared_total": sum(r["declared"] for r in rows),
        "mentions_not_engine_total": sum(r["mentions_not_engine"] for r in rows),
        "judged_total": judged,
        "undecidable_total": sum(r["undecidable"] for r in rows),
        "fail_total": sum(r["fail"] for r in rows),
        "fail_rate": (sum(r["fail"] for r in rows) / judged) if judged else None,
        "rows": rows,
    }


def _default_sessions_dir() -> str:
    """会话根走产品自己的权威解析（认 ``XEYO_SESSIONS_DIR``）。

    不在这里拼死 `~/.xeyo/sessions`：`tests/test_data_root_overrides.py` 就是钉这个家族的，
    而普查若读错树，报出来的"现网"其实是别的目录。
    """
    from memory.working import _sessions_dir

    return str(_sessions_dir())


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", default=_default_sessions_dir())
    ap.add_argument("--workspace", default=r"D:\lea\XenYon code")
    ap.add_argument("--max", type=int, default=12)
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)
    rep = census(Path(a.sessions), Path(a.workspace), max_sessions=a.max)
    # Windows GBK 控制台：只打 ASCII，中文/¥ 会炸
    print(f"working files seen : {rep['working_files_seen']}")
    print(f"sessions w/ entries: {rep['sessions_with_entries']}")
    print(f"declared (engine)  : {rep['declared_total']}")
    print(f"mentions in tool output (not judged): {rep['mentions_not_engine_total']}")
    print(f"judged (ok+fail)   : {rep['judged_total']}")
    print(f"undecidable        : {rep['undecidable_total']}")
    print(f"fail               : {rep['fail_total']}")
    print(f"fail rate          : {rep['fail_rate'] if rep['fail_rate'] is not None else 'n/a (no judged entry)'}")
    for r in rep["rows"]:
        print(f"  {r['session']:28s} engine={r['declared']:4d} mention={r['mentions_not_engine']:4d} "
              f"ok={r['ok']:4d} fail={r['fail']:4d} undecidable={r['undecidable']:4d} "
              f"kinds={r['kinds']}")
    if a.json:
        Path(a.json).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
