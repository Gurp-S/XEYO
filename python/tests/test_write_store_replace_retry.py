"""Windows 目标被持有时的原子写退化路径（2026-10-05，当日活体会话实测 7 次 WinError 5）。

本地双进程句柄实验：目标文件被普通 open 持有 ⇒ ``os.replace`` 抛
PermissionError(WinError 5)，而 ``open(path, "wb")`` 原地写成功。契约：

1. 瞬时占用（首个 replace 失败）⇒ 短重试后仍走 replace（保住原子性）；
2. 持续占用 ⇒ 回落原地写：内容正确、tmp 清理、warning 出声；
3. 非占用类 OSError ⇒ 不重试不回落，首个即抛（不许把真错误吞成"写成功"）；
4. 回落分支仅 Windows 生效（POSIX 的 replace 失败不是句柄问题，保持原语义）。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from engine.write_store import WriteStore


def _call(tmp_path: Path, content: str = "hello\n") -> None:
    WriteStore._atomic_write(tmp_path / "t.txt", content, "utf-8")


def test_replace_retry_recovers_from_transient_lock(tmp_path, monkeypatch):
    calls = {"n": 0}
    real_replace = os.replace

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(13, "拒绝访问")
        return real_replace(src, dst)

    monkeypatch.setattr("engine.write_store.os.replace", flaky)
    _call(tmp_path)
    assert (tmp_path / "t.txt").read_text(encoding="utf-8") == "hello\n"
    assert calls["n"] == 2, "瞬时占用必须在重试里恢复，不许直接走回落"
    assert not list(tmp_path.glob("*.xeyo.write.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="回落原地写只在 Windows 生效")
def test_in_place_fallback_when_replace_permanently_blocked(
    tmp_path, monkeypatch, caplog
):
    def blocked(src, dst):
        raise PermissionError(13, "拒绝访问")

    monkeypatch.setattr("engine.write_store.os.replace", blocked)
    with caplog.at_level(logging.WARNING, logger="engine.write_store"):
        _call(tmp_path)
    assert (tmp_path / "t.txt").read_text(encoding="utf-8") == "hello\n"
    assert not list(tmp_path.glob("*.xeyo.write.tmp")), "回落成功后不许留 tmp 垃圾"
    assert any("in place" in r.getMessage() for r in caplog.records), (
        "回落必须出声（warning），不许静默降级"
    )


def test_non_lock_oserror_propagates_immediately(tmp_path, monkeypatch):
    calls = {"n": 0}

    def boom(src, dst):
        calls["n"] += 1
        raise OSError("disk on fire")

    monkeypatch.setattr("engine.write_store.os.replace", boom)
    with pytest.raises(OSError, match="disk on fire"):
        _call(tmp_path)
    assert calls["n"] == 1, "非占用类错误不许重试"
    assert not (tmp_path / "t.txt").exists()


def test_healthy_path_uses_replace_once(tmp_path, monkeypatch):
    """方向控制：健康时纯 replace 一次成功、无回落痕迹。"""
    calls = {"n": 0}
    real_replace = os.replace

    def spy(src, dst):
        calls["n"] += 1
        return real_replace(src, dst)

    monkeypatch.setattr("engine.write_store.os.replace", spy)
    _call(tmp_path)
    assert calls["n"] == 1
    assert (tmp_path / "t.txt").read_text(encoding="utf-8") == "hello\n"
