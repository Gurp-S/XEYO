"""长文件的结构视图：读之前先给"里面有什么、在第几行"。

动机（agent 自报的摩擦）：无范围整读一个 1145 行的文件，规模只有在**读完之后**
的 ``read_observation.view_total_lines`` 里才出现；读法（整读 / 定向 / 先看结构）
本该在读之前就能决定。

触发（唯一口子，见 ``file_read_tool`` 的无范围分支）：
``symbol`` 未给 ∧ ``offset`` 未给 ∧ ``limit`` 未给 ∧ 总行数 ≥ 阈值
（env ``XEYO_READ_STRUCTURE_MIN_LINES``，默认 600，``0`` = 关）。

产出是**工具合同事实**，不是建议：正文可由 offset/limit 或 symbol= 取回
（与既有 MAX_SIZE_BYTES 报错文案同性质）。代码文件的条目走
``codeindex.symbols.outline``，与 ``symbol=`` 解析**同源**（一份符号事实，不新增
第二套真相）；非代码回退 markdown 标题 / json 顶层键 / toml 段。

边界：本模块只做"条目列表"，不返回正文、不读第二次盘（``outline`` 自带缓存）、
任何异常回退到"只有表头"的最小结构视图。
"""

from __future__ import annotations

import os
import re

ENV_MIN_LINES = "XEYO_READ_STRUCTURE_MIN_LINES"
DEFAULT_MIN_LINES = 600

_CODE_EXTS = frozenset(
    {"py", "pyi", "ts", "tsx", "js", "jsx", "mjs", "cjs", "rs", "go", "java", "rb"}
)
_MAX_ENTRIES = 200

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_TOML_SECTION = re.compile(r"^\s*\[([^\]\[]+)\]\s*$")
_JSON_KEY = re.compile(r'^\s{1,4}"([^"]+)"\s*:')


def min_lines() -> int:
    """阈值；非法/空 env 回退默认，``<=0`` 表示关闭本视图。"""
    raw = os.environ.get(ENV_MIN_LINES, "").strip()
    if not raw:
        return DEFAULT_MIN_LINES
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_MIN_LINES


def enabled(total_lines: int) -> bool:
    limit = min_lines()
    return limit > 0 and int(total_lines or 0) >= limit


def render(full_path: str, all_lines: list[str], ext: str = "") -> str:
    """结构视图正文；任何异常回退最小视图（只报总行数）。"""
    total = len(all_lines)
    try:
        entries = (
            _code_entries(str(full_path))
            if (ext or "").lower() in _CODE_EXTS
            else _text_entries(all_lines, (ext or "").lower())
        )
    except Exception:  # noqa: BLE001 — 结构视图失败不许挡读路径
        entries = []
    head = f"structure view: {total} lines, {len(entries)} entries"
    body = [f"{line_no}  {label}" for line_no, label in entries[:_MAX_ENTRIES]]
    if len(entries) > _MAX_ENTRIES:
        body.append(f"… +{len(entries) - _MAX_ENTRIES} more entries")
    body.append("(pass offset/limit or symbol= to read the body)")
    return "\n".join([head, *body])


def _code_entries(full_path: str) -> list[tuple[int, str]]:
    from codeindex.symbols import outline

    out: list[tuple[int, str]] = []
    for sym in outline(full_path):
        start = int(getattr(sym, "start", 0) or 0)
        if start <= 0:
            continue
        kind = str(getattr(sym, "kind", "") or "symbol")
        out.append((start, f"{kind} {sym.name}"))
    return out


def _text_entries(all_lines: list[str], ext: str) -> list[tuple[int, str]]:
    if ext == "json":
        pattern, label = _JSON_KEY, lambda m: m.group(1)
    elif ext == "toml":
        pattern, label = _TOML_SECTION, lambda m: m.group(1)
    else:
        pattern, label = _MD_HEADING, lambda m: m.group(2)
    seen: set[str] = set()
    out: list[tuple[int, str]] = []
    for index, line in enumerate(all_lines, 1):
        match = pattern.match(line)
        if match is None:
            continue
        text = label(match)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append((index, text))
    return out


__all__ = ["DEFAULT_MIN_LINES", "ENV_MIN_LINES", "enabled", "min_lines", "render"]
