"""canon —— 规范化：把任意模型可见文本压成"可逐字节比对"的稳定形态。

三层侦测全部依赖同一件事：**同一份代码必须产出同一串字节**。所有易变量
（会话 id、工具调用 id、UUID、时间戳、绝对路径、临时目录）都在这里被一次性
抹平，否则 golden 比对会被噪声打红，侦测器就失去意义。

设计约束：
- 只做**确定性**替换，不做任何语义改写（改了就测不出真变化）。
- 不确定的一律不改，宁可留噪声也不掩盖真实差异。
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

#: changedetect/ → evals/ → python/ → <repo root>
REPO_ROOT = Path(__file__).resolve().parents[3]

#: 易变 token → 占位符。顺序敏感（先长后短）。
_VOLATILE: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"xeyo_env_[0-9a-fA-F]{6,}"), "xeyo_env_<ID>"),
    (re.compile(r"\bcall_[0-9a-fA-F]{6,}\b"), "call_<ID>"),
    (
        re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
        "<UUID>",
    ),
    (
        re.compile(
            r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
        ),
        "<TS>",
    ),
    (re.compile(r"\bsession[_-][0-9a-zA-Z]{6,}\b"), "session_<ID>"),
)


def _path_variants(root: Path) -> list[str]:
    """同一根目录在 Windows 上的多种书写形式（正/反斜杠、大小写）。"""
    raw = str(root)
    out = {raw, raw.replace("\\", "/"), raw.replace("/", "\\")}
    if os.name == "nt":
        out |= {v.lower() for v in list(out)}
    return sorted(out, key=len, reverse=True)


def _path_rules() -> list[tuple[str, str]]:
    rules: list[tuple[str, str]] = []
    for root, placeholder in (
        (REPO_ROOT, "<REPO>"),
        (Path.home(), "<HOME>"),
        (Path(os.environ.get("TEMP", "/tmp")), "<TMP>"),
    ):
        try:
            for v in _path_variants(root):
                if v and len(v) > 3:
                    rules.append((v, placeholder))
        except Exception:  # noqa: BLE001 — 路径不可解析时静默跳过
            continue
    return rules


_PATH_RULES: list[tuple[str, str]] = _path_rules()

#: 运行时追加的字面量替换（按调用顺序；前驱的"更具体"项优先）。
_EXTRA_RULES: list[tuple[str, str]] = []


def register_literal(actual: str, placeholder: str) -> None:
    """登记一次性字面量替换（用于随机路径、动态 id 等）。重复调用按调用顺序。

    例：canon.register_literal(str(tmp_dir), "<TMP>")
    """
    if not actual or actual == placeholder:
        return
    # 放在最前——更具体的先于更一般的
    _EXTRA_RULES.insert(0, (actual, placeholder))


def reset_extras() -> None:
    """清空运行时登记（仅测试/重置时使用）。"""
    _EXTRA_RULES.clear()


def scrub(text: str) -> str:
    """抹平易变量。确定性、幂等（占位符本身不会被再次替换）。"""
    if not text:
        return text
    out = text
    for rule_list in (_EXTRA_RULES, _PATH_RULES):
        for needle, placeholder in rule_list:
            out = out.replace(needle, placeholder)
    for pat, placeholder in _VOLATILE:
        out = pat.sub(placeholder, out)
    return out


def scrub_obj(obj: Any) -> Any:
    """递归对结构里的字符串做 scrub。放在 json.dumps 之前，免得路径里
    的单反斜杠被 json 自动转义后糊掉我们的字面量替换规则。"""
    if isinstance(obj, str):
        return scrub(obj)
    if isinstance(obj, dict):
        return {k: scrub_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub_obj(v) for v in obj]
    return obj


def canon_text(text: str) -> str:
    """文本规范化：CRLF→LF、抹易变量、去行尾空白、统一收尾单换行。"""
    if not text:
        return ""
    body = scrub(text.replace("\r\n", "\n").replace("\r", "\n"))
    body = "\n".join(line.rstrip() for line in body.split("\n"))
    return body.rstrip("\n") + "\n"


def canon_obj(obj: Any) -> str:
    """对象规范化：先递归 scrub 字符串，再稳定 JSON，最后再过一遍 canon_text。"""
    cleaned = scrub_obj(obj)
    raw = json.dumps(cleaned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return canon_text(raw)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def digest_of(text: str, *, n: int = 16) -> str:
    return sha(text)[:n]


def char_delta(before: str, after: str) -> tuple[int, int]:
    """返回 (净增字符, 净删字符)，按字符多重集差分，不计位置。"""
    from collections import Counter

    cb, ca = Counter(before), Counter(after)
    added = sum((ca - cb).values())
    removed = sum((cb - ca).values())
    return added, removed


def first_diff_line(before: str, after: str) -> int | None:
    """首个不同行的 1-based 行号；完全相同返回 None。"""
    bl, al = before.split("\n"), after.split("\n")
    for i, (b, a) in enumerate(zip(bl, al), start=1):
        if b != a:
            return i
    if len(bl) != len(al):
        return min(len(bl), len(al)) + 1
    return None


def unified(before: str, after: str, name: str, *, context: int = 2) -> str:
    """人类可读的 unified diff。"""
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{name}",
            tofile=f"b/{name}",
            n=context,
        )
    )


def shorten(text: str, limit: int = 400) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [截断，共 {len(text)} 字符]"


def safe_name(name: str) -> str:
    """artifact 名 → 文件名（可进 git、可 diff）。"""
    return re.sub(r"[^0-9A-Za-z._\u4e00-\u9fff-]+", "__", name).strip("_") or "unnamed"


def now_iso() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")
