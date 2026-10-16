"""A dependency graph batch becomes visible through one atomic file publication.

Task transitions remain per-task snapshots and override their initial batch row.
Readers also understand pre-existing individual task files.
"""
import json
import uuid


def load(store):
    from coord.store import Task
    tasks = {}
    for path in sorted((store.coord_dir / "task-batches").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("version") != 1 or not isinstance(document.get("tasks"), list):
            raise OSError("invalid_task_batch")
        for row in document["tasks"]:
            task = Task.from_dict(row)
            if task.task_id in tasks:
                raise OSError("duplicate_task_batch_identity")
            tasks[task.task_id] = task
    return tasks


def publish(store, tasks):
    from coord.file_store import _atomic_write_json
    path = store.coord_dir / "task-batches" / (uuid.uuid4().hex + ".json")
    if not _atomic_write_json(path, {"version": 1, "tasks": [task.to_dict() for task in tasks]}):
        raise OSError("task_batch_persistence_failed")
