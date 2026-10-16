"""Rollback-mode fixtures; managed-runtime contracts live in test_agent_runtime_v2."""
import pytest


@pytest.fixture(autouse=True)
def legacy_agent_runtime(monkeypatch):
    monkeypatch.setenv("XEYO_AGENT_RUNTIME_V2", "0")
