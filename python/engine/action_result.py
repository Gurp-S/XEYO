"""Durable result artifacts for an enabled journal, without tool arguments."""
import hashlib
import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path

from tools.base_tool import ToolResult


def store_result(journal_path, action_id, result):
    # The action id is not a path component supplied by a tool.
    name = hashlib.sha256(action_id.encode()).hexdigest() + ".json"
    path = journal_path.parent / "action-results" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(asdict(result), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    temp = path.with_name(name + "." + uuid.uuid4().hex + ".tmp")
    try:
        fd = os.open(str(temp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return {"result_path": str(path.resolve()), "result_sha256": hashlib.sha256(data).hexdigest()}


def replay_result(record, *, action_id, side_effect):
    if record.get("result_path"):
        data = Path(record["result_path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != record.get("result_sha256"):
            raise OSError("action result checksum mismatch")
        result = ToolResult(**json.loads(data))
    else:
        if record.get("result_truncated"):
            raise OSError("legacy action result is incomplete")
        result = ToolResult(content=str(record.get("result_content") or ""),
                            is_error=bool(record.get("result_is_error", False)),
                            status=str(record.get("result_status") or "ok"),
                            error_kind=record.get("error_kind"),
                            retryable=bool(record.get("retryable", False)),
                            side_effect=str(record.get("side_effect") or side_effect))
    result.action_id = action_id
    result.metadata = {**(result.metadata or {}), "action_replayed": True}
    return result
