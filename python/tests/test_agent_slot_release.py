"""子代理并发槽的归还不变量：拿到槽之后任何逃逸都必须把槽还回去。

事故（本轮实测）：``AgentTool.execute`` 在 ``_agent_slots.acquire()`` 之后、
主 ``try:`` 之前有 70 行裸代码（imports / scope 规范化 / 注册 live agent /
``record_agent_tool_start`` 落盘 / 发卡片）。其中 ``record_agent_tool_start``
往 ``~/.xeyo/metrics/multi_agent.jsonl`` 追加一行，写不下去时抛 OSError
（本测试用"父目录是普通文件"复现，等价于真实世界里的磁盘/句柄故障）。
异常从裸段逃逸 ⇒ 主 ``finally`` 根本不执行 ⇒ **每次失败永久烧掉 1/8 个槽**，
烧完之后再 spawn 一律得到 "max concurrent agents reached"，而桌面 app
一开就是几天——多 agent 能力从此静默失效。

修法：把这段纳入 ``try/except BaseException`` —— 只保证还槽，异常原样上抛。

方向性都钉：
- 失败路径必须还槽（缺陷回归）；
- 成功/异常穿透路径不得多还（重复 release 会让槽数越涨越大，等于放开并发上限）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import tools.agent_tool.agent_tool as at
from engine.abort import AbortController
from tools.agent_tool.agent_tool import AgentTool

ROOT = Path(at.__file__).resolve()


class _SpawnSentinel(BaseException):
    """真要走子代理 = 测量失败（也保证绝不发厂商请求）。"""


def _no_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    async def sentinel(self, *args, **kwargs):
        raise _SpawnSentinel

    monkeypatch.setattr(AgentTool, "_run_subagent", sentinel, raising=False)


@pytest.fixture()
def slot_state(monkeypatch: pytest.MonkeyPatch):
    """快照并复原全局槽位，避免一条测试把后续测试的并发上限压低。"""
    start = at._agent_slots._value
    yield start
    at._agent_slots._value = start


def _broken_metrics_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("x", encoding="utf-8")
    monkeypatch.setenv("XEYO_METRICS_DIR", str(blocked / "metrics"))


async def _spawn(tool: AgentTool) -> tuple[str, BaseException | None]:
    try:
        await tool.execute(
            {
                "task_id": "t-probe",
                "desc": "d",
                "scope": ["src/a.txt"],
                "required_tools": ["Read"],
            },
            AbortController(),
        )
    except BaseException as exc:  # noqa: BLE001 — 本测试就是要看它抛什么
        return type(exc).__name__, exc
    return "none", None


async def test_spawn_setup_failure_returns_the_slot(
    tmp_path, monkeypatch, slot_state
) -> None:
    """缺陷回归：起点记账写不下去时，槽位必须原样回来。"""
    _no_spawn(monkeypatch)
    _broken_metrics_dir(tmp_path, monkeypatch)
    tool = AgentTool(cwd=str(tmp_path), session_id="probe")

    kind, exc = await _spawn(tool)
    assert kind != "none", "这条路径本该抛出（否则测不到早退分支）"
    assert not isinstance(exc, _SpawnSentinel), "绝不真起子代理"
    assert at._agent_slots._value == slot_state, (
        f"槽位泄漏：起点 {slot_state} → 现在 {at._agent_slots._value}"
    )


async def test_repeated_setup_failures_do_not_accumulate(
    tmp_path, monkeypatch, slot_state
) -> None:
    """烧槽是累加的：连打 6 次后槽数仍不许变。"""
    _no_spawn(monkeypatch)
    _broken_metrics_dir(tmp_path, monkeypatch)
    tool = AgentTool(cwd=str(tmp_path), session_id="probe")
    for _ in range(6):
        await _spawn(tool)
    assert at._agent_slots._value == slot_state


async def test_base_exception_also_returns_the_slot(
    tmp_path, monkeypatch, slot_state
) -> None:
    """还槽必须挂在 BaseException 上：KeyboardInterrupt / CancelledError 同罪。"""
    _no_spawn(monkeypatch)
    monkeypatch.setattr(
        at.AgentTool,
        "_tools_for",
        lambda self, agent_input: (_ for _ in ()).throw(KeyboardInterrupt()),
        raising=False,
    )
    tool = AgentTool(cwd=str(tmp_path), session_id="probe")
    with pytest.raises(KeyboardInterrupt):
        await tool.execute({"task_id": "t2", "desc": "d"}, AbortController())
    assert at._agent_slots._value == slot_state


async def test_normal_escape_releases_exactly_once(
    tmp_path, monkeypatch, slot_state
) -> None:
    """反向：走到主 finally 的路径不许多还（多还=并发上限被悄悄放开）。"""
    _no_spawn(monkeypatch)
    monkeypatch.setenv("XEYO_METRICS_DIR", str(tmp_path / "metrics"))
    tool = AgentTool(cwd=str(tmp_path), session_id="probe")
    for _ in range(5):
        kind, exc = await _spawn(tool)
        assert isinstance(exc, _SpawnSentinel), (kind, exc)
    assert at._agent_slots._value == slot_state


def test_acquire_is_inside_the_guarded_region() -> None:
    """结构门：``acquire`` 成功后第一段代码必须已经在 try 里，且该 try 带
    ``BaseException`` 兜底并调用 ``release``。

    这条钉的是"下一次有人在段里加会抛的语句时，槽仍会回来"——只看某一次
    故障的回归测试挡不住那种搬家。
    """
    src = ROOT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "execute"
    )
    acquires = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and ast.unparse(n.func) == "_agent_slots.acquire"
    ]
    releases = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and ast.unparse(n.func) == "_agent_slots.release"
    ]
    assert len(acquires) == 1, acquires
    assert len(releases) >= 2, releases

    acquire_line = acquires[0].lineno
    outer = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Try) and n.lineno > acquire_line
    ]
    # 第一个包住"裸段"的 try：起始行紧跟 acquire 的 if 块之后，且带 BaseException 分支
    guards = [
        t for t in outer
        if any(
            h.type is not None and ast.unparse(h.type) == "BaseException"
            for h in t.handlers
        )
    ]
    assert guards, "acquire 之后必须有 BaseException 兜底"
    first = min(guards, key=lambda t: t.lineno)
    assert first.lineno - acquire_line <= 12, (first.lineno, acquire_line)
    handler = next(h for h in first.handlers if ast.unparse(h.type) == "BaseException")
    handler_body = ast.unparse(ast.Module(body=handler.body, type_ignores=[]))
    assert "_agent_slots.release()" in handler_body, handler_body
    assert "raise" in handler_body, "兜底只还槽，必须原样上抛（不许吞异常）"


async def test_finally_cleanup_cannot_block_the_release(
    tmp_path, monkeypatch, slot_state
) -> None:
    """finally 里的收尾步骤抛错，也不许挡住还槽（本轮刚修的同形缺陷）。

    现在 finally 是「结算留痕 → unregister_live_agent → 结束记账留痕 → release」，
    中间那句 ``unregister_live_agent`` 没有被包起来：它一抛，release 就永远轮不到。
    """
    import engine.live_agents as live

    _no_spawn(monkeypatch)
    monkeypatch.setenv("XEYO_METRICS_DIR", str(tmp_path / "metrics"))

    def boom(session_id, agent_id):
        raise OSError("live-agent table unwritable")

    monkeypatch.setattr(live, "unregister_live_agent", boom, raising=False)
    tool = at.AgentTool(cwd=str(tmp_path), session_id="probe")
    # 修好后：注销的故障被收下并留痕，原先在飞的异常照常上抛（不吞）。
    with pytest.raises(_SpawnSentinel):
        await tool.execute({"task_id": "t3", "desc": "d"}, AbortController())
    assert at._agent_slots._value == slot_state, (
        f"finally 中途抛错吃掉了还槽：{slot_state} -> {at._agent_slots._value}"
    )
