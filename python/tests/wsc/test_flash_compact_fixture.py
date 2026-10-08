from evals.wsc_flash_compact_chain import extract_answer, native_store
from engine.query_loop import _repair_unpaired_tool_calls


def test_native_receipt_survives_runtime_repair():
    rows = [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "cp", "name": "TodoWrite", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "cp", "content": "committed", "is_error": False}]},
    ]
    store = native_store(rows)
    _repair_unpaired_tool_calls(store)
    assert len(store.items) == 2
    assert store.items[1].role == "tool"
    assert store.items[1].tool_call_id == "cp"
    assert store.items[1].content[0]["content"] == "committed"


def test_answer_extraction_accepts_prose_but_rejects_ambiguity():
    assert extract_answer('Result:\n```json\n{"objective_id":"BILL-27"}\n```\nExplanation') == {"objective_id": "BILL-27"}
    assert extract_answer('{"objective_id":"a"} {"objective_id":"b"}') == {}
