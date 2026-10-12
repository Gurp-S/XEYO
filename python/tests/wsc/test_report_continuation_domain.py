from copy import deepcopy
import json

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("resume", [False, True])
async def test_reporting_reads_selected_asset_without_executing_unknown_tools_or_changing_sources(tmp_path, monkeypatch, resume):
    from evals.wsc_real_report_continuation import run
    from evals import client
    from tests.wsc.test_handoff_bindings import prepared

    store, registry, source, persist, session, state = await prepared(tmp_path / "source")
    original = session.read_bytes()
    workspace = tmp_path / "workspace"
    assets = workspace / ".xeyo"
    assets.mkdir(parents=True)
    asset = assets / "ab_on.txt"
    asset.write_text("ON scratch=true\n", encoding="utf-8")
    key_file = tmp_path / "key.txt"
    key_file.write_text("sk-" + "x" * 32, encoding="utf-8")
    sent = []
    def chat(messages, **kwargs):
        frame = len(sent) % 3
        if frame == 0:
            assert (messages[-1].get("content") == "继续") is (not resume)
        sent.append(deepcopy(messages))
        if frame == 0:
            message = {"tool_calls": [{"id": "unknown", "function": {"name": "Bash", "arguments": '{}'}}]}
        elif frame == 1:
            assert messages[-1]["content"][0]["content"] == "Unknown tool: Bash"
            message = {"tool_calls": [{"id": "read", "function": {"name": "Read", "arguments": json.dumps({
                "file_path": str(asset), "offset": 1, "limit": 1})}}]}
        else:
            result = messages[-1]["content"][0]
            assert not result["is_error"] and "ON scratch=true" in str(result["content"])
            message = {"content": "报告：ON scratch=true"}
        return {"response": {"choices": [{"message": message}], "usage": {
            "prompt_tokens": 20, "completion_tokens": 10, "prompt_cache_hit_tokens": 0}}}
    monkeypatch.setattr(client, "chat", chat)
    # run is synchronous and performs its own Read event loop.
    import asyncio
    report = await asyncio.to_thread(run, [("a", session), ("b", session)], tmp_path / "out", key_file,
                                    execute=True, artifact_cwd=workspace, resume=resume)
    assert len(sent) == 6 and report["selected_artifacts_unchanged"]
    assert all(a["source_unchanged"] and a["frozen_prefix_unchanged"] and a["error"] is None for a in report["arms"])
    assert session.read_bytes() == original and asset.read_text(encoding="utf-8") == "ON scratch=true\n"
