"""挂起存储的 TTL 清扫不得在迭代字典时改字典。

事故形态（2026-10-03）：三个进程级挂起存储（提问 / 权限审批 / 计划确认）的
`_prune()` 都写成 `for rid in (generator over self._items.items())` 并在循环体里
`self._items.pop(rid)`——生成器是惰性求值的，第一次 pop 之后下一次 `next()`
就抛 `RuntimeError: dictionary changed size during iteration`。
`_prune()` 由 `create()` 调用 ⇒ **只要进程里存在一条已过期未决条目，
之后每一次审批/提问/计划确认都会抛错**，被编排层的宽 except 变成
`tool error: RuntimeError: …`，表现为"模型突然再也问不了人 / 写不了文件"。

同一文件里的 `GrantStore._prune` 早就是正确写法（先取列表再删），
本用例把三处对齐到它，并双向校：清扫必须真的删掉过期未决项，
**未过期与已决议项不得被删**（否则门只是不抛错而已）。
"""

from __future__ import annotations

import time

import pytest

from engine.plan import PlanEngine
from permissions.ask_store import PendingAskStore
from permissions.store import PendingPermissionStore


def _make_permission(store: PendingPermissionStore, turn_id: str) -> object:
    return store.create(
        session_id="s",
        turn_id=turn_id,
        tool_name="Write",
        tool_input={"path": "a.txt"},
        reason="needs_confirmation",
        prompt="allow?",
    )


def _fresh_pair(kind: str):
    """构造 (store, create, resolve)。

    `create(n)` 必须按序号给**不同 turn_id**：`PlanEngine.create` 的键是
    `request_id or turn_id`，同一 turn 里两次请求会落同一个键（每回合只挂一份
    计划，这是产品口径），fixture 若复用 turn_id 就测不到"两条独立条目"。
    """
    if kind == "ask":
        store = PendingAskStore(ttl_seconds=0.05)
        return (
            store,
            lambda n: store.create(session_id="s", turn_id=f"t{n}", question=f"q{n}", options=[]),
            lambda item: store.resolve_answer(item.request_id, "a", actor="test"),
        )
    if kind == "permission":
        store = PendingPermissionStore(ttl_seconds=0.05)
        return (
            store,
            lambda n: _make_permission(store, f"t{n}"),
            lambda item: store.resolve(item.request_id, True, actor="test"),
        )
    store = PlanEngine(ttl_seconds=0.05)
    return (
        store,
        lambda n: store.create(session_id="s", turn_id=f"t{n}", plan=f"p{n}"),
        lambda item: store.resolve(item.request_id, True, actor="test"),
    )


@pytest.mark.parametrize("kind", ["ask", "permission", "plan"])
def test_create_after_an_expired_pending_does_not_raise(kind: str) -> None:
    store, create, _resolve = _fresh_pair(kind)
    create(0)
    time.sleep(0.12)  # 让第一条过期且未决
    second = create(1)  # 修复前这里抛 RuntimeError: dictionary changed size during iteration
    assert second is not None


@pytest.mark.parametrize("kind", ["ask", "permission", "plan"])
def test_prune_removes_expired_but_keeps_live_and_resolved(kind: str) -> None:
    store, create, resolve = _fresh_pair(kind)
    expired = create(0)
    time.sleep(0.12)
    live = create(1)           # 这次 create 会清扫：expired 应被删，live 留下
    ids = set(store._items)
    assert expired.request_id not in ids, "过期未决项必须被清掉，否则门是装饰"
    assert live.request_id in ids, "未过期项不得被清"

    # 已决议的条目即使过期也不该被这条清扫误删（口径：只清未决）
    resolved_item = create(2)
    resolve(resolved_item)
    time.sleep(0.12)
    store._prune()
    assert resolved_item.request_id in store._items, (
        "已决议条目不该被 TTL 清扫按未决口径误删"
    )
