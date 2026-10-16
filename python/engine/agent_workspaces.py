"""Owned worktrees and explicit, content-checked publication to a checkout.

Worker completion never publishes. Publication preserves the parent's Git index
and participates in XEYO's workspace and path locks. External editors do not
participate in these locks; no cross-editor atomicity is claimed.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
from engine.agent_io import owned_io as _owned_io

from engine.agent_identity import current_agent
from engine.agent_run_store import AgentRunStore


def git(repo, *args, data=None, index=None):
    env = dict(os.environ)
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        env.pop(key, None)
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_AUTHOR_NAME="XEYO Agent",
               GIT_AUTHOR_EMAIL="agent@local", GIT_COMMITTER_NAME="XEYO Agent",
               GIT_COMMITTER_EMAIL="agent@local")
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    completed = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=repo,
                               env=env, input=data, capture_output=True, timeout=120)
    if completed.returncode:
        raise RuntimeError("git_failed: " + completed.stderr.decode("utf-8", "replace")[:400])
    return completed.stdout


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".xeyo-publish-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _save(path, value):
    _atomic(path, json.dumps(value, ensure_ascii=False).encode("utf-8"))


def _snapshot(repo, directory):
    """Capture the visible checkout without changing its HEAD or index."""
    directory.mkdir(parents=True, exist_ok=True)
    index = directory / ("snapshot-" + os.urandom(8).hex() + ".index")
    try:
        head = git(repo, "rev-parse", "HEAD").decode().strip()
        git(repo, "read-tree", head, index=index)
        paths = _source_paths(repo)
        if paths:
            git(repo, "--literal-pathspecs", "add", "-A", "--pathspec-from-file=-",
                "--pathspec-file-nul", data=b"\0".join(paths) + b"\0", index=index)
        git(repo, "rm", "--cached", "-r", "--ignore-unmatch", "--", ".xeyo", ".tmp", ".xy-shadow-git", index=index)
        tree = git(repo, "write-tree", index=index).decode().strip()
        return git(repo, "commit-tree", tree, "-p", head,
                   data=b"XEYO isolated working snapshot\n").decode().strip()
    finally:
        index.unlink(missing_ok=True)
        Path(str(index) + ".lock").unlink(missing_ok=True)


def _source_paths(repo):
    paths = git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    # A staged deletion is absent from the real index, but still present in
    # HEAD (the temporary index's base). It must participate in git add -A.
    paths += git(repo, "ls-tree", "-r", "--name-only", "-z", "HEAD")
    return sorted({p for p in paths.split(b"\0") if p and p.split(b"/", 1)[0]
                   not in (b".xeyo", b".tmp", b".xy-shadow-git")})


def _baseline(repo):
    hashes = {}
    for raw in _source_paths(repo):
        name = raw.decode("utf-8")
        path = Path(repo) / name
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() and not path.is_symlink() else None
    return hashes


def _validate(artifact):
    repo = Path(artifact["repo"]).resolve()
    path = Path(artifact["worktree"])
    expected = repo / ".xeyo" / "agent-worktrees" / artifact["resource_id"]
    if path.is_symlink() or path.resolve() != expected.resolve() or not path.is_dir():
        raise RuntimeError("invalid_worktree_identity")
    actual = Path(git(path, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    branch = git(path, "symbolic-ref", "--short", "HEAD").decode().strip()
    if actual != path.resolve() or actual == repo or branch != artifact["branch"]:
        raise RuntimeError("invalid_worktree_identity")
    return repo, path


def prepare(identity, spec, previous=None):
    from engine.workspace_mutation import hold_workspace_mutation
    from coord.worktree import git as metadata_git
    from coord.worktree_metadata import metadata_guard
    if previous and previous.get("artifact"):
        from engine.agent_artifact_state import reconcile
        artifact = reconcile(previous["artifact"], resuming=True)
        _validate(artifact)
        if artifact.get("applied_head") == artifact["head"]:
            artifact = {**artifact, "base": artifact["head"], "applied_head": "",
                        "base_hashes": _baseline(Path(artifact["worktree"])), "changed_files": []}
        _save(Path(artifact["directory"]) / "artifact.json", artifact)
        return artifact
    source = Path(spec["cwd"]).resolve()
    repo = Path(git(source, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    relative = source.relative_to(repo)
    from engine.agent_artifact_state import resource_id
    resource = resource_id(identity)
    path = repo / ".xeyo" / "agent-worktrees" / resource
    branch = "xeyo/agent/" + resource
    directory = AgentRunStore().directory / "artifacts" / resource
    with hold_workspace_mutation(repo, owner="agent-snapshot:" + identity.attempt_id, timeout=10):
        baseline = _baseline(repo)
        base = _snapshot(repo, directory)
    artifact = {"repo": str(repo), "source_cwd": str(source), "worktree": str(path),
                "cwd": str(path / relative), "branch": branch, "base": base, "head": base,
                "resource_id": resource, "directory": str(directory), "changed_files": [],
                "applied_head": "", "scope": list(spec.get("scope") or []), "base_hashes": baseline}
    _save(directory / "artifact.json", artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    with metadata_guard(repo, metadata_git, timeout=120) as acquired:
        if not acquired or path.exists():
            raise RuntimeError("worktree_resource_busy")
        git(repo, "worktree", "add", "-b", branch, str(path), base)
    return artifact


def collect(artifact):
    repo, path = _validate(artifact)
    head = _snapshot(path, Path(artifact["directory"]))
    old = git(path, "rev-parse", "HEAD").decode().strip()
    git(path, "update-ref", "refs/heads/" + artifact["branch"], head, old)
    git(path, "read-tree", head)
    files = git(repo, "diff", "--no-renames", "--name-only", "-z", artifact["base"], head)
    artifact = {**artifact, "head": head,
                "changed_files": [p.decode("utf-8") for p in files.split(b"\0") if p]}
    _save(Path(artifact["directory"]) / "artifact.json", artifact)
    return artifact


async def run_child(tool, agent_input, *, agent_id, runtime, tool_whitelist, abort,
                    append_prompt, on_text_delta):
    from engine.write_store import WriteStore
    from tools.agent_tool.worktree_isolation import IsolationOutcome
    identity = current_agent.get()
    if identity is None:
        raise RuntimeError("missing_agent_attempt")
    store = await asyncio.to_thread(AgentRunStore)
    row = await asyncio.to_thread(store.get, identity.session_id, identity.agent_id)
    def prepare_owned():
        artifact = prepare(identity, row["spec"], row)
        store.artifact(identity, artifact)
        return artifact
    artifact = await _owned_io(prepare_owned)
    try:
        out = await tool._run_child(agent_input, agent_id=agent_id, runtime=runtime,
            tool_whitelist=tool_whitelist, abort=abort, append_prompt=append_prompt,
            on_text_delta=on_text_delta, workspace_root=artifact["cwd"],
            write_store=WriteStore(artifact["cwd"], allowed_paths=(artifact["cwd"],)))
    finally:
        def collect_owned():
            collected = collect(artifact)
            store.artifact(identity, collected)
            return collected
        artifact = await _owned_io(collect_owned)
    out.isolation = IsolationOutcome(ok=not out.is_error, branch=artifact["branch"],
        worktree=artifact["worktree"], changed_files=artifact["changed_files"],
        no_changes=not artifact["changed_files"], detail="retained; publication pending")
    return out


def _blob(repo, revision, name):
    entry = git(repo, "ls-tree", "-z", revision, "--", name)
    if not entry:
        return None, None
    mode, kind, oid = entry.split(b"\t", 1)[0].split()
    if kind != b"blob" or mode not in (b"100644", b"100755"):
        raise RuntimeError("unsupported_artifact_file: " + name)
    return git(repo, "cat-file", "blob", oid.decode()), mode.decode()


def _target(repo, name, artifact):
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or any(p.lower() in (".git", ".xeyo") for p in relative.parts):
        raise RuntimeError("invalid_artifact_path")
    path = repo.joinpath(*relative.parts)
    if not path.resolve().is_relative_to(repo) or any(p.is_symlink() for p in [path, *path.parents] if p != repo.parent):
        raise RuntimeError("invalid_artifact_path")
    source = Path(artifact["source_cwd"])
    allowed = [(source / scope).resolve() for scope in artifact["scope"]]
    if not any(path.resolve() == p or path.resolve().is_relative_to(p) for p in allowed):
        raise RuntimeError("artifact_outside_write_scope: " + name)
    return path


def publish(artifact):
    from engine.workspace_mutation import hold_workspace_mutation
    from engine.write_transaction import path_lock
    repo, worktree = _validate(artifact)
    if git(worktree, "rev-parse", "HEAD").decode().strip() != artifact["head"]:
        raise RuntimeError("artifact_head_changed")
    if git(worktree, "status", "--porcelain").strip():
        raise RuntimeError("artifact_has_uncollected_changes")
    if artifact.get("applied_head") == artifact["head"]:
        return artifact
    files = artifact["changed_files"]
    targets = {name: _target(repo, name, artifact) for name in files}
    journal = Path(artifact["directory"]) / "publication.json"
    with hold_workspace_mutation(repo, owner="agent-publish:" + artifact["resource_id"], timeout=10), ExitStack() as locks:
        for name in sorted(targets):
            locks.enter_context(path_lock(targets[name]))
        prior = json.loads(journal.read_text(encoding="utf-8")) if journal.exists() else {}
        if prior.get("state") == "applied" and prior.get("head") == artifact["head"]:
            return {**artifact, "applied_head": artifact["head"]}
        recovering = prior.get("state") == "applying" and prior.get("head") == artifact["head"]
        if prior.get("state") == "applying" and not recovering:
            raise RuntimeError("publication_recovery_required: " + str(journal))
        saved = {item["path"]: item for item in prior.get("files", [])} if recovering else {}
        changes = []
        size = 0
        for name, target in targets.items():
            _, _ = _blob(repo, artifact["base"], name)
            new_blob, mode = _blob(repo, artifact["head"], name)
            new = (worktree / name).read_bytes() if new_blob is not None else None
            current = target.read_bytes() if target.is_file() else None
            current_hash = hashlib.sha256(current).hexdigest() if current is not None else None
            was_applied = recovering and name in saved and current_hash == saved[name]["after_sha256"]
            if current_hash != artifact["base_hashes"].get(name) and not was_applied:
                raise RuntimeError("publication_conflict: " + name)
            old = (base64.b64decode(saved[name]["before"]) if saved[name]["before"] is not None else None) if recovering else current
            size += len(old or b"") + len(new or b"")
            if size > 128 * 1024 * 1024:
                raise RuntimeError("publication_size_limit")
            old_mode = saved[name].get("before_mode") if recovering else (target.stat().st_mode if target.exists() else None)
            changes.append((name, old, new, mode, old_mode))
        receipt = {"state": "applying", "head": artifact["head"], "files": [
            {"path": name, "before": base64.b64encode(old).decode() if old is not None else None,
             "after_sha256": hashlib.sha256(new).hexdigest() if new is not None else None,
             "before_mode": old_mode}
            for name, old, new, _, old_mode in changes]}
        _save(journal, receipt)
        touched = []
        try:
            for name, old, new, mode, old_mode in changes:
                target = targets[name]
                touched.append((name, old, old_mode))
                if new is None:
                    target.unlink(missing_ok=True)
                else:
                    _atomic(target, new)
                    os.chmod(target, old_mode if old_mode is not None else (0o755 if mode == "100755" else 0o644))
        except BaseException:
            rollback = [(n, old, old_mode) for n, old, _, _, old_mode in changes] if recovering else touched
            for name, old, old_mode in reversed(rollback):
                target = targets[name]
                if old is None:
                    target.unlink(missing_ok=True)
                else:
                    _atomic(target, old)
                    if old_mode is not None:
                        os.chmod(target, old_mode)
            _save(journal, {**receipt, "state": "rolled_back"})
            raise
        artifact = {**artifact, "applied_head": artifact["head"]}
        _save(journal, {**receipt, "state": "applied"})
        _save(Path(artifact["directory"]) / "artifact.json", artifact)
        return artifact
