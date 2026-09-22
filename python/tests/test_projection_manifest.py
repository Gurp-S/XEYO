from __future__ import annotations

from engine.projection_manifest import build_manifest


def test_projection_manifest_detects_pairs_and_spill() -> None:
    canonical = [
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "u1", "name": "Read"}],
        },
        {
            "role": "tool",
            "content": [{"type": "tool_result", "tool_use_id": "u1", "content": "ok"}],
        },
    ]
    projected = canonical + [
        {"role": "system", "content": "state"},
        {"role": "tool", "content": "output truncated; full output: /tmp/out"},
    ]
    manifest = build_manifest(
        canonical=canonical,
        projected=projected,
        compact_cursor=1,
        context_limit=1_000_000,
    )
    assert manifest.tool_pairs_preserved == 1
    assert manifest.unresolved_tool_calls == 0
    assert manifest.spills == 1
    assert manifest.t_now_system_blocks == 1
    assert manifest.context_limit == 1_000_000
    assert not manifest.invariant_errors


def test_projection_manifest_marks_unpaired_tool_call() -> None:
    manifest = build_manifest(
        canonical=[
            {"role": "assistant", "content": [{"type": "tool_use", "id": "u1"}]}
        ],
        projected=[
            {"role": "assistant", "content": [{"type": "tool_use", "id": "u1"}]}
        ],
    )
    assert manifest.unresolved_tool_calls == 1
    assert any("unresolved_tool_calls" in x for x in manifest.invariant_errors)


def test_projection_manifest_flags_orphan_tool_result() -> None:
    """2026-09-20 事故回归：只有「结果无调用」才会让厂商 400，原先漏报。

    坏投影被判为合法 ⇒ 引擎每轮原样重发同一个坏形状 ⇒ 会话结构性卡死。
    """
    canonical = [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "u1"}]},
        {
            "role": "tool",
            "content": [{"type": "tool_result", "tool_use_id": "u1", "content": "ok"}],
        },
    ]
    projected = canonical + [
        {
            "role": "tool",
            "content": [
                {"type": "tool_result", "tool_use_id": "ghost", "content": "x"}
            ],
        }
    ]
    manifest = build_manifest(canonical=canonical, projected=projected)
    assert manifest.tool_calls_seen == 1
    assert manifest.tool_results_seen == 2
    assert manifest.tool_pairs_preserved == 1
    assert manifest.unresolved_tool_calls == 0
    assert "orphan_tool_results:1" in manifest.invariant_errors
