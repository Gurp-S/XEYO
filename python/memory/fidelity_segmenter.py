"""L6 原子事实分段：把「中间游离区 M」按信息原子切分（确定性、纯函数）。

背景（P1 缺失1）：
    压缩态早期事实保真下降（67% vs 92%）的主因之一是——质量模型 Q 把一整条
    tool_result 当**一个**事实单元。一条 8KB 的工具结果里，报错栈、取值行、噪声
    混在一起，Q 只按「消息条数 × 单权重」计权，无法区分「哪些是硬事实」。于是
    C1 占位 / C2 摘要把整段一起处理，宝贵的硬事实被折叠掉。

    本模块用**确定性工程**弥补：把 M 段按「信息原子」切分，得到一批原子 `a_i`，
    每原子带权重 `v_i`（字符长度），满足 ``Σ v_i = |M|``（精确划分，无缝隙无重叠）。
    Q 改为按原子计权（见 ``state_model`` 的挂载），一个报错栈原子与一个取值原子
    是**独立单元**——折叠报错栈不再连带把取值行一起减信。

设计约束（对齐交接提示词）：
    - 只改「表示粒度」，不改 v6.1 的 Q/J/投票公式。
    - ``split_into_atoms`` 是纯函数，无 I/O、无状态，可离线单测。
    - 末尾 ``assert sum(weight) == len(original_text)`` 保证划分无损。
    - 开关 ``XEYO_ATOM_SEGMENT``（默认关），只有在 v61 / C2 需要按原子计权时才开，
      默认 project 路径保持既有字节行为（不回归）。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from memory.token import token_len

#: 兜底按行分组 / 超大行分块的字符阈值（行内超过此值再切成 512 字符块）。
MAX_LINE_CHARS = 512
#: 结构化块识别：栈回溯起点。
_TRACEBACK_RE = re.compile(r"^\s*traceback\s*\(most recent call last\)", re.IGNORECASE)
#: 栈回溯收尾的异常行（如 ``ValueError: bad value``），列首不缩进，属栈的一部分。
_ERROR_TERMINUS_RE = re.compile(
    r"^\s*[\w.$<>]+(?:Error|Exception|Warning|Error\b)\s*:", re.IGNORECASE
)
#: 文件树节点（tree / lg 输出）。
_TREE_NODE_RE = re.compile(r"^\s*(?:[├└│]|`?[-+])\s*-?[─]?\s*[\w.]")
#: key=value / key: value 行。
_KV_RE = re.compile(r"^[\w.\- ]{1,48}?\s*[=:]\s*\S.{0,200}$")
#: 表格行（markdown | ... |）。
_TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
#: 路径行（/path:line 或 /path/to/file）。
_PATH_RE = re.compile(r"^(?:[A-Za-z]:)?[\\/][^\s:]{1,120}(?::\d+)?\s*$")
#: JSON 对象 / 数组块起点。
_JSON_OPEN_RE = re.compile(r"^\s*[\[{]")


@dataclass(frozen=True)
class Atom:
    """一条信息原子。

    ``text`` 是原文本的精确切片；``weight`` 恒等于 ``len(text)``（字符数），
    因此 ``Σ weight == |M|`` 恒成立。``kind`` 标记原子类型，供 Q 计权分组用。
    ``start``/``end`` 是其在原始文本里的偏移（半开区间），用于溯源。
    """

    text: str
    weight: int
    kind: str
    start: int
    end: int

    @property
    def tokens(self) -> int:
        return token_len(self.text)


def atoms_enabled() -> bool:
    """XEYO_ATOM_SEGMENT 是否开启（默认关；v61 才按原子计权）。"""
    raw = os.environ.get("XEYO_ATOM_SEGMENT", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _line_spans(text: str) -> list[tuple[int, int]]:
    """把 text 精确切成一行的半开区间，保留换行符，覆盖 [0, len)。"""
    spans: list[tuple[int, int]] = []
    pos = 0
    n = len(text)
    while pos < n:
        nl = text.find("\n", pos)
        if nl == -1:
            spans.append((pos, n))
            break
        spans.append((pos, nl + 1))
        pos = nl + 1
    return spans


def _body_extent(text: str, start: int, end: int) -> str:
    """去掉行尾换行符后的行正文（不含行首缩进剥离）。"""
    return text[start:end].rstrip("\r\n")


def _is_blank(text: str, start: int, end: int) -> bool:
    return not _body_extent(text, start, end).strip()


def _traceback_block(text: str, spans: list[tuple[int, int]], i: int) -> int | None:
    """栈回溯：从 Traceback 起点吞并「连续缩进行/空行 + 收尾异常行」；返回下一条下标。"""
    start, end = spans[i]
    body = _body_extent(text, start, end)
    if not _TRACEBACK_RE.match(body):
        return None
    j = i + 1
    total = len(spans)
    while j < total:
        s, e = spans[j]
        ln = _body_extent(text, s, e)
        if not ln.strip():
            # 空行：属于回溯内部（帧间空行），继续
            j += 1
            continue
        if ln[0] in (" ", "\t"):
            # 缩进（File "...", line N / at ... / 错误消息）
            j += 1
            continue
        # 非缩进行：若是异常收尾行（列首不缩进）归入栈，否则栈到此结束
        if _ERROR_TERMINUS_RE.match(ln.strip()):
            j += 1
        break
    return j


def _tree_block(text: str, spans: list[tuple[int, int]], i: int) -> int | None:
    """文件树：从树节点起点吞并连续树节点行；返回下一条下标。"""
    start, end = spans[i]
    if not _TREE_NODE_RE.match(_body_extent(text, start, end)):
        return None
    j = i
    total = len(spans)
    while j < total:
        s, e = spans[j]
        if _TREE_NODE_RE.match(_body_extent(text, s, e)):
            j += 1
            continue
        if _is_blank(text, s, e):
            j += 1
            continue
        break
    return j


def _json_block(text: str, spans: list[tuple[int, int]], i: int) -> int | None:
    """JSON 对象/数组块：从 `{`/`[` 起点按花括号/方括号平衡吞并；返回下一条下标。"""
    body = _body_extent(text, *spans[i]).strip()
    if not _JSON_OPEN_RE.match(body):
        return None
    depth = 0
    j = i
    total = len(spans)
    # 先累积到当前行，遇到闭合后再看是否收尾
    while j < total:
        s, e = spans[j]
        for ch in text[s:e]:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
        j += 1
        if depth <= 0:
            break
    return j


def _kv_group(text: str, spans: list[tuple[int, int]], i: int) -> int | None:
    """key=value 行组：连续匹配的取值行，**逐行**成为独立原子；返回下一条下标。"""
    start, end = spans[i]
    if not _KV_RE.match(_body_extent(text, start, end).strip()):
        return None
    j = i
    total = len(spans)
    while j < total:
        s, e = spans[j]
        body = _body_extent(text, s, e).strip()
        if not body:
            break
        if not _KV_RE.match(body):
            break
        j += 1
    return j


def _table_group(text: str, spans: list[tuple[int, int]], i: int) -> int | None:
    """markdown 表格行组：连续 `|...|` 行，逐行构成原子；返回下一条下标。"""
    start, end = spans[i]
    if not _TABLE_RE.match(_body_extent(text, start, end).strip()):
        return None
    j = i
    total = len(spans)
    while j < total:
        s, e = spans[j]
        body = _body_extent(text, s, e).strip()
        if not body:
            break
        if not _TABLE_RE.match(body):
            break
        j += 1
    return j


def _path_group(text: str, spans: list[tuple[int, int]], i: int) -> int | None:
    """路径行组：连续路径行，逐行构成原子；返回下一条下标。"""
    start, end = spans[i]
    if not _PATH_RE.match(_body_extent(text, start, end).strip()):
        return None
    j = i
    total = len(spans)
    while j < total:
        s, e = spans[j]
        body = _body_extent(text, s, e).strip()
        if not body:
            break
        if not _PATH_RE.match(body):
            break
        j += 1
    return j


def _fallback_atoms(text: str, start: int, end: int, kind: str) -> list[Atom]:
    """兜底：单行一个原子；行正文超限（>MAX_LINE_CHARS）按 512 字符块切开。"""
    # 行正文长度（不含换行）
    body_end = end
    if end - start > 0 and text[end - 1] == "\n":
        body_end = end - 1
    body_len = body_end - start
    atoms: list[Atom] = []
    if body_len > MAX_LINE_CHARS:
        pos = start
        while pos < body_end:
            stop = min(body_end, pos + MAX_LINE_CHARS)
            atoms.append(
                Atom(text=text[pos:stop], weight=stop - pos, kind="chunk", start=pos, end=stop)
            )
            pos = stop
        # 行尾换行符单独成一个 atom（保留精确划分）
        if body_end < end:
            atoms.append(
                Atom(text=text[body_end:end], weight=end - body_end, kind="line", start=body_end, end=end)
            )
    else:
        atoms.append(Atom(text=text[start:end], weight=end - start, kind=kind, start=start, end=end))
    return atoms


def split_into_atoms(text: str) -> tuple[Atom, ...]:
    """把一段文本按信息原子切分，**精确覆盖** [0, len(text))，无缝隙无重叠。

    分段优先级：① 结构化块（Traceback / 文件树 / JSON-YAML）② 行组（key=value /
    表格行 / 路径行，逐行成原子）③ 兜底按行、超大行按 512 字符分块。
    末尾 ``assert sum(weight) == len(original_text)`` 保证划分无损。
    """
    n = len(text or "")
    if n == 0:
        return ()
    spans = _line_spans(text)
    atoms: list[Atom] = []
    i = 0
    total = len(spans)
    while i < total:
        start, end = spans[i]
        if _is_blank(text, start, end):
            atoms.append(Atom(text=text[start:end], weight=end - start, kind="blank", start=start, end=end))
            i += 1
            continue
        # ① 结构化块
        for det, kind in (
            (_traceback_block, "stack"),
            (_tree_block, "tree"),
            (_json_block, "json"),
        ):
            nxt = det(text, spans, i)
            if nxt is not None:
                b_start, _b_end = spans[i]
                end_at = spans[nxt - 1][1]
                atoms.append(
                    Atom(text=text[b_start:end_at], weight=end_at - b_start, kind=kind, start=b_start, end=end_at)
                )
                i = nxt
                break
        else:
            # ② 行组
            found = False
            for det, kind in (
                (_kv_group, "kv"),
                (_table_group, "table"),
                (_path_group, "path"),
            ):
                nxt = det(text, spans, i)
                if nxt is not None:
                    for j in range(i, nxt):
                        s, e = spans[j]
                        atoms.append(
                            Atom(text=text[s:e], weight=e - s, kind=kind, start=s, end=e)
                        )
                    i = nxt
                    found = True
                    break
            if not found:
                # ③ 兜底
                atoms.extend(_fallback_atoms(text, start, end, kind="line"))
                i += 1
    # 无损断言
    if sum(a.weight for a in atoms) != n:
        raise AssertionError(
            f"atom weight sum {sum(a.weight for a in atoms)} != len(text) {n}"
        )
    return tuple(atoms)


def atoms_to_dicts(atoms: tuple[Atom, ...], *, text_cap: int = 64) -> list[dict]:
    """把原子序列化进 WorkingSnapshot.current_atoms 的紧凑字典（不存全文）。

    只保留可重入计量信息（kind / weight / 戳记），避免 sidecar 被全文撑爆：
    ``text`` 截断到 ``text_cap`` 供人读，完整文本留在原消息里。
    """
    out: list[dict] = []
    for a in atoms:
        snippet = a.text if len(a.text) <= text_cap else a.text[:text_cap] + "…"
        out.append({"kind": a.kind, "weight": int(a.weight), "text": snippet})
    return out


def _message_texts(messages: list[dict]) -> list[str]:
    """抽取 messages 里可分段的内容文本（tool_result/text/user 正文）。"""
    texts: list[str] = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            texts.append(c)
        elif isinstance(c, list):
            for b in c:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_result":
                    txt = b.get("content")
                    if isinstance(txt, str):
                        texts.append(txt)
                elif "text" in b:
                    txt = b.get("text")
                    if isinstance(txt, str):
                        texts.append(txt)
    return texts


def atoms_histogram(messages: list[dict]) -> list[dict]:
    """对一段消息区间统计原子数量/种类，供 ``WorkingSnapshot.current_atoms``。

    只存聚合计量（kind→count），不存全文；含一行 ``_total`` 给总数与总权重，
    用于审计「Q 是按多少原子计权」。
    """
    counts: dict[str, int] = {}
    total_atoms = 0
    total_weight = 0
    for text in _message_texts(messages):
        for a in split_into_atoms(text):
            counts[a.kind] = counts.get(a.kind, 0) + 1
            total_atoms += 1
            total_weight += a.weight
    out: list[dict] = [{"kind": k, "count": c} for k, c in sorted(counts.items())]
    if total_atoms:
        out.append({"kind": "_total", "count": total_atoms, "weight": total_weight})
    return out
