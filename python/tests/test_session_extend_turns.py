"""session_extend_turns：真实会话循环扩展到 N user 轮。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from memory.simulator.replay import _user_turn_indices, load_jsonl
from scripts.session_extend_turns import extend_session_rows, rows_to_api


def test_extend_to_200_turns(tmp_path):
    src = {
        "id": "u1",
        "role": "user",
        "content": "hello",
    }
    rows = [
        src,
        {"id": "a1", "role": "assistant", "content": "hi"},
        {"id": "u2", "role": "user", "content": "again"},
        {"id": "a2", "role": "assistant", "content": [{"type": "tool_use", "id": "call_x", "name": "Read", "input": {}}]},
        {"id": "t1", "role": "tool", "content": [{"type": "tool_result", "tool_use_id": "call_x", "content": "ok"}], "tool_call_id": "call_x"},
    ]
    p = tmp_path / "mini.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    base = load_jsonl(p)
    ext = extend_session_rows(base, target_user_turns=5)
    api = rows_to_api(ext)
    assert len(_user_turn_indices(api)) == 5
    text = json.dumps(ext, ensure_ascii=False)
    assert "c000t01_call_x" in text
    assert text.count('"id": "call_x"') == 0
