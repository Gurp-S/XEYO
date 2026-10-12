"""Render receipt identity from protocol fields; no task/completion inference."""
import json
import os


# 收执头**不可收敛**（2026-10-10 实测，已回退）：曾加过一条旁路
# ``XEYO_RECEIPT_MINIMAL``（无事实结果不加头），开态直接打破 4 条 WSC 合同测试——
#   tests/wsc/test_execution_probe.py::test_receipt_render_is_a_pure_append_stable_projection
#   tests/wsc/test_execution_probe.py::test_receipt_render_keeps_image_and_literal_header_text
#   tests/wsc/test_task_continuity.py::test_committed_todo_survives_size_prune_in_actual_emission
#   tests/wsc/test_task_continuity.py::test_merge_receipt_and_original_checkpoint_survive_unfrozen_tail
# （断言精确相等：恒启的 call_id 身份行；缺了它＝投影不再是稳定 append，迟到回执的绑定失效）。
# 结论：这条"噪声"是合同的代价，不属于可优化项。要减它只能改合同，不在本方案内。


def projection_enabled():
    from synaptic.main_policy import enabled
    return enabled()
def enabled():
    """Keep the renderer's direct API stable; callers gate model projection."""
    return True


def render(messages):
    if not enabled():
        return messages
    emitted = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            emitted.append(message)
            continue
        blocks = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                blocks.append(block)
                continue
            identity = block.get("tool_use_id")
            if not isinstance(identity, (str, int)) or not identity:
                blocks.append(block)
                continue
            facts = {"call_id": identity}
            execution = block.get("execution")
            for key in (
                "read_observation",
                "grep_observation",
                "truncation",
                "error_origin",
            ):
                observation = execution.get(key) if isinstance(execution, dict) else None
                # 事实可以是对象（观测）也可以是标量（例如 error_origin: "requested_command"）：
                # 只认 dict 会把标量事实静默丢掉（A/B 实测 def-2）。
                if isinstance(observation, dict):
                    facts[key] = observation
                elif isinstance(observation, str) and observation:
                    facts[key] = observation
            header = "执行回执身份=" + json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
            body = block.get("content")
            if isinstance(body, str):
                projected = header + "\n" + body
            elif isinstance(body, list):
                projected = [{"type": "text", "text": header}] + body
            else:
                blocks.append(block)
                continue
            blocks.append({**block, "content": projected})
        emitted.append({**message, "content": blocks})
    return emitted
