"""Independent installation and host-service ownership are executable contracts."""
from __future__ import annotations

import ast
from pathlib import Path
import tomllib

import pytest

from engine.query_engine import build_default_engine
from engine.runtime_services import RuntimeServices


def test_engine_has_no_transport_imports():
    root = Path(__file__).resolve().parents[1] / "engine"
    violations = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            names = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                     [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            for name in names:
                if name.split(".")[0] in {"server", "fastapi", "uvicorn", "cli"}:
                    violations.append(f"{path.name}:{node.lineno}: {name}")
    assert not violations, violations


def test_packaging_separates_engine_and_product_requirements():
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    base = data["project"]["dependencies"]
    assert {x.split(">=")[0] for x in base} == {"httpx", "pydantic", "tokenizers"}
    extras = data["project"]["optional-dependencies"]
    assert any(x.startswith("typer") for x in extras["cli"])
    assert any(x.startswith("fastapi") for x in extras["server"])
    assert any(x.startswith("uvicorn") for x in extras["product"])
    includes = data["tool"]["setuptools"]["packages"]["find"]["include"]
    assert {"coord*", "lsp*", "sidecar*", "xeyo*"} <= set(includes)
    assert "evals*" not in includes


class Jobs:
    def __init__(self, marker):
        self.marker = marker
        self.calls = []

    def snapshot_list(self, session_id):
        self.calls.append(session_id)
        return [{"job_id": self.marker, "status": "running", "owner_session_id": session_id}]


@pytest.mark.asyncio
async def test_injected_jobs_stay_per_engine_through_verification_and_recovery(tmp_path):
    left, right = Jobs("left-job"), Jobs("right-job")
    engines = [build_default_engine(cwd=str(tmp_path), model_backend="fake",
               session_id=sid, runtime_services=RuntimeServices(jobs=jobs),
               runtime_checkpoint=True, runtime_verify=True)
               for sid, jobs in (("left", left), ("right", right))]
    for engine, jobs in zip(engines, (left, right)):
        events = [e async for e in engine.submit("hello")]
        assert events[-1].type == "result" and not events[-1].is_error
        snapshot = engine.runtime_snapshot()
        assert snapshot["jobs"][0]["job_id"] == jobs.marker
        assert snapshot["verification"]["checked"] is True
        assert snapshot["verification"]["active_jobs"] == 1
        assert engine.runtime_recovery()["checked"] is True
    assert set(left.calls) == {"left"}
    assert set(right.calls) == {"right"}


@pytest.mark.asyncio
async def test_injected_inbox_delivers_only_its_engine_at_sampling_boundary(tmp_path, monkeypatch):
    from engine import t_now_inbox
    from server.inbox_registry import InboxRegistry

    monkeypatch.setenv("XEYO_INBOX_BOUNDARY", "1")
    monkeypatch.setattr(t_now_inbox, "_registry", lambda: pytest.fail("implicit host lookup"))
    inbox = InboxRegistry()
    inbox.enqueue("target", "queued input", message_id="queued-1")
    inbox.enqueue("other", "unrelated input", message_id="queued-2")
    engine = build_default_engine(cwd=str(tmp_path), model_backend="fake", session_id="target",
                                  runtime_services=RuntimeServices(inbox=inbox))
    events = [e async for e in engine.submit("initial input")]
    delivered = [e for e in events if e.type == "steer_delivered"]
    assert len(delivered) == 1 and delivered[0].message_ids == ("queued-1",)
    assert inbox.peek("target") is None
    assert inbox.peek("other").message_id == "queued-2"
    assert any(e.type == "final" and e.text == "ok: queued input" for e in events)


def test_product_adapter_resolves_current_registry_without_owning_it(monkeypatch):
    from server import job_registry
    from server.engine_services import product_runtime_services

    host = product_runtime_services()
    first, second = Jobs("first"), Jobs("second")
    monkeypatch.setattr(job_registry, "get_job_registry", lambda: first)
    assert host.job_snapshots("session")[0]["job_id"] == "first"
    monkeypatch.setattr(job_registry, "get_job_registry", lambda: second)
    assert host.job_snapshots("session")[0]["job_id"] == "second"


@pytest.mark.parametrize("entry", ["http", "cli"])
def test_product_entry_points_inject_host_services(entry, tmp_path, monkeypatch):
    from server import job_registry
    jobs = Jobs("product-job")
    monkeypatch.setattr(job_registry, "get_job_registry", lambda: jobs)
    if entry == "http":
        from server.session_pool import ModelConfig, SessionPool
        pool = SessionPool(cwd=str(tmp_path))
        engine = pool.get_or_create("product-session", ModelConfig("fake", "", "", "fake"))
    else:
        from cli.chat_cmd import build_chat_engine
        engine, _ = build_chat_engine(cwd=str(tmp_path), session_id="product-session",
                                      provider="fake", model="fake", api_key="", base_url="")
    assert engine.runtime_snapshot()["jobs"][0]["job_id"] == "product-job"
    assert jobs.calls == ["product-session"]


def test_unbound_runner_requires_explicit_host_composition(monkeypatch):
    from engine import turn_runner
    monkeypatch.setattr(turn_runner, "_runner", None)
    with pytest.raises(RuntimeError, match="bind_turn_runner"):
        turn_runner.get_turn_runner()
    pool = object()
    runner = turn_runner.bind_turn_runner(pool)
    assert turn_runner.get_turn_runner() is runner


def test_embedded_jobs_do_not_consult_product_registry(tmp_path, monkeypatch):
    from server import job_registry
    monkeypatch.setattr(job_registry, "get_job_registry", lambda: pytest.fail("product lookup"))
    engine = build_default_engine(cwd=str(tmp_path), model_backend="fake")
    assert engine.runtime_snapshot()["jobs"] == []


def test_host_snapshot_failure_retains_existing_fail_open_boundary(tmp_path):
    class BrokenJobs:
        def snapshot_list(self, session_id):
            raise OSError("host unavailable")
    engine = build_default_engine(cwd=str(tmp_path), model_backend="fake",
                                  runtime_services=RuntimeServices(jobs=BrokenJobs()),
                                  runtime_checkpoint=True)
    assert engine.runtime_snapshot()["jobs"] == []
    assert engine.runtime_recovery()["state"] == "unavailable"


def test_legacy_and_public_exports_are_identical():
    import xeyo
    import cli
    from engine.query_engine import QueryEngine
    from common.version import engine_version
    assert xeyo.QueryEngine is QueryEngine
    assert xeyo.build_default_engine is build_default_engine
    assert xeyo.RuntimeServices is RuntimeServices
    assert xeyo.__version__ == cli.__version__ == engine_version()
