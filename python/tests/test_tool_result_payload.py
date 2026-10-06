"""Tool transformations must preserve receipts and media all the way to wire."""
from pathlib import Path

import pytest
from PIL import Image

from engine.abort import AbortController
from extension.mcp_client import _result_from_mcp_call
from model._openai_common import normalize_messages_for_openai, prune_orphan_tool_rows
from msgtypes.message import ToolUse, tool_result_message
from tools.base_tool import ToolResult
from tools.tool_registry import ToolRegistry


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_SPILL_DIR", str(tmp_path / "spill"))
    monkeypatch.setenv("XEYO_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    from audit.log import reset_default_audit_log
    reset_default_audit_log()
    yield tmp_path
    reset_default_audit_log()


@pytest.mark.asyncio
async def test_large_mcp_result_preserves_media_and_receipts(isolated):
    import base64
    import io
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buf, format="PNG")
    raw = "observation\n" * 2000
    original = _result_from_mcp_call({"content": [
        {"type": "text", "text": raw},
        {"type": "image", "mimeType": "image/png", "data": base64.b64encode(buf.getvalue()).decode()},
    ]})
    original.todos = [{"id": "t", "content": "inspect", "status": "pending"}]
    original.ui = {"action": "open_panel", "panel": "files"}
    original.metadata = {"receipt": "r"}
    original.action_id = "action-1"

    class Probe:
        name = "payload_probe"
        is_read_only = staticmethod(lambda: True)
        is_concurrency_safe = staticmethod(lambda: True)
        async def execute(self, input, abort):
            return original

    registry = ToolRegistry(cwd=str(isolated))
    registry.register(Probe())
    result = await registry.run(ToolUse("p", "payload_probe", {}), AbortController(), skip_ask=True)
    assert result.images == original.images
    assert result.todos == original.todos and result.ui == original.ui
    assert result.execution_metadata() == original.execution_metadata()
    assert result.metadata["receipt"] == "r"
    assert Path(result.metadata["spill_path"]).read_text(encoding="utf-8") == original.content
    assert len(result.content) < len(original.content)
    assert original.metadata == {"receipt": "r"}


@pytest.mark.asyncio
async def test_real_routed_read_keeps_png(isolated):
    from permissions.workspace_policy import clear_policy_cache
    from tools.catalog import apply_read_vision, build_default_registry
    (isolated / ".xeyo-policy.json").write_text('{"bash":"default","bash_routing":"auto"}')
    clear_policy_cache()
    Image.new("RGB", (2, 2), "red").save(isolated / "image.png")
    registry = build_default_registry(cwd=str(isolated))
    apply_read_vision(registry, enabled=True)
    direct = await registry.run(ToolUse("direct", "Read", {"file_path": str(isolated / "image.png")}), AbortController())
    routed = await registry.run(ToolUse("route", "Bash", {"command": "cat image.png"}), AbortController())
    assert not routed.is_error
    assert routed.metadata["routed_tool"] == "Read"
    assert direct.images and routed.images == direct.images
    clear_policy_cache()


@pytest.mark.parametrize("count", [1, 2])
def test_openai_tool_images_survive_wire_without_breaking_batch(count):
    calls = [{"type": "tool_use", "id": f"c{i}", "name": "Read", "input": {}} for i in range(count)]
    url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP8zwACTGCSAQANHQEDgslx/wAAAABJRU5ErkJggg=="
    rows = [{"role": "assistant", "content": calls}]
    for i in range(count):
        msg = tool_result_message(f"c{i}", "Read", f"image {i}", images=[url])
        rows.append({"role": "tool", "tool_call_id": msg.tool_call_id, "content": msg.content})
    rows.append({"role": "assistant", "content": "received"})
    wire = normalize_messages_for_openai(rows)
    wire, dropped = prune_orphan_tool_rows(wire)
    assert dropped == []
    assert [r["tool_call_id"] for r in wire if r["role"] == "tool"] == [f"c{i}" for i in range(count)]
    images = [b for r in wire if isinstance(r["content"], list) for b in r["content"] if b.get("type") == "image_url"]
    assert len(images) == count
    assert all(b["image_url"]["url"] == url for b in images)
    assert wire[-1]["content"] == "received"
