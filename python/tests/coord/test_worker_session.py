"""coord worker_session 离线 e2e：真 QueryEngine 在 worktree 里落盘 → commit →
reconcile → main 出现文件。用注入式 scripted 模型客户端，不联网、不吃厂商额度。

证明接线核心闭环成立：任务卡 → 真会话（fake 后端 + scripted Write tool_use）
→ worktree 产物 → 上交 → 三路合并收敛到 main。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from coord.file_store import CoordFileStore
from coord.reconciler import Reconciler
from coord.store import STATUS_CLAIMED, new_task
from coord.worker_pool import WorkerPool
from coord.worker_session import (
    run_worker_session,
    session_work_fn,
    task_card_text,
    worker_session_id,
)
from coord.worktree import git
from model.chunks import ModelChunk
from msgtypes.message import ToolUse


class WriteScriptedClient:
    """第一轮发 Write tool_use（写 rel_path），第二轮（历史含 assistant Write）发纯文本收尾。"""

    def __init__(self, rel_path: str, content: str) -> None:
        self.rel = rel_path
        self.content = content
        provider = "fake"
        self.provider = provider
        self._provider = provider
        self._model = "scripted"
        self.context_limit = None

    @staticmethod
    def _already_wrote(messages: list[dict]) -> bool:
        for m in messages:
            if m.get("role") == "assistant" and isinstance(m.get("content"), list):
                for b in m["content"]:
                    if (isinstance(b, dict) and b.get("type") == "tool_use"
                            and b.get("name") == "Write"):
                        return True
        return False

    async def stream(self, messages, tools, abort):
        abort.raise_if_aborted()
        if self._already_wrote(messages):
            yield ModelChunk(kind="text_delta", text="written")
            return
        yield ModelChunk(kind="tool_use", tool_use=ToolUse(
            id=f"call_{int(time.time() * 1e6) % 100000:05d}",
            name="Write",
            input={"file_path": self.rel, "content": self.content},
        ))


def _mk_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    for args in (["init", "-b", "main"], ["config", "user.name", "t"],
                 ["config", "user.email", "t@t"], ["config", "core.autocrlf", "false"]):
        git(repo, *args)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "seed")
    return repo


def test_worker_session_id_and_task_card():
    sid = worker_session_id("w1", "task_abcdef123456")
    assert sid.startswith("__worker__w1-")
    assert sid.endswith("123456")
    t = new_task("g", "加登录页", ["src/a.ts"], brief="按设计稿实现", parent_id="task_p")
    t.findings = [{"file": "src/a.ts", "line": 3, "error": "missing test"}]
    card = task_card_text(t)
    assert t.task_id in card and "加登录页" in card and "按设计稿实现" in card
    assert "src/a.ts" in card and "missing test" in card


@pytest.mark.timeout(120)
def test_worker_session_offline_e2e(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))  # 隔离 transcript
    repo = _mk_repo(tmp_path)
    root = str(repo)
    store = CoordFileStore(repo)
    t = new_task("g", "写一个文件", ["generated.txt"],
                 brief="写 generated.txt", max_turns=6)
    store.create_task(t)
    tid = t.task_id
    # 上面 create 保证文件存在；用返回的真实 id 重取
    base = git(repo, "rev-parse", "main").stdout.strip()
    task = store.claim_task(tid, "w1", base)
    assert task is not None and task.status == STATUS_CLAIMED

    # 真会话跑：worktree → build_default_engine(fake) → scripted Write → commit → submit
    pool = WorkerPool(repo, store)
    fn = session_work_fn(task, model_client=WriteScriptedClient("generated.txt", "hello worker\n"))
    outcome = pool.run_task(tid, "w1", fn)
    assert outcome.ok, outcome.error

    # 收敛
    report = Reconciler(repo, store).reconcile_ready()
    assert len(report["merged"]) == 1, report
    assert git(repo, "show", "main:generated.txt").stdout == "hello worker\n"
    # main 线性、无 index.lock
    assert not (repo / ".git" / "index.lock").exists()


@pytest.mark.timeout(120)
def test_worker_session_direct_no_worktree(tmp_path, monkeypatch):
    """run_worker_session 单点：在给定 worktree 起真会话、落盘文件（不经 pool）。"""
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    repo = _mk_repo(tmp_path)
    from coord.worktree import WorktreeManager

    wm = WorktreeManager(repo)
    handle = wm.create("task_direct1", git(repo, "rev-parse", "main").stdout.strip())
    from coord.store import Task

    t = Task(task_id="task_direct1", goal_id="g", title="直写",
             scope=["d.txt"], claimed_by="w2", max_turns=6)
    out = run_worker_session(handle.path, t,
                             model_client=WriteScriptedClient("d.txt", "direct\n"))
    assert out["ok"] is True, out
    assert (handle.path / "d.txt").read_text(encoding="utf-8") == "direct\n"
