"""`calibration_events.action` 的语义门：它是**这一枪走了哪条发射路径**的标签，
不是折叠计数器，也不是折叠评估计数器。

起因（2026-09-30 重测，`_wsc_out/_action_recall.py`）：文档旧句"折叠标签召回率 ~2%"作废。
实测 347 行 `action=C2` 的每一行都在同会话 120 秒内配到一条 `c2_events` 游标行
（**347/347**）⇒ 标签与 C2 发射面**同步**，没有坏。真正要钉的是它的语义边界：

- `c2_events` 记"这一枪发了 C2 面"（3,698 行 / 105 会话，起于 2026-08-19），
- `fold_events` 记"这一次折叠判定（放行与拒绝都记）"，且**只有带 `account` 的判定才落行**
  （`_note_fold_attempt` 见 `account` 为空直接 return），账本起于 2026-09-22
  ⇒ 105 个会话里只有 8 个有行。两者在同一会话内几乎相等（152/175、107/107、9/10、6/6…），
  差的就是"发了 C2 面但那次判定没带账目"的枪。

⇒ 数折叠走 `c2_events`，数判定走 `fold_events`，**都不许走 `action`**：
`action` 会把"扩展被拒"记成 `keep`（下面的门②），也会把没带 account 的 C2 发射
记成 C2 却没有折叠行（门①）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("synaptic")

from memory.working import WorkingSnapshot  # noqa: E402


def _msgs(n: int = 8, size: int = 900) -> list[dict]:
    return [{"role": "user", "content": f"m{i}-" + "x" * size} for i in range(n)]


def _working(cursor: int, sid: str = "s_action_semantics") -> WorkingSnapshot:
    w = WorkingSnapshot()
    w.session_id = sid
    w.compact_cursor = cursor
    w.c1_frozen_until = cursor
    w.turns_since_c2 = 999          # 不让冷却门挡住的实验条件
    if cursor > 0:
        w.c2_summary_text = "prior summary"
    return w


def _emit(monkeypatch, mem_switch, w, *, extended, tmp_path=None):
    """走 v61 实验通道的生产投影出口：只桩 `decide` 与 `try_extend_c2`。

    `decide` 在函数内条件 import ⇒ 必须 patch 源模块属性才打得到。
    返回是否真的走到了扩展门（`calls`）——没有它，两臂的"keep/C2"可能只是绕过了这道门。
    """
    import memory.simulator.decision as decision
    from memory import runtime as rt

    mem_switch(XEYO_L5="v61")
    monkeypatch.setenv("XEYO_WSC", "0")
    if tmp_path is not None:
        monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
    monkeypatch.setattr(decision, "decide",
                        lambda *a, **k: SimpleNamespace(a_star="C2", hardtop=False,
                                                        branches=None))
    calls: list[int] = []

    def _ext(working, messages, new_cursor, params, force=False, account=None, cwd=None):
        calls.append(int(new_cursor))
        return extended

    monkeypatch.setattr(rt, "try_extend_c2", _ext)
    rt.project_for_model(_msgs(), w, context_limit=None, cwd=".")
    return calls


def test_extension_success_labels_c2_but_may_write_no_fold_row(monkeypatch, mem_switch,
                                                               tmp_path) -> None:
    """门①：扩展放行 ⇒ 标签 C2、`c2_events` 落一行，而 `fold_events` **可以一行都没有**。

    这正是账本里 84 行"有 C2 标签、找不到批准折叠"的成因 ⇒ 谁把 `action` 当折叠计数器，
    谁就会在这一枪上多算；把它当发射路径标签才是对的。
    """
    from usage.ledger import read_c2_events
    from usage.pairing import read_fold_events

    w = _working(cursor=1)
    calls = _emit(monkeypatch, mem_switch, w, extended=True, tmp_path=tmp_path)
    assert calls, "根本没走到扩展门 ⇒ 这条门是装饰"
    assert w.last_action == "C2"
    assert read_c2_events(), "C2 发射没落 c2_events ⇒ 这条门没在被量的路径上"
    assert read_fold_events(tmp_path) == [], "桩掉的判定不该自己造折叠行"


def test_extension_refusal_labels_keep_though_an_assessment_happened(monkeypatch,
                                                                    mem_switch,
                                                                    tmp_path) -> None:
    """门②：扩展被拒 ⇒ 标签退回 `keep`。⇒ `action` 里**看不到被 θ 挡住的评估**，
    拒绝次数只能从 `fold_events` 取。"""
    w = _working(cursor=1)
    calls = _emit(monkeypatch, mem_switch, w, extended=False, tmp_path=tmp_path)
    assert calls, "两臂必须走同一道扩展门，否则 keep 只是绕过它"
    assert w.last_action == "keep"
    assert w.compact_cursor == 1, "被拒却不该动游标"


def test_label_survives_the_snapshot_roundtrip() -> None:
    """门③：`last_action` 随快照落盘并回读 ⇒ 它是**跨枪携带的状态**，
    下一枪若不重新决定就会把同一标签再发一次（"事件标签"不该有这性质）。"""
    from memory.working import _from_dict, _to_dict

    w = _working(cursor=3)
    w.last_action = "C2"
    blob = _to_dict(w)
    assert str(blob.get("last_action")) == "C2", "标签没进快照，本门失效"
    assert _from_dict(blob, w.session_id).last_action == "C2"


def test_blank_label_falls_back_to_keep(monkeypatch, tmp_path) -> None:
    """生产者→账本的唯一转换点：标签为空 ⇒ 记 `keep`（默认口径不许漂）。"""
    from memory.observe import observe_shot
    from usage.ledger import read_calibration_events

    monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
    w = WorkingSnapshot(session_id="s_blank")
    assert not w.last_action
    observe_shot(w, _msgs(1), hit=1, miss=1, out=1, context_tokens=2, turn=1)
    assert read_calibration_events()[0]["action"] == "keep"
