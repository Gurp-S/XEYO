"""Render receipt identity from protocol fields; no task/completion inference."""
import json
import os


def projection_enabled():
    """Model-facing receipt projection is opt-in; direct rendering stays stable."""
    return any(
        (os.environ.get(key) or "").strip().lower() in {"1", "true", "yes", "on"}
        for key in ("XEYO_WSC_TASK_CONTINUITY", "XEYO_WSC_STATE_CONTRACTS", "XEYO_WSC_MODEL_TIMING")
    )
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
            for key in ("read_observation", "grep_observation"):
                observation = execution.get(key) if isinstance(execution, dict) else None
                if isinstance(observation, dict):
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
