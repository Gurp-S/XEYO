"""v4 索引对账（sync_index_from_ledger）契约测试。

背景：rewind v3 热路径每轮两次全工作区扫描（turn 起始 lstat 基线 +
turn 结束二次全树比对），大仓库把首 token 与收尾拖慢数百 ms～秒级
（2026-09-09 审计 + 受控基准）。v4 以**索引账本自身**的 (size,mtime)
签名为基线（账本即基线，checkpoint 冻结本就只读账本），变更发现改用
git 增量（workspace 即 git worktree 顶层时，``git status --porcelain -z``，
成本靠 git 的 index/stat cache）；非 git 工作区退化为单次全树 walk。

本文件锁死两条语义：
1. 账本基线对账：新建/修改/删除都能被发现并落账，无需 turn 起始基线。
2. git 增量路径与账本语义一致：user gitignore 掉的账本路径（git status
   不报）仍会被定向 lstat 发现——不因换发现机制而丢账本语义。

运行:
  py -3.11 -m pytest tests/test_rewind_index_v4.py -q
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from rewind.index import AgentFileIndex, sync_index_from_ledger
from rewind.snapshot import SnapshotStore

_HAVE_GIT = subprocess.run(
    ["git", "--version"], capture_output=True
).returncode == 0


def _make_ws(tmp_path: Path, name: str) -> Path:
    ws = tmp_path / name
    ws.mkdir()
    return ws


def _entries(paths: dict[str, str], ws: Path) -> None:
    for rel, content in paths.items():
        full = ws / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")


def test_ledger_sync_detects_create_modify_delete(tmp_path) -> None:
    """账本即基线：无 turn 起始扫描也能发现新建/修改/删除。"""
    ws = _make_ws(tmp_path, "ws-plain")
    sid = "v4-plain"
    idx = AgentFileIndex(sid)
    snaps = SnapshotStore(sid)

    # 首轮：空账本 → 全量入库。
    _entries({"a.txt": "one", "dir/b.txt": "two"}, ws)
    r = sync_index_from_ledger(sid, snapshots=snaps, workspace_root=ws)
    assert r["upserted"] == 2 and r["removed"] == 0 and not r["failed"]
    e = idx.entries()
    assert set(e) == {"a.txt", "dir/b.txt"}
    a0 = e["a.txt"]
    assert a0.content_hash and a0.source == "turn_diff"

    # 修改 a.txt + 删除 dir/b.txt + 新建 c.txt → 只对这些路径落账。
    (ws / "a.txt").write_text("one-changed", encoding="utf-8")
    (ws / "dir/b.txt").unlink()
    _entries({"c.txt": "three"}, ws)
    r = sync_index_from_ledger(sid, snapshots=snaps, workspace_root=ws)
    assert r["upserted"] == 2 and r["removed"] == 1
    e = idx.entries()
    assert set(e) == {"a.txt", "c.txt", "dir/b.txt"}
    assert e["a.txt"].content_hash != a0.content_hash
    assert e["dir/b.txt"].content_hash is None  # 删除标记
    # blob 内容可回溯（快照真的落盘了）。
    assert snaps.get_text(e["a.txt"].content_hash) == "one-changed"


@pytest.mark.skipif(not _HAVE_GIT, reason="git 不可用")
def test_git_workspace_uses_fast_path_and_keeps_ignored_semantics(tmp_path) -> None:
    """git 顶层工作区：git 增量发现 + user-gitignore 账本路径不丢语义。"""
    ws = _make_ws(tmp_path, "ws-git")
    subprocess.run(["git", "-C", str(ws), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(ws), "config", "user.email", "t@t"], check=True
    )
    subprocess.run(
        ["git", "-C", str(ws), "config", "user.name", "t"], check=True
    )
    sid = "v4-git"
    idx = AgentFileIndex(sid)
    snaps = SnapshotStore(sid)

    # 首轮：账本入库 a.txt + secret.env（此时尚无 .gitignore，git 都认）。
    _entries({"a.txt": "one", "secret.env": "s3cret"}, ws)
    r = sync_index_from_ledger(sid, snapshots=snaps, workspace_root=ws)
    assert r["upserted"] == 2 and not r["failed"]
    assert set(idx.entries()) == {"a.txt", "secret.env"}

    # 用户随后 gitignore 掉 secret.env 并手改它 + 改 a.txt + 加 .gitignore。
    _entries({".gitignore": "secret.env\n", "a.txt": "one-v2"}, ws)
    (ws / "secret.env").write_text("s3cret-v2", encoding="utf-8")
    r = sync_index_from_ledger(sid, snapshots=snaps, workspace_root=ws)
    assert not r["failed"]
    e = idx.entries()
    assert set(e) == {"a.txt", ".gitignore", "secret.env"}
    assert e["secret.env"].content_hash is not None
    assert snaps.get_text(e["secret.env"].content_hash) == "s3cret-v2"
    assert snaps.get_text(e["a.txt"].content_hash) == "one-v2"

    # gitignore 掉的账本路径被删除 → 定向 lstat 仍发现并记删除（不丢）。
    (ws / "secret.env").unlink()
    r = sync_index_from_ledger(sid, snapshots=snaps, workspace_root=ws)
    assert not r["failed"]
    assert idx.entries()["secret.env"].content_hash is None

    # 子目录仓库（非顶层）不走 git 快速路径 → 也能正常对账（walk 兜底）。
    sub = ws / "subrepo"
    sub.mkdir()
    subprocess.run(["git", "-C", str(sub), "init", "-q"], check=True)
    _entries({"x.txt": "x"}, sub)
    r = sync_index_from_ledger(sid, snapshots=snaps, workspace_root=sub)
    assert not r["failed"]
    assert set(idx.entries()) >= {"x.txt"}


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
