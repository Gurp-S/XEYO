"""裁决回执要能说出"为什么没生效"。

此前 `/v1/permission/resolve` 与 `/v1/ask/resolve` 只回 `{ok: false}`，GUI 于是统一
toast「提交审批结果失败，请重试」。但 store.resolve 返回 False 只有两种原因
（permissions/store.py::resolve、permissions/ask_store.py::resolve_answer 同一形状：
内存 dict + item.resolved）：

- `no_such_request`：挂起项不在内存里 —— 最常见是服务重启清了它，重试永远修不好；
- `already_resolved`：已经被别的表面答过（远程/微信，或用户双击）—— 这**不是失败**，
  裁决其实生效了，界面却把它报成失败会让人以为没批而再点一次。

两种都要在 HTTP 上分得开，界面才能说实话。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine.workspace_context import WorkspaceContext, set_workspace_context
import permissions.ask_store as ask_mod
import permissions.store as perm_store
from permissions.ask_store import PendingAskStore
from server.app import app


@pytest.fixture(autouse=True)
def _isolate_client(tmp_path):
    set_workspace_context(WorkspaceContext(session_id="s-rc", cwd=str(tmp_path)))
    yield
    set_workspace_context(None)


def _pending_permission() -> str:
    store = perm_store.PendingPermissionStore(ttl_seconds=60)
    perm_store._default_store = store
    item = store.create(
        session_id="s-rc",
        turn_id="t1",
        tool_name="Bash",
        tool_input={"command": "echo hi"},
        reason="needs_confirmation",
        prompt="Allow?",
        matched_rule="bash_policy_ask",
    )
    return item.request_id


def _resolve(client: TestClient, request_id: str) -> dict:
    r = client.post(
        "/v1/permission/resolve",
        json={"request_id": request_id, "approved": True},
    )
    assert r.status_code == 200
    return r.json()


def test_successful_decision_carries_no_reason() -> None:
    client = TestClient(app)
    rid = _pending_permission()
    body = _resolve(client, rid)
    assert body["ok"] is True
    assert "reason" not in body, "生效时不得带失败原因"


def test_double_submit_says_it_was_already_resolved() -> None:
    """第二次点击：ok=false，但原因必须是"已经答过"，不是"提交失败"。"""
    client = TestClient(app)
    rid = _pending_permission()
    assert _resolve(client, rid)["ok"] is True
    second = _resolve(client, rid)
    assert second["ok"] is False
    assert second["reason"] == "already_resolved"


def test_unknown_handle_says_no_such_request() -> None:
    """服务重启把内存挂起项清了：重试无意义，界面必须说得出口。"""
    client = TestClient(app)
    perm_store._default_store = perm_store.PendingPermissionStore(ttl_seconds=60)
    body = _resolve(client, "call_does_not_exist")
    assert body["ok"] is False
    assert body["reason"] == "no_such_request"


def test_ask_endpoint_uses_the_same_reasons(tmp_path) -> None:
    client = TestClient(app)
    store = PendingAskStore()
    ask_mod._default_ask_store = store
    item = store.create(session_id="s-rc", turn_id="t1", question="选哪个？", options=["a", "b"])

    def post(answer: str) -> dict:
        r = client.post("/v1/ask/resolve", json={"request_id": item.request_id, "answer": answer})
        assert r.status_code == 200
        return r.json()

    assert post("a") == {"ok": True, "request_id": item.request_id}
    again = post("b")
    assert again["ok"] is False and again["reason"] == "already_resolved"
    r = client.post("/v1/ask/resolve", json={"request_id": "nope_42", "answer": "a"})
    body = r.json()
    assert body["ok"] is False and body["reason"] == "no_such_request"


def test_miss_reason_stays_empty_when_the_store_cannot_be_read() -> None:
    """读不出挂起项时不得猜原因：空串让界面退回通用措辞，比编一个更接近事实。"""

    class Boom:
        def get(self, _rid):
            raise RuntimeError("store down")

    from server.routers.control import _resolve_miss_reason

    assert _resolve_miss_reason(Boom(), "x") == ""
