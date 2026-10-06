"""多 agent 协调层的失败留痕不许停在 debug —— 本仓 debug 级等于没说。

事实（已在本目标内三次兑现）：产品从不配置 logging handler，只有 WARNING+ 会
落进 server.log。而 ``coord/`` 里的这些分支全是**状态操作失败**：
账本读不出、账本写不进、presence 变更失败、租约释放失败、worker 会话崩了。
停在 debug 的后果是：现场看得到"任务凭空消失/重复派发"，日志里一个字都没有。

本文件钉三处最有后果的（账本读、账本写、presence 变更），外加一条结构门：
这些句子的留痕级别不许再退回 debug。
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

import coord.file_store as fs

COORD_DIR = Path(fs.__file__).resolve().parent
MUST_BE_LOUD = [
    "coord read failed at",
    "coord write failed at",
    "presence mutate failed",
    "presence take failed",
    "presence read failed",
    "presence drop failed",
    "reconcile release lease failed",
    "reviewer release lease failed",
    "worker session failed",
    "coord config read failed at",
    "coord workers config read failed at",
]


def test_corrupt_ledger_is_loud(tmp_path: Path, caplog: pytest.LogFixture) -> None:
    """缺陷回归：账本坏掉（截断/非 UTF-8）必须留 warning，不能静默当"没有"。"""
    path = tmp_path / "tasks.json"
    path.write_bytes(b"{\"tasks\": [\xc3\x28")  # 非法 UTF-8 ⇒ UnicodeDecodeError
    with caplog.at_level(logging.DEBUG, logger="xeyo.coord.file"):
        got = fs._read_json(path)
    assert got is None, got
    hits = [r for r in caplog.records if "coord read failed" in r.getMessage()]
    assert hits, "读不出根本没留痕"
    assert all(r.levelno >= logging.WARNING for r in hits), [
        (r.levelname, r.getMessage()) for r in hits
    ]


def test_ledger_write_failure_is_loud(tmp_path: Path, caplog: pytest.LogFixture) -> None:
    bad = tmp_path / "blocked"
    bad.write_text("x", encoding="utf-8")  # 父目录是普通文件 ⇒ mkdir 必炸
    target = bad / "tasks.json"
    with caplog.at_level(logging.DEBUG, logger="xeyo.coord.file"):
        ok = fs._atomic_write_json(target, {"a": 1})
    assert ok is False
    hits = [r for r in caplog.records if "coord write failed" in r.getMessage()]
    assert hits, "写失败根本没留痕"
    assert all(r.levelno >= logging.WARNING for r in hits), [
        (r.levelname, r.getMessage()) for r in hits
    ]


def _levels_for(message: str) -> list[str]:
    """在 coord/*.py 里找 `message` 所在那条日志调用的级别名。"""
    out: list[str] = []
    for file in sorted(COORD_DIR.glob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.value and "_log" in ast.unparse(func.value)):
                continue
            if not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                continue
            if message in first.value:
                out.append(func.attr)
    return out


@pytest.mark.parametrize("message", MUST_BE_LOUD)
def test_failure_traces_are_warning_level(message: str) -> None:
    """结构门：这些"操作失败"句子的留痕级别只能是 warning/error。

    写死句子而不是扫全目录：全目录扫会把"降级中"这类刻意留 debug 的语句一起
    卷进来（那不是缺陷，是不想刷屏）。这里只钉"状态操作失败"这一族。
    """
    levels = _levels_for(message)
    assert levels, f"找不到句子：{message}"
    assert set(levels) <= {"warning", "error"}, (message, levels)


def test_json_helper_still_returns_none_for_absent(tmp_path: Path) -> None:
    """反向对照：文件不存在仍是"没有"，不许被这次改动变成报错。"""
    assert fs._read_json(tmp_path / "missing.json") is None
