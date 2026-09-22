"""折叠判定的三条准入（2026-09-20 事故回归）。

事故现场（会话 sess_mu9ooeri_tt8cxa）：6 次折叠**全部**落在
``Approval unavailable: the request timed out without a decision and was
treated as rejected.``（91 字节）这类**模板回执**上，折叠行还不带被折内容的
任何痕迹 ⇒ 我既看不出"审批又超时了"，也看不出"命令到底跑没跑"，于是反复重试，
再被 loop_breaker 以"连续同结果"拒执行，彻底无路。

三条准入（本文件逐条锁定）：
1. 模板回执（审批超时 / 权限拒绝 / 工具异常 / 被中止）不参与折叠——它们是引擎与
   宿主写给模型的**当下事实**，不是工具观测的证据；
2. 收益门：折叠行（含事实头）必须真的比原文短；
3. 可见性前提：同内容旧副本必须仍在投影可见面内（否则折掉的是唯一一份）。
"""

from __future__ import annotations

from engine.repeat_fold import IdenticalResultFold

#: 远长于折叠行（含事实头）的正文，用于"值得折"的场景。
_LONG = "line-1\n" * 40 + "tail\n"

_RECEIPT = (
    "Approval unavailable: the request timed out without a decision "
    "and was treated as rejected."
)


def test_template_receipt_never_folds(monkeypatch) -> None:
    """回归：模板回执重复多少次都必须保持原文可见。"""
    monkeypatch.delenv("XEYO_LOOP_LEDGER", raising=False)
    monkeypatch.setenv("XEYO_FOLD_EQUIV_AT", "2")
    f = IdenticalResultFold()
    for index in range(6):
        text, folded = f.process("Bash", {"command": f"cmd-{index}"}, _RECEIPT)
        assert not folded, f"第 {index + 1} 次模板回执被折叠了"
        assert text == _RECEIPT
    # 同签名重复同样不折（逐字节档也不吃回执）
    for _ in range(5):
        text, folded = f.process("Bash", {"command": "same"}, _RECEIPT)
        assert not folded and text == _RECEIPT


def test_permission_receipt_never_folds(monkeypatch) -> None:
    monkeypatch.delenv("XEYO_LOOP_LEDGER", raising=False)
    monkeypatch.setenv("XEYO_FOLD_EQUIV_AT", "2")
    f = IdenticalResultFold()
    for index in range(4):
        receipt = f"Permission denied: {index}"
        text, folded = f.process("Bash", {"command": f"c{index}"}, receipt)
        assert not folded and text == receipt


def test_fold_line_never_grows_the_result(monkeypatch) -> None:
    """收益门：把 "ok" 换成一行折叠提示是"更长且更少信息"，故不折。"""
    monkeypatch.delenv("XEYO_LOOP_LEDGER", raising=False)
    monkeypatch.setenv("XEYO_FOLD_EQUIV_AT", "2")
    f = IdenticalResultFold()
    for index in range(5):
        text, folded = f.process("Bash", {"command": f"c{index}"}, "ok")
        assert not folded and text == "ok"


def test_same_content_different_args_folds_when_worth_it(monkeypatch) -> None:
    """等价档原意保留：同工具跨签名同内容、且折了真省体积 → 第 3 次折叠。"""
    monkeypatch.delenv("XEYO_LOOP_LEDGER", raising=False)
    f = IdenticalResultFold()
    t1, folded1 = f.process("Grep", {"pattern": "a"}, _LONG)
    assert not folded1 and t1 == _LONG
    _, folded2 = f.process("Grep", {"pattern": "b"}, _LONG)
    assert not folded2  # 第 2 次仍原文
    t3, folded3 = f.process("Grep", {"pattern": "c"}, _LONG)
    assert folded3 and "等价结果" in t3
    assert len(t3) < len(_LONG)


def test_fold_line_carries_structure_facts(monkeypatch) -> None:
    """折叠行必须留下被折内容的首行 / 行数 / 字节数（否则信息净损）。"""
    monkeypatch.delenv("XEYO_LOOP_LEDGER", raising=False)
    monkeypatch.setenv("XEYO_FOLD_EQUIV_AT", "2")
    f = IdenticalResultFold()
    f.process("Grep", {"pattern": "a"}, _LONG)
    folded_text, folded = f.process("Grep", {"pattern": "b"}, _LONG)
    assert folded
    assert "line-1" in folded_text  # 首行
    assert "41 行" in folded_text  # 行数
    assert f"{len(_LONG.strip())} 字节" in folded_text  # 字节数


def test_fold_skipped_when_earlier_copy_rolled_out(monkeypatch) -> None:
    """压缩/冻结把旧副本移出可见面后不许再折（否则唯一副本被吃掉）。"""
    monkeypatch.delenv("XEYO_LOOP_LEDGER", raising=False)
    monkeypatch.setenv("XEYO_FOLD_EQUIV_AT", "2")
    f = IdenticalResultFold()
    f.process("Grep", {"pattern": "a"}, _LONG, msg_index=5, visible_from=0)
    text, folded = f.process(
        "Grep", {"pattern": "b"}, _LONG, msg_index=60, visible_from=40
    )
    assert not folded and text == _LONG


def test_fold_allowed_when_earlier_copy_still_visible(monkeypatch) -> None:
    """对照：旧副本仍在可见面内（下标 ≥ 可见起点）时照常折叠。"""
    monkeypatch.delenv("XEYO_LOOP_LEDGER", raising=False)
    monkeypatch.setenv("XEYO_FOLD_EQUIV_AT", "2")
    f = IdenticalResultFold()
    f.process("Grep", {"pattern": "a"}, _LONG, msg_index=50, visible_from=0)
    _, folded = f.process(
        "Grep", {"pattern": "b"}, _LONG, msg_index=60, visible_from=40
    )
    assert folded


def test_byte_level_still_takes_priority(monkeypatch) -> None:
    """逐字节档（同签名相邻相同）文案不变、优先级不变。"""
    monkeypatch.delenv("XEYO_LOOP_LEDGER", raising=False)
    f = IdenticalResultFold()
    for _ in range(3):
        text, folded = f.process("Grep", {"pattern": "a"}, _LONG)
    assert folded and "同一签名" in text
