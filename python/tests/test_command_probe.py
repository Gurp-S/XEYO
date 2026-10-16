"""Compare the optimization to the system lookup, including failure paths."""
import os
import shutil

import pytest

from engine.command_probe import probe_commands


GROUPS = {"git": ("git",), "node": ("node",), "compiler": ("cc", "clang", "cl")}


def reference():
    return {key: any(shutil.which(name) for name in names) for key, names in GROUPS.items()}


def executable(directory, name):
    path = directory / (name + (".EXE" if os.name == "nt" else ""))
    path.write_text("fixture", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_matches_standard_lookup_and_observes_installs_and_deletions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.setenv("PATH", os.pathsep.join([str(first), str(second), str(first), str(tmp_path / 'missing')]))
    monkeypatch.setenv("PATHEXT", ".EXE;.CMD")
    (first / "git.EXE").mkdir()  # A directory is not an executable.
    installed = executable(second, "git")
    assert probe_commands(GROUPS) == reference()
    assert probe_commands(GROUPS)["git"]
    installed.unlink()
    assert probe_commands(GROUPS) == reference()
    assert not probe_commands(GROUPS)["git"]
    executable(second, "node")
    assert probe_commands(GROUPS) == reference()
    assert probe_commands(GROUPS)["node"]


@pytest.mark.parametrize("path", ["", os.pathsep, None])
def test_empty_missing_and_current_directory_path_semantics(tmp_path, monkeypatch, path):
    monkeypatch.chdir(tmp_path)
    executable(tmp_path, "git")
    if path is None:
        monkeypatch.delenv("PATH", raising=False)
    else:
        monkeypatch.setenv("PATH", path)
    assert probe_commands(GROUPS) == reference()


def test_unlistable_directory_keeps_standard_execution_check(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    executable(tmp_path, "node")
    def denied(_):
        raise PermissionError("enumeration denied")
    monkeypatch.setattr(os, "scandir", denied)
    assert probe_commands(GROUPS) == reference()
    assert probe_commands(GROUPS)["node"]


@pytest.mark.skipif(os.name != "nt", reason="Windows executable extensions")
def test_custom_pathext_and_case_are_decided_by_shutil(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("PATHEXT", ".XYE")
    (tmp_path / "NoDe.xye").write_text("fixture")
    assert probe_commands(GROUPS) == reference()
    assert probe_commands(GROUPS)["node"]


@pytest.mark.skipif(os.name != "nt", reason="Windows PATH prefilter")
def test_explicit_current_directory_survives_filtering(tmp_path, monkeypatch):
    from engine.command_probe import _candidate_paths
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path / "missing") + os.pathsep)
    executable(tmp_path, "node")
    # Explicit current-directory entries still apply on Python versions that
    # can disable the implicit current-directory search.
    assert os.curdir in _candidate_paths(("node",))["node"].split(os.pathsep)
    assert probe_commands(GROUPS) == reference()


@pytest.mark.skipif(os.name != "nt", reason="Windows PATH prefilter")
def test_large_directory_falls_back_without_losing_an_executable(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    monkeypatch.setenv("PATH", str(tmp_path))
    executable(tmp_path, "node")
    @contextmanager
    def large(_):
        yield (SimpleNamespace(name=f"unrelated-{index}") for index in range(5000))
    monkeypatch.setattr(os, "scandir", large)
    assert probe_commands(GROUPS) == reference()
    assert probe_commands(GROUPS)["node"]
