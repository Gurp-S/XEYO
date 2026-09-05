"""子 Agent MemoryCandidate 采集。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.subagent_memory import (
    collect_files_touched,
    harvest_subagent_memories,
    strip_memory_markers,
)
from memory.working import WorkingSnapshot
from msgtypes.message import Message, assistant_text_message


def test_parse_line_marker():
    msgs = [
        assistant_text_message(
            "Done.\nMEMORY_CANDIDATE: 真库测试偏好用 pytest\n"
        )
    ]
    snap = WorkingSnapshot()
    mems, cleaned = harvest_subagent_memories(
        msgs,
        snap,
        main_session_id="main-s",
        agent_id="agent-a",
        conclusion="",
    )
    assert len(mems) == 1
    assert "pytest" in mems[0]["content"]
    assert mems[0]["source"]["agent_id"] == "agent-a"


def test_parse_fence_json():
    text = (
        "Summary\n```memory_candidate\n"
        '{"content": "API base URL is /v1/chat"}\n```'
    )
    mems, _ = harvest_subagent_memories(
        [],
        WorkingSnapshot(),
        main_session_id="s",
        agent_id="a",
        conclusion=text,
    )
    assert len(mems) == 1
    assert "/v1/chat" in mems[0]["content"]


def test_strip_markers_from_conclusion():
    raw = "OK\nMEMORY_CANDIDATE: secret fact\nTail"
    cleaned = strip_memory_markers(raw)
    assert "MEMORY_CANDIDATE" not in cleaned
    assert "Tail" in cleaned
    assert "secret fact" not in cleaned


def test_speculation_becomes_candidate():
    snap = WorkingSnapshot(speculation=["模块入口在 engine/query_loop.py"])
    mems, _ = harvest_subagent_memories(
        [],
        snap,
        main_session_id="s",
        agent_id="a",
    )
    assert len(mems) == 1
    assert "query_loop" in mems[0]["content"]


def test_collect_files_touched():
    msgs = [
        Message(
            role="assistant",
            content=[
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "Write",
                    "input": {"file_path": "src/a.ts", "content": "x"},
                }
            ],
        ),
        Message(
            role="assistant",
            content=[
                {
                    "type": "tool_use",
                    "id": "t2",
                    "name": "Edit",
                    "input": {"file_path": "src/b.ts", "old_string": "a", "new_string": "b"},
                },
            ],
        ),
    ]
    paths = collect_files_touched(msgs)
    assert paths == ["src/a.ts", "src/b.ts"]


def test_dedupe_and_cap():
    snap = WorkingSnapshot()
    body = "\n".join(f"MEMORY_CANDIDATE: fact {i}" for i in range(20))
    mems, _ = harvest_subagent_memories(
        [assistant_text_message(body)],
        snap,
        main_session_id="s",
        agent_id="a",
    )
    assert len(mems) <= 8
