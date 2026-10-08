"""Offline product-force audit: archive availability is not task-state coverage."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path

from evals.wsc_execution_behavior import seed, Executor
from evals.wsc_request_projection import arm


def run(output):
    from memory.runtime import force_compact
    from memory.working import WorkingSnapshot
    from memory import wsc_projection
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"scope": "isolated seeded task, actual force_compact; no model/API calls", "arms": {}}
    previous = os.environ.get("XEYO_WSC")
    try:
        for native in (False, True):
            for committed in (False, True):
                target = output / (str(native) + "-" + str(committed))
                with arm("1", target / "home"):
                    os.environ["XEYO_WSC"] = str(int(native))
                    wsc_projection._STATE.clear()
                    rows, records = seed(target / "task")
                    specification = rows[13]["content"]
                    if not committed:
                        assert rows[-2]["content"][0]["name"] == "TodoWrite"
                        rows, records = rows[:-2], []
                    rows += [{"role": "assistant", "content": "已观察追加记录 " + str(i) + "x" * 2000} for i in range(18)]
                    rows += [{"role": "user", "content": "继续当前任务"}]
                    original = deepcopy(rows)
                    working = WorkingSnapshot(session_id="uncommitted-force")
                    emitted = force_compact(rows, working, cwd=target / "task")
                    head = emitted[0]["content"]
                    executor = Executor(target / "task", records)
                    # Use real FileReadTool against a published full-source view,
                    # not an in-memory archive dict or a fabricated tool result.
                    recovered = False
                    read_count = 0
                    for view in (target / "task").rglob("*.txt"):
                        lines = view.read_text(encoding="utf-8").splitlines()
                        for index, line in enumerate(lines):
                            if specification in line:
                                receipt = executor.execute("Read", {"file_path": str(view), "offset": index + 1, "limit": 1})
                                read_count += 1
                                recovered |= not receipt["is_error"] and specification in receipt["content"]
                    key = str(native) + "-" + str(committed)
                    report["arms"][key] = {
                        "native_requested": native, "native_used": bool(wsc_projection._STATE),
                        "initial_checkpoint_committed": committed, "cursor": working.compact_cursor,
                        "true_fold": working.compact_cursor > 13,
                        "source_rows_unchanged": rows == original,
                        "task_handoff_present": "任务交接快照" in head,
                        "report_receipt_constraint_hot": "verification_call_id" in head,
                        "full_specification_hot": specification in head,
                        "actual_read_recovers_full_specification": recovered, "read_count": read_count}
                    (target / "emitted.json").write_text(json.dumps(emitted, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        wsc_projection._STATE.clear()
        if previous is None:
            os.environ.pop("XEYO_WSC", None)
        else:
            os.environ["XEYO_WSC"] = previous
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    run(parser.parse_args().output)
