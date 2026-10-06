"""子代理收尾的三处静默失败必须留痕（产品从不配 logging handler ⇒ debug 级等于没说）。

事故族（本目标已修过一次同形缺陷：turn 终态广播）：
- ``enqueue_subagent_candidates`` 被 ``except Exception: pass`` 吞掉 ⇒ 子代理交接
  （files_touched / memories）从此不存在，没有任何痕迹；主模型带着"子代理做过事"的
  印象继续写答案，而热缓存里根本没有那份证据。
- ``record_agent_settlement`` / ``record_agent_tool_end`` 失败只记 **debug** ⇒
  在本仓等于没记（``logging`` 从没被配置过 handler，判"有没有留痕"要看级别）。

修法：级别升到 warning（措辞仍是事实型，不含建议），行为零变化。
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from pathlib import Path

import pytest

import tools.agent_tool.agent_tool as at
from engine.abort import AbortController

LOGGER = at.__name__
OUT_FIELDS = SimpleNamespace(
    conclusion="做完了",
    files_touched=["a.py"],
    memories=(),
    is_error=False,
    turns_used=2,
    max_turns=8,
    tokens_used=100,
    cost_cny=None,
    had_write_stale=False,
)


def _ok_subagent(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(self, *args, **kwargs):
        return OUT_FIELDS

    monkeypatch.setattr(at.AgentTool, "_run_subagent", fake, raising=False)


async def _spawn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setenv("XEYO_METRICS_DIR", str(tmp_path / "metrics"))
    tool = at.AgentTool(cwd=str(tmp_path), session_id="trace-probe")
    return await tool.execute(
        {"task_id": "t1", "desc": "d", "scope": ["a.py"]}, AbortController()
    )


async def test_handoff_enqueue_failure_leaves_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """缺陷回归：交接被丢时必须有 warning，否则事后无从知道证据没进热缓存。"""
    _ok_subagent(monkeypatch)

    def boom(*args, **kwargs):
        raise OSError("memory store unwritable")

    monkeypatch.setattr(at, "enqueue_subagent_candidates", boom, raising=False)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        res = await _spawn(tmp_path, monkeypatch)
    assert not res.is_error, str(res.content)[:160]
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("handoff" in m or "enqueue" in m for m in msgs), (
        f"交接失败没留 warning（记录={msgs}）"
    )
    assert any(
        r.exc_info is not None and issubclass(r.exc_info[0], OSError)
        for r in caplog.records
        if r.levelno >= logging.WARNING
    ), f"留痕没带上异常本体（事后无从查哪种故障）：{msgs}"


async def test_end_record_failure_is_warning_not_debug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """``record_agent_tool_end`` 失败要升到 warning（debug 在产品里读不到）。"""
    import usage.multi_agent_metrics as mam

    _ok_subagent(monkeypatch)

    def boom(*args, **kwargs):
        raise OSError("metrics unwritable")

    # execute 里是"局部 import"，钉模块属性没用，必须钉源模块本身。
    monkeypatch.setattr(mam, "record_agent_tool_end", boom, raising=False)
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        await _spawn(tmp_path, monkeypatch)
    hits = [
        r for r in caplog.records
        if "record_agent_tool_end" in r.getMessage() or "agent_tool_end" in r.getMessage()
    ]
    assert hits, "收尾记账失败根本没留痕"
    assert all(r.levelno >= logging.WARNING for r in hits), [
        (r.levelname, r.getMessage()) for r in hits
    ]


async def test_settlement_record_failure_is_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """异常逃逸路径上的结算留痕同样不许停在 debug。

    分支前置自证：逃逸必须是 ``BaseException``——``execute`` 里内层
    ``except Exception`` 会把普通异常收成正经的失败结果，那条路上
    ``sys.exc_info()`` 为空，结算分支根本走不到（上一版就是这么假红的）。
    """
    import engine.agent_settlement as ag

    class _Escaper(BaseException):
        pass

    async def raiser(self, *args, **kwargs):
        raise _Escaper("parent turn aborted")

    monkeypatch.setattr(at.AgentTool, "_run_subagent", raiser, raising=False)
    monkeypatch.setattr(
        ag, "record_agent_settlement",
        lambda *a, **k: (_ for _ in ()).throw(OSError("settlement unwritable")),
        raising=False,
    )
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        with pytest.raises(_Escaper):
            await _spawn(tmp_path, monkeypatch)
    hits = [
        r for r in caplog.records
        if "settlement" in r.getMessage()
    ]
    assert hits, "结算记录失败没留痕"
    assert all(r.levelno >= logging.WARNING for r in hits), [
        (r.levelname, r.getMessage()) for r in hits
    ]


async def test_happy_path_adds_no_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """反向对照：正常收尾不该因为这次改动多出噪声（守卫不能变成"永远叫"）。"""
    _ok_subagent(monkeypatch)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        res = await _spawn(tmp_path, monkeypatch)
    assert not res.is_error, str(res.content)[:160]
    assert [r.getMessage() for r in caplog.records] == [], [
        r.getMessage() for r in caplog.records
    ]
