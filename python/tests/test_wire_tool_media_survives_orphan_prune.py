"""wire 出口：丢孤儿 tool 行时，尾巴上还没 flush 的工具图片不能一起消失。

`normalize_messages_for_openai` 把工具图片攒进 ``pending_tool_images``，只在遇到
非 tool 行时经 ``append_tool_media`` 落成一条 user 媒体行（"图片排在整批工具结果
之后"）。循环结束时再 flush 一次 —— 但 ``prune_orphan_tool_rows`` 有丢行时走的是
**提前 return**，那次收尾 flush 根本执行不到。

于是两个条件同时成立时，图片整批静默丢失（文本结果照常发出，模型看不见图）：
1. 请求的最后一条内部消息是 tool 行（= 上一批工具结果刚落库、本轮没有注入行尾随）。
   下面 ``test_request_can_end_on_an_image_tool_row`` 用真引擎把这个形状证出来。
2. 同一条请求里存在无主 tool 行需要被丢。这不是假想：2026-09-20 实测
   （sess_mu9oqy8m_63ljiu，投影 137 calls / 138 results）就是这条分支存在的理由。

2026-10-15 修复：图片先绑定到结果行，配对裁剪后统一输出有效结果的图片。
本用例已由 strict xfail 提升为正常回归；孤儿结果的图片归属另有专项测试。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, AsyncIterator

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.query_loop import query_loop
from model._openai_common import normalize_messages_for_openai
from model.chunks import ModelChunk
from msgtypes.message import ToolUse, tool_result_message, user_message
from prompt.assembler import DEFAULT_SYSTEM, PromptAssembler
from prompt.t_now_strategy import set_t_now_strategy
from session.message_store import MessageStore
from tools.catalog import apply_read_vision, build_default_registry

# 「工具图片上 wire」这件事由 model/tool_media.py 承载。本门钉的是**它**的早退分支，
# 所以该模块不在（slim 独立运行时闭包 / 未带这条特性的树）时本门不适用——
# 必须出声跳过，不许把"特性缺失"判成"特性有 bug"。
tool_media = pytest.importorskip(
	"model.tool_media", reason="no tool-media wire in this tree; gate not applicable"
)

# 2x2 红 PNG（与 tests/test_tool_result_payload.py 同一枚，能过厂商体积下限）。
PNG_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP8zwACTGCSAQANHQEDgslx/wAAAABJRU5ErkJggg=="
)


def _tool_row(tool_use_id: str, *, with_image: bool) -> dict[str, Any]:
    msg = tool_result_message(
        tool_use_id,
        "Read",
        f"result of {tool_use_id}",
        images=[PNG_URL] if with_image else None,
    )
    return {"role": "tool", "tool_call_id": msg.tool_call_id, "content": msg.content}


def _request(with_orphan: bool) -> list[dict[str, Any]]:
    """真实请求尾巴：assistant 声明 c0 →（可选无主行）→ 带图 tool 行收尾。"""
    rows: list[dict[str, Any]] = [
        {"role": "user", "content": "读这张图"},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "c0", "name": "Read", "input": {}}],
        },
    ]
    if with_orphan:
        # 上游改写多出来的一条：前面没有声明它的 assistant.tool_calls。
        rows.append(_tool_row("ghost", with_image=False))
    rows.append(_tool_row("c0", with_image=True))
    return rows


def _image_blocks(wire: list[dict[str, Any]]) -> int:
    return sum(
        1
        for row in wire
        if isinstance(row.get("content"), list)
        for block in row["content"]
        if isinstance(block, dict) and block.get("type") == "image_url"
    )


def test_control_paired_batch_ships_its_image() -> None:
    """前置自证：无孤儿行时图片确实上得了 wire（否则下面的断言是空的）。"""
    wire = normalize_messages_for_openai(_request(with_orphan=False))
    assert [r.get("role") for r in wire] == ["user", "assistant", "tool", "user"], wire
    assert _image_blocks(wire) == 1, wire
    assert wire[-1]["content"][0]["image_url"]["url"] == PNG_URL, wire[-1]


def test_orphan_row_is_the_dropped_one_not_the_image() -> None:
    """无主行该被丢、配对行该留 —— 这条不许连坐丢的是图片。"""
    wire = normalize_messages_for_openai(_request(with_orphan=True))
    assert [str(r.get("tool_call_id") or "") for r in wire if r.get("role") == "tool"] == ["c0"], wire


def test_orphan_prune_keeps_pending_tool_images() -> None:
    wire = normalize_messages_for_openai(_request(with_orphan=True))
    assert _image_blocks(wire) == 1, wire


@pytest.mark.asyncio
async def test_request_can_end_on_an_image_tool_row(tmp_path, monkeypatch) -> None:
    """可达性证人（今天就该过）：真引擎的一次 Read 出图，请求尾巴确实是 tool 行。

    注入行是尾巴的**唯一**常设来源，所以取 ``skip`` 档（``resolve_t_now_strategy``
    回退阶梯的终态）把它拿掉；``render_notice`` 在正文为空时同样原样返回，因此
    "无注入"不是只有这一档才可能。
    """

    class _ReadThenStop:
        def __init__(self) -> None:
            self.turns: list[list[dict[str, Any]]] = []

        async def stream(self, messages, tools, abort) -> AsyncIterator[ModelChunk]:
            self.turns.append([dict(m) for m in messages])
            if len(self.turns) == 1:
                yield ModelChunk(
                    kind="tool_use",
                    tool_use=ToolUse(
                        id="r1", name="Read", input={"file_path": "image.png"}
                    ),
                )
                return
            yield ModelChunk(kind="text_delta", text="done")
            return

    monkeypatch.setenv("XEYO_READ_VISION", "1")
    Image.new("RGB", (2, 2), "red").save(tmp_path / "image.png")
    registry = build_default_registry(cwd=str(tmp_path))
    apply_read_vision(registry, enabled=True)
    store = MessageStore([user_message("读 image.png")])
    client = _ReadThenStop()
    set_t_now_strategy("skip")
    try:
        async for _ in query_loop(
            store=store,
            model=client,
            tools=registry,
            prompt=PromptAssembler(),
            system_prompt=DEFAULT_SYSTEM,
            abort=AbortController(),
            budget=BudgetTracker(max_turns=8),
        ):
            pass
    finally:
        set_t_now_strategy(None)

    assert len(client.turns) == 2, client.turns
    last = client.turns[1][-1]
    assert last.get("role") == "tool", [r.get("role") for r in client.turns[1]]
    blocks = last.get("content")
    assert isinstance(blocks, list), blocks
    urls = [
        str(b.get("image_url", {}).get("url") or "")
        for b in blocks
        if isinstance(b, dict) and b.get("type") == "image_url"
    ]
    assert urls and urls[0].startswith("data:image/"), blocks
