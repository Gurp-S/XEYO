"""Full task identity for coord worktrees; active resources are never replaced."""
import hashlib


def task_resource(task_id):
    return hashlib.sha256(str(task_id).encode("utf-8")).hexdigest()[:24]
