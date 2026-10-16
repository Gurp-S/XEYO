"""Offline observation probes; assert CURRENT defects, not desired regressions.

Run from repo root: py -3.11 docs/input-chain-audit-2026-10-07/reproduce.py
All writable runtime state lives in TemporaryDirectory; no provider calls.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))
observations = []


def note(name, **facts):
    observations.append({"probe": name, **facts})


async def backend_probes(work):
    from server import inbox_registry as inbox
    from server import synthetic_round as synthetic
    from server.deps import _pool
    from server.app import app
    from engine import t_now_steer
    import httpx

    # Selected steer must preserve the two siblings. It currently discards them.
    reg = inbox.InboxRegistry()
    with patch.object(inbox, "_registry", reg):
        items = [reg.enqueue("select-steer", t, message_id=t) for t in ("A", "B", "C")]
        from server.routers.sessions import session_inbox_item_steer
        result = await session_inbox_item_steer("select-steer", items[1].queue_id)
        remaining = [i["text"] for i in reg.snapshot("select-steer")["items"]]
        assert remaining == ["B"], remaining
        note("selected_steer_drops_siblings", accepted=result["ok"], before=["A", "B", "C"], after=remaining)
    t_now_steer.clear("select-steer")

    # The selected-item route moves ownership to steer but never finishes its
    # inbox inflight receipt when steer actually lands at a sampling boundary.
    reg = inbox.InboxRegistry()
    sid = "steer-boundary-receipt"
    with patch.object(inbox, "_registry", reg):
        item = reg.enqueue(sid, "boundary task", message_id="boundary-user")
        await session_inbox_item_steer(sid, item.queue_id)
        class Store:
            items = []
            def append(self, message):
                self.items.append(message)
        store = Store()
        landed = t_now_steer.deliver(sid, store)
        # Same ordered boundary calls as query_loop (inbox boundary is off).
        from engine.t_now_inbox import deliver_queued_users
        with patch.dict(os.environ, {"XEYO_INBOX_BOUNDARY": "0"}):
            assert deliver_queued_users(sid, store) == []
        await reg.on_turn_settled(sid, "succeeded", "", "original-user")
        receipt = reg.snapshot(sid)["items"]
        assert len(landed) == 1 and receipt[0]["state"] == "delivering"
        assert reg.acknowledge_delivered(sid, [item.queue_id]) == 0
        note("selected_steer_boundary_receipt_never_finishes", landed_ids=[m.id for m in landed], after_settle=receipt[0]["state"], acknowledgement_removed=0)

    # A stopped settlement holds only until the next read-only snapshot.
    reg = inbox.InboxRegistry()
    reg._session_idle = lambda sid: True
    calls = []
    async def submitted(sid, text, **kwargs):
        calls.append(text)
        return True
    reg._submit = submitted
    reg.enqueue("stop-snapshot", "held")
    with patch.dict(os.environ, {"XEYO_INBOX_AUTORUN": "1"}):
        await reg.on_turn_settled("stop-snapshot", "stopped", "interrupt")
        await asyncio.sleep(0)
        before = list(calls)
        reg.snapshot("stop-snapshot")
        await asyncio.sleep(0)
        assert before == [] and calls == ["held"], calls
        note("snapshot_restarts_stopped_queue", before_read=before, after_read=calls)

    # Goal revision is local to a goal; endpoint targets whichever binding is now current.
    sid = "goal-identity"
    ws = work / "workspace"
    ws.mkdir()
    _pool.pin_session_cwd(sid, str(ws))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1)), base_url="http://local") as client:
        url = f"/v1/sessions/{sid}/goal"
        old = (await client.patch(url, json={"action": "new", "text": "old goal"})).json()
        new = (await client.patch(url, json={"action": "new", "text": "replacement goal"})).json()
        result = await client.patch(url, json={"action": "edit", "revision": old["revision"], "text": "old editor draft"})
        changed = result.json()
        assert result.status_code == 200 and changed["goal_id"] == new["goal_id"]
        assert changed["text"] == "old editor draft"
        note("stale_goal_editor_changes_replacement", status=result.status_code, same_initial_revision=old["revision"] == new["revision"], target_is_replacement=True)

        # GUI advertises archived sessions as read-only; HTTP goal PATCH still writes.
        from engine.title import write_archive
        write_archive(sid)
        result = await client.patch(url, json={"action": "edit", "revision": changed["revision"], "text": "changed while archived"})
        assert result.status_code == 200 and result.json()["text"] == "changed while archived"
        note("archived_goal_write_accepted", status=result.status_code, text=result.json()["text"])

    # Queue items carry no request environment; all dispatches use the latest session env.
    reg = inbox.InboxRegistry()
    sid = "env-drift"
    synthetic.note_request_env(sid, {"model": "model-A", "provider": "fake", "permission_mode": "always"})
    reg.enqueue(sid, "request-A", message_id="request-A")
    synthetic.note_request_env(sid, {"model": "model-B", "provider": "fake", "permission_mode": "never"})
    captured = []
    async def capture(app, scope, body):
        captured.append(json.loads(body))
        return 200
    with patch.object(synthetic, "_invoke_asgi_head", capture):
        assert await reg._drain_one(sid)
    assert captured[0]["model"] == "model-B" and captured[0]["permission_mode"] == "never"
    note("queued_environment_replaced", submitted_model="model-A", dispatched_model=captured[0]["model"], submitted_approval="always", dispatched_approval=captured[0]["permission_mode"])
    synthetic.clear_request_envs()


async def cli_probe(lines, label):
    import cli.chat_cmd as chat
    from permissions.policy import permission_mode
    builds, turns = [], []
    def build(**kw):
        builds.append({"sid": kw["session_id"], "model": kw["model"]})
        class Engine:
            session_id = kw["session_id"]
            async def submit(self, text, options):
                turns.append({"sid": self.session_id, "text": text, "approval": permission_mode()})
                if False:
                    yield None
        return Engine(), 0
    iterator = iter(lines)
    def read(mode):
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError
    with patch.object(chat, "ensure_utf8_stdio", lambda: None), patch.object(chat, "resolve_cwd", lambda cwd, persist: cwd), patch.object(chat, "build_chat_engine", build), patch.object(chat, "_read_repl_line", read):
        result = await chat.chat_async(prompt=None, cwd=".", session_id="original", provider="fake", model="model-A", api_key="", base_url="", permission_mode="risk", agent_mode="agent", print_mode=False, json_mode=True)
    assert result == 0
    note(label, builds=builds, turns=turns)
    return builds, turns


async def main(work):
    await backend_probes(work)
    builds, turns = await cli_probe(["/approval always", "ordinary task"], "cli_approval_reverted")
    assert turns[0]["approval"] == "risk"
    builds, turns = await cli_probe(["old task", "/model model-B", "new task"], "cli_model_switch_changes_session")
    assert builds[0]["sid"] != builds[1]["sid"]
    builds, turns = await cli_probe(["old task", "/clear", "/retry"], "cli_retry_after_clear_leaks_old_task")
    assert turns[0]["text"] == turns[1]["text"] == "old task" and turns[0]["sid"] != turns[1]["sid"]


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="xeyo-input-audit-") as temp:
        work = Path(temp)
        with patch.dict(os.environ, {"XEYO_HOME": temp, "XEYO_DATA_DIR": temp, "XEYO_SESSIONS_DIR": str(work / "sessions"), "XEYO_USAGE_DIR": str(work / "usage"), "XEYO_INBOX_AUTORUN": "0", "XEYO_C2_GATE": "0", "XEYO_ALLOW_FAKE_MODEL": "1"}):
            asyncio.run(main(work))
    output = json.dumps({"source_revision": "e091434", "mode": "offline_observation_probes", "observations": observations}, ensure_ascii=True, indent=2)
    (Path(__file__).parent / "backend-observations.json").write_text(output + "\n", encoding="utf-8")
    print(output)
