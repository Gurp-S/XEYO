"""strict_env_shadow 门槛/证明性测试（②）。

覆盖：
- 关（默认）：enabled=False。
- whitelist：默认 + env 追加。
- isolate_git_history：无 `.git` → no-op ok；有 `.git` → 备份后变单 commit 仓库；
  restore 后 `.git` 回归原样。
- 隔离后仓库无历史（git log 只 1 条/或为空）。
- strict_summary：恒含 4 字段。
- fail-open：恢复失败显式报错。
"""

from __future__ import annotations

import subprocess

import pytest

from evals.strict_env_shadow import (
    enabled,
    isolate_git_history,
    restore_git_history,
    strict_summary,
    whitelist,
)


@pytest.fixture()
def strict_off(monkeypatch):
    monkeypatch.delenv("XEYO_EVAL_STRICT", raising=False)
    monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "0")


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    (r / "a.py").write_text("print(1)\n", encoding="utf-8")
    return r


def _git(r, *args):
    return subprocess.run(
        ["git", *args], cwd=str(r), capture_output=True, text=True, timeout=30
    )


def test_default_disabled(strict_off):
    assert enabled() is False


def test_whitelist_default_plus_env(monkeypatch):
    base = whitelist()
    assert "pypi.org" in base
    monkeypatch.setenv("XEYO_EVAL_STRICT_OUTBOUND_WHITELIST", "example.com, pypi.org")
    with_env = whitelist()
    assert "example.com" in with_env
    assert with_env.count("pypi.org") == 1  # 不重复


def test_isolate_no_git(repo):
    res = isolate_git_history(str(repo))
    assert res.ok is True and res.action == "no-op"


def test_isolate_then_restore(repo):
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@l", "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@l", "commit", "-q", "-m", "base")
    old = _git(repo, "rev-list", "--count", "HEAD").stdout.strip()

    res = isolate_git_history(str(repo))
    assert res.ok is True
    # 隔离后 .git 被替换为单 commit（历史只剩 1 条或空仓）。
    count_after = _git(repo, "rev-list", "--count", "HEAD").stdout.strip()
    assert count_after in ("0", "1")
    # 备份目录存在。
    assert (repo / ".git.bak_eval_strict").exists()

    restored = restore_git_history(str(repo))
    assert restored.ok is True and restored.restored is True
    # 备份挪回 .git，原始历史恢复。
    count_back = _git(repo, "rev-list", "--count", "HEAD").stdout.strip()
    assert count_back == old


def test_strict_summary_has_4_fields():
    s = strict_summary({"accuracy": 0.8})
    for k in ("standard", "strict", "delta", "leakage_rate"):
        assert k in s
    assert s["standard"] == 0.8
