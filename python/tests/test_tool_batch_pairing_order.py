"""E2E（真 registry + 真权限裁决 + 真编排层，无模型无付费）：并发批次里结果必须与调用**配对且保序**。

`run_tools_partitioned` 对界面与模型同时承诺两件事（其 docstring 第 4、5 条）：
1. 返回列表**按原始 tool_uses 顺序**填充；
2. 给了 ``result_q`` 时"每个工具一完成就 put"。

若并发批次把结果错配到别的 tool_use 上，模型看到的是**张冠李戴的读数**（把 A 的输出当成 B 的结果
继续推理）——这类缺陷不报错，只会让后续每一步都错。

实现说明：替身工具**借用真名**（Read/Glob/Grep）——`permissions/policy.py` 对未知工具默认 ASK，
无应答者时整批会被记成"Approval unavailable"而根本走不到工具（实测踩过）。借真名 ⇒ 裁决走
`read_allow` 放行，被测面只剩编排层，权限层不参与。
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController
from msgtypes.message import ToolUse
from tools.base_tool import ToolResult
from tools.orchestration import run_tools_partitioned
from tools.tool_registry import ToolRegistry

REAL_NAMES = ("Read", "Glob", "Grep")


class _TagTool:
    """以真名注册的替身：内容里带自己的名字，配对错位一眼可见。"""

    def __init__(
        self,
        name: str,
        *,
        safe: bool = True,
        delay: float = 0.0,
        raises: bool = False,
        gate: asyncio.Event | None = None,
        let_go: asyncio.Event | None = None,
        order_out: list[str] | None = None,
    ) -> None:
        self.name = name
        self._safe = safe
        self._delay = delay
        self._raises = raises
        self._gate = gate
        self._let_go = let_go
        self._order_out = order_out if order_out is not None else []

    @staticmethod
    def is_read_only() -> bool:
        return True

    def is_concurrency_safe(self) -> bool:
        return self._safe

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": f"substitute for {self.name}",
            "input_schema": {"type": "object", "properties": {}},
        }

    async def execute(self, input: dict[str, Any], abort: AbortController) -> ToolResult:
        abort.raise_if_aborted()
        if self._let_go is not None:
            self._let_go.set()
        if self._gate is not None:
            try:
                await asyncio.wait_for(self._gate.wait(), timeout=8.0)
            except asyncio.TimeoutError:
                return ToolResult(content=f"{self.name}|GATE_TIMEOUT", is_error=True)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raises:
            raise RuntimeError("boom in tool")
        self._order_out.append(self.name)
        return ToolResult(content=f"{self.name}|ok")


def _reg(tools: list[_TagTool]) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)  # register 按 name 覆盖，替身即真名实现
    return reg


def _calls(ids: list[str]) -> list[ToolUse]:
    ws = str(Path.cwd())
    return [
        ToolUse(id=i, name=n, input={"file_path": "a.py", "pattern": "x", "path": ws})
        for i, n in zip(ids, REAL_NAMES)
    ]


def _tag(res: ToolResult) -> str:
    """结果属于哪一次调用：编排层的错误正文不带工具标签，改读它自己写的 metadata.tool_name。"""
    meta = res.metadata or {}
    return str(meta.get("tool_name") or res.content.split("|")[0])


@pytest.mark.asyncio
async def test_concurrent_batch_pairs_results_with_calls_and_keeps_order():
    """并发批次：完成顺序被打乱，返回列表仍按调用顺序，且每行内容与自己的 id 同槽。"""
    gate = asyncio.Event()
    order_out: list[str] = []
    reg = _reg([
        _TagTool("Read", gate=gate, delay=0.20, order_out=order_out),
        _TagTool("Glob", let_go=gate, raises=True, order_out=order_out),
        _TagTool("Grep", delay=0.10, order_out=order_out),
    ])
    calls = _calls(["c1", "c2", "c3"])
    result_q: asyncio.Queue = asyncio.Queue()
    results = await run_tools_partitioned(reg, calls, AbortController(), result_q=result_q)

    # 0) 闸门没超时 ⇒ 三个调用确实在同一批次里并发跑（否则 Glob 永远设不了 gate）
    assert "GATE_TIMEOUT" not in str(results[0].content), results[0].content

    # 1) 保序：结果归属与调用逐槽对齐
    assert [_tag(r) for r in results] == list(REAL_NAMES), (
        f"结果与调用错配：{[r.content for r in results]}"
    )

    # 2) 失败那一行留在自己的槽位，且是带分类的失败回执（不冒充成功、不串位）
    assert results[1].is_error is True and results[1].error_kind, results[1].content
    assert _tag(results[1]) == "Glob"
    assert not results[0].is_error and not results[2].is_error

    # 3) 完成顺序与发起顺序不同 ⇒ 配对断言不是恒真
    assert order_out == ["Grep", "Read"], order_out

    # 4) result_q 按**完成**顺序出（与返回列表的**请求**顺序相对照），且事件里的 ToolUse 与结果同配对
    emitted: list[tuple[str, str]] = []
    while not result_q.empty():
        tu, res = result_q.get_nowait()
        emitted.append((tu.name, _tag(res)))
    assert [e[0] for e in emitted] == ["Glob", "Grep", "Read"], (
        f"事件应按完成顺序出（docstring 第 5 条），实际={emitted}"
    )
    for name_a, name_b in emitted:
        assert name_a == name_b, f"事件与结果不同一对：{name_a} / {name_b}"


def test_pairing_checker_catches_a_swapped_batch():
    """反vacuity 控：把结果手动错位一行，配对断言必须失败（否则上面那条门是装饰）。"""
    res = [ToolResult(content="Read|ok"), ToolResult(content="Glob|ok"), ToolResult(content="Grep|ok")]
    swapped = [res[1], res[2], res[0]]
    assert [_tag(r) for r in res] == list(REAL_NAMES)
    assert [_tag(r) for r in swapped] != list(REAL_NAMES)
    # 错误回执靠 metadata 认身份（正文不带标签）：没有这层就会误判成"没配对"
    err = ToolResult(content="tool error: RuntimeError: x", is_error=True, metadata={"tool_name": "Glob"})
    assert _tag(err) == "Glob"


@pytest.mark.asyncio
async def test_sequential_partition_still_keeps_request_order():
    """混合分区：不安全的那个单独成批，返回列表仍按原始顺序。"""
    reg = _reg([
        _TagTool("Read", delay=0.02),
        _TagTool("Glob", safe=False, delay=0.02),
        _TagTool("Grep", delay=0.02),
    ])
    calls = _calls(["c1", "c2", "c3"])
    results = await run_tools_partitioned(reg, calls, AbortController())
    assert [r.content for r in results] == [f"{n}|ok" for n in REAL_NAMES], results
