"""coord 双进程契约测试的子进程脚本（非 pytest 收集目标）。

用法::
    python coord_child.py claim  <ws> <task_id> <worker_id> <base_commit> <attempts>
    python coord_child.py write  <ws> <session_id> <rel_path> <title>
    python coord_child.py status <ws> <task_id>

stdout 输出 JSON（stdout 只放 JSON，诊断走 stderr）。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # python/


def main(argv: list[str]) -> int:
    mode = argv[1]
    if mode == "claim":
        ws, task_id, worker, base, attempts = argv[2], argv[3], argv[4], argv[5], int(argv[6])
        from coord.file_store import CoordFileStore

        store = CoordFileStore(ws)
        ok = 0
        last = None
        for _ in range(attempts):
            claimed = store.claim_task(task_id, worker, base)
            if claimed is not None:
                ok += 1
                last = claimed.to_dict()
                break
            time.sleep(0.005)
        print(json.dumps({"worker": worker, "ok": ok, "task": last}, ensure_ascii=False))
        return 0

    if mode == "write":
        ws, session_id, rel_path, title = argv[2], argv[3], argv[4], argv[5]
        from coord.presence_adapter import FileBackedPresence

        fb = FileBackedPresence()
        fb.note_write(ws, session_id, str(Path(ws) / rel_path), title=title)
        print(json.dumps({"wrote": rel_path, "by": session_id}, ensure_ascii=False))
        return 0

    if mode == "busy":
        ws, session_id, title = argv[2], argv[3], argv[4]
        from coord.presence_adapter import FileBackedPresence

        fb = FileBackedPresence()
        fb.touch_busy(ws, session_id, busy=True, title=title)
        print(json.dumps({"busy": session_id}, ensure_ascii=False))
        return 0

    if mode == "status":
        ws, task_id = argv[2], argv[3]
        from coord.file_store import CoordFileStore

        t = CoordFileStore(ws).load_task(task_id)
        print(json.dumps({"status": t.status if t else None}, ensure_ascii=False))
        return 0

    print(json.dumps({"error": f"unknown mode {mode}"}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
