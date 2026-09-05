from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from server import app as app_mod
from server.app import app
from tests.test_rewind_service import _build_session


def _client() -> TestClient:
    return TestClient(app)


def test_rollback_preview_is_disabled_when_opted_out(monkeypatch) -> None:
    monkeypatch.setenv("XEYO_REWIND_ENABLED", "0")
    response = _client().post(
        "/v1/sessions/api-disabled/rollback/preview",
        json={"target_message_id": "msg-1", "edited_text": "edited"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "rewind_disabled"


def test_rollback_api_preview_and_execute(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XEYO_REWIND_ENABLED", "1")
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    service, target, ids = _build_session(tmp_path)
    # SessionPool 原私有属性 _cwd 已改名为 _ui_cwd（公共入口 set_cwd）。
    app_mod._pool.set_cwd(str(target.parent))

    client = _client()
    preview = client.post(
        f"/v1/sessions/{service.session_id}/rollback/preview",
        json={
            "target_message_id": ids["target_message_id"],
            "edited_text": "new prompt",
        },
    )
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["ok"] is True
    plan = payload["plan"]
    assert plan["status"] == "approval_required"
    assert target.read_text(encoding="utf-8") == "after\n"

    missing_confirmation = client.post(
        f"/v1/sessions/{service.session_id}/rollback/execute",
        json={
            "plan_id": plan["plan_id"],
            "plan_hash": plan["plan_hash"],
            "idempotency_key": "api-confirmation-required",
            "confirmed": False,
        },
    )
    assert missing_confirmation.status_code == 400
    assert missing_confirmation.json()["error"]["type"] == "approval_required"

    execute = client.post(
        f"/v1/sessions/{service.session_id}/rollback/execute",
        json={
            "plan_id": plan["plan_id"],
            "plan_hash": plan["plan_hash"],
            "idempotency_key": "api-confirmation-required",
            "confirmed": True,
        },
    )
    assert execute.status_code == 200
    assert execute.json()["job"]["status"] == "committed"
    assert target.read_text(encoding="utf-8") == "before\n"

    status = client.get(
        f"/v1/sessions/{service.session_id}/rollback/status/{execute.json()['job']['job_id']}"
    )
    assert status.status_code == 200
    assert status.json()["job"]["status"] == "committed"


def test_rewind_v3_route_returns_result(monkeypatch, tmp_path: Path) -> None:
    """回归：POST /v1/sessions/{sid}/rewind 成功路径必须 return result。

    曾因漏 return 落入 ``raise AssertionError("unreachable")``，前端弹窗收到
    500「unreachable」，Restore 永远到不了「回溯完成」。
    """
    monkeypatch.setenv("XEYO_REWIND_ENABLED", "1")
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    service, target, ids = _build_session(tmp_path)
    app_mod._pool.set_cwd(str(target.parent))

    client = _client()
    resp = client.post(
        f"/v1/sessions/{service.session_id}/rewind",
        json={
            "mode": "continue",
            "target_message_id": ids["target_message_id"],
            "edited_text": "edited copy",
            "confirmed": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert str(body.get("rewind_id") or "")
    assert body.get("transcript_committed") is True
    assert body.get("mode") == "continue"
