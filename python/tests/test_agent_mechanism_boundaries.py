"""Mechanisms cannot substitute old evidence for an unobserved operation."""
from pathlib import Path

import pytest

from engine.abort import AbortController
from engine.loop_breaker import LoopBreaker
from engine.repeat_fold import IdenticalResultFold
from msgtypes.message import ToolUse
from tools.base_tool import ToolResult
from tools.tool_registry import ToolRegistry


@pytest.mark.asyncio
async def test_identical_receipts_do_not_prevent_new_file_operations(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_LOOP_BREAK_LEDGER", "0")
    class WriteReceipt:
        name = "receipt_writer"
        is_read_only = staticmethod(lambda: False)
        is_concurrency_safe = staticmethod(lambda: False)
        async def execute(self, input, abort):
            (tmp_path / input["target"]).write_text(input["value"], encoding="utf-8")
            return ToolResult("ok")

    registry = ToolRegistry(cwd=str(tmp_path))
    registry.register(WriteReceipt())
    breaker = LoopBreaker(enabled=True)
    refused = []
    for i in range(8):
        params = {"target": f"file{i}.txt", "value": str(i)}
        refusal = breaker.admit("receipt_writer", params)
        if refusal:
            refused.append(i)
            continue
        result = await registry.run(ToolUse(f"write-{i}", "receipt_writer", params), AbortController(), skip_ask=True)
        assert not result.is_error
        breaker.observe_result("receipt_writer", params, result.content)
    files = sorted(tmp_path.glob("file*.txt"))
    assert len(files) == 8, {"completed": len(files), "refused": refused}
    assert all((tmp_path / f"file{i}.txt").read_text() == str(i) for i in range(8))


def test_family_guard_still_blocks_observed_repeated_paths(monkeypatch):
    monkeypatch.setenv("XEYO_LOOP_BREAK_LEDGER", "0")
    breaker = LoopBreaker(same_at=99, equiv_at=99, family_at=2, enabled=True)
    for i in range(3):
        breaker.observe_result("Grep", {"pattern": f"p{i}"}, "same old result")
    refusal = breaker.admit("Grep", {"pattern": "p0"})
    assert refusal and refusal.kind == "L4"
    assert breaker.admit("Grep", {"pattern": "new"}) is None


@pytest.mark.parametrize("ledger", ["0", "1"])
def test_repeated_read_after_compaction_restores_complete_evidence(ledger, monkeypatch):
    monkeypatch.setenv("XEYO_LOOP_LEDGER", ledger)
    text = "configuration\n" + "irrelevant detail\n" * 60 + "required_endpoint=https://service.internal\n"
    fold = IdenticalResultFold()
    params = {"file_path": "configuration.txt"}
    for index in (10, 11, 12):
        fold.process("Read", params, text, msg_index=index)
    restored, folded = fold.process("Read", params, text, msg_index=30, visible_from=20)
    assert not folded
    assert restored == text
    assert "required_endpoint=https://service.internal" in restored
    # The fresh full copy permits useful deduplication again.
    subsequent, folded = fold.process("Read", params, text, msg_index=31, visible_from=20)
    assert folded and len(subsequent) < len(text)


def test_latest_complete_copy_keeps_dedup_useful(monkeypatch):
    monkeypatch.setenv("XEYO_LOOP_LEDGER", "1")
    text = "evidence\n" * 100
    fold = IdenticalResultFold()
    params = {"pattern": "endpoint"}
    fold.process("Grep", params, text, msg_index=10)
    fold.process("Grep", params, text, msg_index=25)
    # The first copy disappeared but the second complete copy remains.
    _, folded = fold.process("Grep", {"pattern": "service"}, text, msg_index=30, visible_from=20)
    assert folded


@pytest.mark.asyncio
async def test_engine_read_after_write_is_not_blocked_by_stale_observations(tmp_path, monkeypatch):
    from engine.query_engine import QueryEngine
    from model.chunks import ModelChunk
    from msgtypes.events import ToolResultEvent
    from permissions.policy import set_permission_mode
    monkeypatch.setenv("XEYO_LOOP_BREAK_LEDGER", "0")
    path = tmp_path / "state.txt"
    path.write_text("before", encoding="utf-8")
    class ReadProbe:
        name = "Read"
        is_read_only = staticmethod(lambda: True)
        is_concurrency_safe = staticmethod(lambda: True)
        def schema(self):
            return {"name": self.name, "description": "File observation.", "parameters": {"type": "object", "properties": {}}}
        async def execute(self, input, abort):
            return ToolResult(path.read_text(encoding="utf-8"))
    class WriteProbe(ReadProbe):
        name = "Write"
        is_read_only = staticmethod(lambda: False)
        is_concurrency_safe = staticmethod(lambda: False)
        async def execute(self, input, abort):
            path.write_text("after", encoding="utf-8")
            return ToolResult("ok")
    class Model:
        last_usage = None
        calls = 0
        async def stream(self, messages, tools, abort):
            self.calls += 1
            if self.calls <= 5:
                name = "Write" if self.calls == 4 else "Read"
                yield ModelChunk(kind="tool_use", tool_use=ToolUse(f"call-{self.calls}", name, {"file_path": str(path)}))
            else:
                yield ModelChunk(kind="text_delta", text="finished")
    registry = ToolRegistry(cwd=str(tmp_path))
    registry.register(ReadProbe())
    registry.register(WriteProbe())
    set_permission_mode("never")
    model = Model()
    engine = QueryEngine({"cwd": str(tmp_path), "tools": registry, "model_client": model,
                          "provider": "deepseek", "model": "deepseek-v4-flash", "max_turns": 10})
    events = [event async for event in engine.submit("Read the state, change it, then verify the new state.")]
    result = next(event for event in events if isinstance(event, ToolResultEvent) and event.tool_use_id == "call-5")
    assert not result.is_error and result.output == "after"
    assert model.calls == 6


@pytest.mark.asyncio
async def test_changing_images_are_new_observations_in_engine(tmp_path, monkeypatch):
    import base64
    from PIL import Image
    from engine.query_engine import QueryEngine
    from model.chunks import ModelChunk
    from msgtypes.events import ToolResultEvent
    from permissions.policy import set_permission_mode
    monkeypatch.setenv("XEYO_LOOP_BREAK_LEDGER", "0")
    path = tmp_path / "frame.png"
    class ImageProbe:
        name = "Read"
        is_read_only = staticmethod(lambda: True)
        is_concurrency_safe = staticmethod(lambda: True)
        def schema(self):
            return {"name": self.name, "description": "Image observation.", "parameters": {"type": "object", "properties": {}}}
        async def execute(self, input, abort):
            url = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
            return ToolResult("Current frame attached.", images=[url])
    class Model:
        last_usage = None
        calls = 0
        async def stream(self, messages, tools, abort):
            self.calls += 1
            if self.calls <= 4:
                # A changing external display; identical descriptive text.
                Image.new("RGB", (2, 2), (self.calls * 40, 0, 0)).save(path)
                yield ModelChunk(kind="tool_use", tool_use=ToolUse(f"frame-{self.calls}", "Read", {"file_path": str(path)}))
            else:
                yield ModelChunk(kind="text_delta", text="finished")
    registry = ToolRegistry(cwd=str(tmp_path))
    registry.register(ImageProbe())
    set_permission_mode("never")
    model = Model()
    engine = QueryEngine({"cwd": str(tmp_path), "tools": registry, "model_client": model,
                          "provider": "deepseek", "model": "deepseek-v4-flash", "max_turns": 10})
    events = [event async for event in engine.submit("Observe the changing display.")]
    results = [event for event in events if isinstance(event, ToolResultEvent)]
    assert len(results) == 4 and all(not result.is_error for result in results)
    assert model.calls == 5


def test_evidence_invalidation_keeps_call_pattern_protection(monkeypatch):
    monkeypatch.setenv("XEYO_LOOP_BREAK_LEDGER", "0")
    breaker = LoopBreaker(same_at=3, enabled=True)
    for _ in range(2):
        assert breaker.admit("Bash", {"command": "repeat"}) is None
        breaker.observe_result("Bash", {"command": "repeat"}, "ok")
    breaker.invalidate_result_evidence()
    refusal = breaker.admit("Bash", {"command": "repeat"})
    assert refusal and refusal.kind == "L1"
