"""History Index 回归：append-only 行号稳定 + locator 真的可执行 + 不新增 parser。

这一层的存在理由就是"被剪内容仍找得回"，所以它的测试必须是**真回读**，
不是格式检查。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from memory.wsc2 import history as H
from memory.wsc2.events import build_events
from memory.wsc2.projector import token_len

pytest.importorskip("synaptic")

from tests.wsc2.test_state_reducer_v0 import result, use, user  # noqa: E402

SESSION_ROW = 7


def _events(msgs):
    return build_events(list(msgs))


def _msgs():
    return [user("把 timeout 从 30 改成 60"),
            use("c1", "Read", file_path="srv/conf.py"),
            result("c1", "TIMEOUT = 30"),
            use("c2", "Edit", file_path="srv/conf.py", old_string="TIMEOUT = 30",
                new_string="TIMEOUT = 60"),
            result("c2", "ok"),
            use("c3", "Bash", command="pytest -q"),
            result("c3", "1 failed", is_error=True),
            user("再跑一次测试确认"),
            use("c4", "Bash", command="pytest -q"),
            result("c4", "42 passed")]


def test_page_lines_are_append_only_under_a_longer_prefix() -> None:
    """行号漂移 = locator 失效。事件只追加 ⇒ 前缀页必须是长页的逐字前缀。"""
    ev = _events(_msgs())
    small = H.build_prefix(ev, 6)
    big = H.build_prefix(ev, 10)
    for ns in H.NAMESPACES:
        s = small.page_text(ns)
        b = big.page_text(ns)
        assert b.startswith(s), f"{ns} 页不是前缀稳定的 ⇒ locator 会漂移"
        assert all(r.line == i for i, r in enumerate(small.pages[ns], start=1))


def test_every_locator_resolves_after_pages_are_written(tmp_path) -> None:
    """可执行性硬不变量：每条 locator 都必须真能回读出它那行（D1 的教训）。"""
    ev = _events(_msgs())
    ix = H.index_events(ev)
    pages = H.write_pages(ix, tmp_path / "idx")
    checked = 0
    for ns in H.NAMESPACES:
        if ns == "root" or ns not in pages:
            continue
        for rec in ix.pages[ns]:
            got = H.resolve_line(pages[ns], rec.line)
            assert got == rec.page_line(), f"{ns} 第 {rec.line} 行回读不一致"
            assert rec.event_id in got
            checked += 1
    assert checked == ix.total_records, "每条记录都必须被回读过，不许抽样漏类"
    assert checked >= 8, "样本太小，等于没测"


def test_raw_event_locator_resolves_into_the_session_rows(tmp_path) -> None:
    """第二级 locator 指向 Event Store 行号：必须是**真实存在**的行。"""
    msgs = _msgs()
    s = tmp_path / "sess.jsonl"
    import json

    s.write_text("\n".join(json.dumps(m, ensure_ascii=False) for m in msgs) + "\n",
                 encoding="utf-8")
    ix = H.index_events(_events(msgs))
    lines = s.read_text(encoding="utf-8").splitlines()
    for ns in H.NAMESPACES:
        for rec in ix.pages[ns]:
            got = H.resolve_line(str(s), rec.row + 1)
            assert got is not None, f"row={rec.row} 越界 ⇒ locator 指向不存在的原文"
            assert got == lines[rec.row]


def test_locators_use_only_read_and_never_a_new_scheme() -> None:
    """禁止出现"生产没有 parser 的 handle"：所有定位符都得是普通 Read(...)。"""
    ix = H.index_events(_events(_msgs()))
    for ns in H.NAMESPACES:
        for rec in ix.pages[ns]:
            assert rec.read_locator(f"idx/{ns}.md").startswith("Read('idx/")
            assert rec.raw_locator("sess.jsonl").startswith("Read('sess.jsonl'")


def test_resident_cost_is_the_root_only_and_stays_tiny(tmp_path) -> None:
    """索引之所以省钱，全靠"只有 root 常驻"。root 一旦长成分桶明细就白做。"""
    ix = H.index_events(_events(_msgs()))
    root = ix.root_lines("idx")
    assert token_len(root) < 120, f"root 常驻成本 {token_len(root)} tok，太大"
    assert "row=" not in root, "root 里不许出现事件级明细"
    assert ix.total_records == ix.stats()["total"]


def test_index_has_no_transport_vocabulary() -> None:
    src = (Path(__file__).resolve().parents[2] / "memory" / "wsc2" /
           "history.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    for w in ("theta", "price_ratio", "prefix_hit", "cache", "frozen_head",
              "keep_tail", "compact_cursor"):
        assert w not in body, f"历史索引读到了 transport 词汇：{w}"


def test_empty_namespace_is_not_announced_in_root() -> None:
    msgs = [user("只有一个问题"), result("nope", "x")]
    ix = H.index_events(_events(msgs))
    root = ix.root_lines("idx")
    assert "errors" not in root or ix.lines["errors"] == 0
