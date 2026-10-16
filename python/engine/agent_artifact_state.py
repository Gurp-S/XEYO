"""Durable artifact receipts reconcile worktree collection and DB settlement.

An unfinished publication pins its exact head until publication is recovered.
Run admission owns the agent lease before inspecting these receipts.
"""
import json
import hashlib
from pathlib import Path
from engine.agent_identity import AgentBusy


def resource_id(identity):
    return hashlib.sha256((identity.session_id + "\0" + identity.agent_id + "\0" + identity.attempt_id).encode()).hexdigest()[:24]


def reconcile(artifact, *, resuming=False):
    if not artifact:
        return artifact
    directory = Path(artifact["directory"])
    manifest = directory / "artifact.json"
    if manifest.exists():
        saved = json.loads(manifest.read_text(encoding="utf-8"))
        # Only the same resource can advance the durable checkpoint.
        identity = ("repo", "source_cwd", "worktree", "cwd", "branch", "resource_id", "directory", "scope")
        if any(saved.get(key) != artifact.get(key) for key in identity):
            raise AgentBusy("artifact_identity_mismatch")
        artifact = saved
    journal = directory / "publication.json"
    receipt = json.loads(journal.read_text(encoding="utf-8")) if journal.exists() else {}
    if receipt.get("state") == "applying" and resuming:
        raise AgentBusy("publication_recovery_required")
    if receipt.get("state") == "applied" and receipt.get("head") == artifact["head"]:
        artifact = {**artifact, "applied_head": artifact["head"]}
    return artifact


def recover_owner(store, identity, row):
    """Called with the dead owner's OS lease, before terminal settlement."""
    artifact = row.get("artifact")
    if not artifact and row["spec"].get("isolation") == "worktree":
        path = store.directory / "artifacts" / resource_id(identity) / "artifact.json"
        if path.exists():
            artifact = json.loads(path.read_text(encoding="utf-8"))
    if artifact:
        from engine.agent_workspaces import collect, prepare
        artifact = prepare(identity, row["spec"], {"artifact": artifact})
        artifact = collect(artifact)
        store.artifact(identity, artifact)
