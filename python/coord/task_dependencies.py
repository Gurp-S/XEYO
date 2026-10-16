"""Persisted DAG admission, shared by planner and worker claim operations."""
from contextlib import contextmanager


def enabled():
    from engine.agent_runtime import enabled as runtime_enabled
    return runtime_enabled()


@contextmanager
def graph_guard(store):
    if enabled():
        import time
        from engine.agent_identity import AgentLease, AgentBusy
        lease = AgentLease(store.coord_dir / "owner-locks", "coord", "task-graph")
        deadline = time.monotonic() + 5
        while True:
            try:
                lease.acquire()
                break
            except AgentBusy:
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(.01)
        try:
            yield True
        finally:
            lease.release()
    else:
        yield True


def publish(store, drafts, rejected):
    from dataclasses import replace
    with graph_guard(store) as ok:
        if not ok:
            return {"created": [], "rejected": [*rejected, {"reason": "task_graph_busy"}]}
        existing = {t.task_id: t for t in store.list_tasks()}
        tasks = {t.task_id: replace(t, deps=list(dict.fromkeys(deps))) for t, deps in drafts}
        reason = ""
        if existing.keys() & tasks.keys():
            reason = "duplicate_task_id"
        elif any(not key.startswith("task_") or any(c in key for c in "/\\") for key in tasks):
            reason = "invalid_task_id"
        graph = {**existing, **tasks}
        if not reason:
            missing = next((dep for t in tasks.values() for dep in t.deps if dep not in graph), None)
            if missing:
                reason = "unknown_dep:" + missing
        if not reason:
            pending = {key: set(t.deps) for key, t in graph.items()}
            while pending:
                ready = {key for key, deps in pending.items() if not deps}
                if not ready:
                    reason = "cyclic_dependencies"
                    break
                pending = {key: deps - ready for key, deps in pending.items() if key not in ready}
        if reason:
            return {"created": [], "rejected": [*rejected, *[
                {"title": t.title, "reason": reason} for t in tasks.values()]]}
        if tasks:
            from coord.task_batches import publish as publish_batch
            publish_batch(store, tasks.values())
        return {"created": list(tasks), "rejected": rejected}


def claim(store, task_id, worker_id, base_commit):
    from coord.store import claim_task
    with graph_guard(store) as ok:
        if not ok:
            return None
        with store._guard("task-" + task_id) as owned:
            if not owned:
                return None
            task = store.load_task(task_id)
            if task is None:
                return None
            dependencies = [store.load_task(dep) for dep in task.deps]
            if any(dep is None or dep.status not in ("completed", "merged") for dep in dependencies):
                return None
            claimed = claim_task(task, worker_id, base_commit)
            if claimed is not None:
                store._save_task(claimed)
            return claimed
