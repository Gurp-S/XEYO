"""Edge regression for the jobs / control routers (background-task + operator surface).

Proven defect (fixed): jobs routes normalize the caller session id with ``strip()``
before it selects records in the shared in-process registry, so ``"victim "`` folds
onto ``"victim"`` and reads another session's job snapshot / output. Accepted fix:
edge validation to a sanitizer fixed point -> 422, never silent sanitization.

Everything else here is proven-safe-by-execution coverage: control's resolve family
must report not-found (ok:false) instead of fabricating ok:true, its report route must
reach the filesystem only through the fixed generator path, and interrupt's always-ok
is the documented idempotent stop contract.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Redirect every writable root to an OS-temp dir BEFORE any server import so the
# real store under the home dir is never written and the repo worktree stays clean.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
	sys.path.insert(0, str(_ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="xeyo_jobs_ctrl_edges_"))
os.environ["XEYO_DATA_DIR"] = str(_TMP / "data")
os.environ["XEYO_SESSIONS_DIR"] = str(_TMP / "sessions")
os.environ["XEYO_DIAGNOSTICS_DIR"] = str(_TMP / "diagnostics")
os.environ["XEYO_UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["XEYO_GRANT_STORE"] = str(_TMP / "grants.json")
os.environ["XEYO_GRANT_PERSIST"] = "off"
os.environ["XEYO_ALLOW_REMOTE_CONTROL"] = ""

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.job_registry import get_job_registry  # noqa: E402
from server.routers.control import router as control_router  # noqa: E402
from server.routers.jobs import router as jobs_router  # noqa: E402
from server.routers.sessions import require_session_id  # noqa: E402

app = FastAPI()
app.include_router(jobs_router)
app.include_router(control_router)


@pytest.fixture
def client():
	return TestClient(app)


@pytest.fixture
def seeded():
	"""Register one owner job directly in the shared registry; return (owner, jid)."""
	reg = get_job_registry()
	owner = "victim"
	jid, err = reg._register(kind="bash", label="secret-run", owner_session_id=owner)
	assert jid is not None, err
	reg._push(jid, "top-secret-output-line")
	reg.settle(jid, "succeeded", "")
	return owner, jid


# ---------------------------------------------------------------------------
# jobs.py: whitespace aliasing over the shared registry (the proven defect)
# ---------------------------------------------------------------------------

def test_list_jobs_owner_ok(client, seeded):
	owner, jid = seeded
	r = client.get(f"/v1/sessions/{owner}/jobs")
	assert r.status_code == 200
	body = r.json()
	assert any(j.get("job_id") == jid for j in body["jobs"])


def test_list_jobs_trailing_space_alias_blocked(client, seeded):
	# "victim " strips to "victim" in the registry query -> would leak before the fix.
	r = client.get("/v1/sessions/victim%20/jobs")
	assert r.status_code == 422
	assert "victim" not in r.text


def test_list_jobs_trailing_dot_alias_blocked(client, seeded):
	r = client.get("/v1/sessions/victim%2E/jobs")
	assert r.status_code == 422


def test_list_jobs_colon_variant_blocked(client, seeded):
	# "vi:ctim" normalizes to "vi__ctim": not a fixed point -> rejected.
	r = client.get("/v1/sessions/vi%3Actim/jobs")
	assert r.status_code == 422


def test_list_jobs_wellformed_unknown_is_empty(client, seeded):
	owner, jid = seeded
	r = client.get("/v1/sessions/xeyo-not-a-real-one/jobs")
	assert r.status_code == 200
	body = r.json()
	assert body["jobs"] == []


def test_job_output_owner_ok(client, seeded):
	owner, jid = seeded
	r = client.get(f"/v1/sessions/{owner}/jobs/{jid}/output")
	assert r.status_code == 200
	body = r.json()
	assert body["job_id"] == jid
	assert "top-secret-output-line" in body["text"]


def test_job_output_trailing_space_alias_blocked(client, seeded):
	owner, jid = seeded
	r = client.get(f"/v1/sessions/victim%20/jobs/{jid}/output")
	assert r.status_code == 422


def test_job_output_cross_owner_denied(client, seeded):
	_owner, jid = seeded
	# Well-formed but different owner: exact owner check -> 404, no leak.
	r = client.get(f"/v1/sessions/attacker-1/jobs/{jid}/output")
	assert r.status_code == 404


def test_job_output_unknown_job_404(client, seeded):
	owner, _jid = seeded
	r = client.get(f"/v1/sessions/{owner}/jobs/bash-999999/output")
	assert r.status_code == 404


# ---------------------------------------------------------------------------
# sanitizer fixed-point matrix (blank / NUL / overlong reach the validator)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
	"bad",
	[
		"",
		"   ",
		"..",
		".",
		"victim ",
		" victim",
		"victim.",
		".victim",
		"vi:ctim",
		"a" * 200,
		"x\x00y",
		"a/b",
		"a\\b",
		"/etc/passwd",
	],
)
def test_require_session_id_rejects_ambiguous(bad):
	with pytest.raises(HTTPException) as exc:
		require_session_id(bad)
	assert exc.value.status_code == 422


@pytest.mark.parametrize(
	"bad", ["vi:ctim", "a.b_c-d:e", "pure:colon"]
)
def test_require_session_id_rejects_colon_non_fixed_point(bad):
	# ':' normalizes to '__' -> not a fixed point, so even well-formed-looking
	# colon ids are rejected rather than silently mapped onto another record.
	with pytest.raises(HTTPException) as exc:
		require_session_id(bad)
	assert exc.value.status_code == 422


@pytest.mark.parametrize("good", ["victim", "xeyo-ab12cd34ef56", "a.b_c-d1", "job-1"])
def test_require_session_id_accepts_fixed_points(good):
	assert require_session_id(good) == good


# ---------------------------------------------------------------------------
# control.py: proven-safe-by-execution coverage
# ---------------------------------------------------------------------------

def test_interrupt_unknown_is_idempotent_ok(client):
	# Documented stop contract: an unknown/idle session returns ok:true, never 500.
	r = client.post("/v1/interrupt", json={"session_id": "never-seen-sess"})
	assert r.status_code == 200
	assert r.json().get("ok") is True


def test_interrupt_whitespace_id_does_not_crash(client):
	# Registry/pool lookups are exact-key, so "victim " never acts on "victim";
	# the route must return the idempotent ok, not a 500.
	r = client.post("/v1/interrupt", json={"session_id": "victim "})
	assert r.status_code == 200
	assert r.json().get("ok") is True


def test_permission_resolve_unknown_reports_not_found(client):
	r = client.post(
		"/v1/permission/resolve",
		json={"request_id": "no-such-request-xyz", "approved": True},
	)
	assert r.status_code == 200
	assert r.json().get("ok") is False


def test_ask_resolve_unknown_reports_not_found(client):
	r = client.post(
		"/v1/ask/resolve",
		json={"request_id": "no-such-ask-xyz", "answer": "hello"},
	)
	assert r.status_code == 200
	assert r.json().get("ok") is False


def test_plan_approve_unknown_reports_not_found(client):
	r = client.post("/v1/plan/no-such-turn-xyz/approve", json={"approved": True})
	assert r.status_code == 200
	assert r.json().get("ok") is False


def test_revoke_unknown_grant_reports_not_found(client):
	r = client.delete("/v1/permissions/grants/deadbeefdeadbeef")
	assert r.status_code == 200
	assert r.json().get("ok") is False


def test_report_routes_use_fixed_path_not_caller_path(client):
	# No caller-supplied path: report metadata returns ok/exists; view is 200 or 404
	# (file present or not) -- never an arbitrary read, never a 500.
	meta = client.get("/v1/settings/memory/report")
	assert meta.status_code == 200
	assert "exists" in meta.json()
	view = client.get("/v1/settings/memory/report/view")
	assert view.status_code in (200, 404)
