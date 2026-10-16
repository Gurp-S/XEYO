from __future__ import annotations

import json
import hashlib
from pathlib import Path

from server.session_pool import SessionPool
from session.persistence import transcript_path
from session.transcript_blobs import blob_file, resolve_transcript_row


def test_fork_copies_externalized_bodies_and_workspace_binding(tmp_path, monkeypatch):
	sessions_dir = tmp_path / "sessions"
	workspace = tmp_path / "workspace"
	workspace.mkdir()
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(sessions_dir))
	monkeypatch.setenv("XEYO_TRANSCRIPT_BLOB_THRESHOLD", "512")

	from server.routers import sessions as sessions_module

	pool = SessionPool(cwd=str(workspace))
	monkeypatch.setattr(sessions_module, "_pool", pool)
	source_id = "fork-source"
	pool.pin_session_cwd(source_id, str(workspace))
	source = transcript_path(source_id, sessions_dir=sessions_dir)
	source.parent.mkdir(parents=True, exist_ok=True)
	content = "body-" + "x" * 1500
	payload = json.dumps(content, ensure_ascii=False).encode("utf-8")
	row = {
		"id": "externalized-message",
		"role": "user",
		"content_ref": "externalized-message.json",
		"content_hash": "sha256:" + hashlib.sha256(payload).hexdigest(),
		"content_bytes": len(payload),
	}
	blob_path = blob_file(source, row["id"])
	blob_path.parent.mkdir(parents=True, exist_ok=True)
	blob_path.write_bytes(payload)
	archive = source.with_name(source.name + ".old1")
	source.write_text(json.dumps(row) + "\n", encoding="utf-8")
	archive.write_text(json.dumps(row) + "\n", encoding="utf-8")

	result = sessions_module.fork_session(source_id)
	new_id = result["new_id"]
	destination = transcript_path(new_id, sessions_dir=sessions_dir)
	new_row = json.loads(destination.read_text(encoding="utf-8").splitlines()[0])
	archive_copy = destination.with_name(destination.name + ".old1")
	archived_row = json.loads(archive_copy.read_text(encoding="utf-8").splitlines()[0])

	assert blob_file(destination, row["id"]).is_file()
	assert resolve_transcript_row(new_row, destination, strict=True)["content"] == content
	assert resolve_transcript_row(archived_row, destination, strict=True)["content"] == content
	assert result["cwd"] == str(workspace)
	assert pool.session_cwd(new_id) == str(workspace)
