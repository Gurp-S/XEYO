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


def _manifest_for(text: str):
    """把一段工具输出塞进投影，看 manifest 对截断标记说什么。"""
    canonical = [{"role": "tool", "content": [{"type": "tool_result", "tool_use_id": "u1", "content": text}]}]
    return build_manifest(
        canonical=canonical,
        projected=canonical,
        context_limit=1_000_000,
    )


def test_real_producer_shapes_are_all_consistent() -> None:
    """四个真实产生方的标记形状各不相同，健康投影一律不得报不一致。

    旧判据是 ``count("full output:") != count("output truncated")``：
    Bash 截断与后台任务标记天生不带 ``full output:``，于是任何一次读被截断过的
    输出都会让旗标为真（真实数据 26/40 轮全由此而来），正文引用这两个词也算数。
    """
    shapes = [
        # tools/tool_registry.py：声明与句柄成对
        "[output truncated: 预算截断（非错误），原始 9000 字符；full output: /tmp/a.txt]",
        # tools/spill.py：只有句柄
        "…前文…\nfull output: /tmp/b.txt (5120 bytes)",
        # tools/bash_tool/truncate.py：自带回读路径，不写 "full output:"
        "…body…\n\n[output truncated, full at /tmp/c.log (9000 chars)]",
        # tools/job_tools.py：更早的输出已在之前的分片里送过，尾标记无句柄
        "job tail\n(earlier output truncated)",
    ]
    for text in shapes:
        manifest = _manifest_for(text)
        assert "truncation_without_handle" not in manifest.invariant_errors, text
        assert manifest.spills == (0 if "earlier output" in text else 1), text


def test_truncation_claim_without_a_handle_is_flagged() -> None:
    """真正会伤人的形状：说了"截断"却没给可回读句柄——原文再也读不回来。"""
    manifest = _manifest_for("[output truncated: 预算截断（非错误），原始 9000 字符；]")
    assert "truncation_without_handle" in manifest.invariant_errors
    assert manifest.spills == 0


def test_mentioning_the_words_in_prose_is_not_a_truncation() -> None:
    """判据只认标记形状，不认裸子串：正文里讨论这两个词不再误报不一致。

    口径限制一并钉住：``spills`` 是按标记前缀计数的估计值，正文原样引用
    ``full output:`` 仍会算一处 —— 那只是展示用的"大概几处可回读"，
    不变量看的是 ``_unhandled_truncations``。
    """
    manifest = _manifest_for(
        "这段日志说 output truncated 又提到 full output: 但两处都是引用文本，不是标记"
    )
    assert "truncation_without_handle" not in manifest.invariant_errors
    assert manifest.spills == 1
