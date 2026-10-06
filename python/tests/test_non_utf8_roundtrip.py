"""非 UTF-8 正文必须能安全地读→改→写回，不得被替换符吃掉。

实测（2026-10-03，`tools/fileio/text.py` 的产品链路，一次性 Edit 一行 ASCII）：

- 盘上原文件：GBK 编码、CRLF、68 字节、含 12 个中文词；
- Read 回执：``is_error=False``，正文里已经是 24 个 ``\\ufffd``（解码走
  ``data.decode("utf-8", errors="replace")``，本模块**只**认 utf-8 与带 BOM 的
  utf-16-le）；
- Edit 回执：``has been updated successfully. +1 -1``；
- 盘上结果：68 → 116 字节、GBK 中文**全部消失**、编码变成 UTF-8、``\\ufffd`` 计数 24。

⇒ 模型只改了一行，用户的整份中文正文被静默重写；``encoding`` 字段一路传到底
（``read_text_file`` 返回它、``write_text_file`` 消费它），坏的只是**读侧检测**：
非 UTF-8 文件被判成"UTF-8 但有些字节看不清"。

这不是新能力：同一仓里 ``tools/bash_tool/runner.py:101`` 与
``engine/shadow_git.py:34`` 都已经按 ``utf-8 → gbk → cp1252`` 的顺序兜底解码，
只有 Read/Edit/Write/NotebookEdit 的共用汇聚点没有接。

已按“B + 拒读兜底”修（2026-10-03）：``read_text_file`` 依次试 utf-8 / gbk / cp1252，
且只接受能把原字节**逐字节编回去**的编码（“能解码”不等于“不丢数据”）；没有无损候选、
或正文含 NUL（二进制、无 BOM 的 UTF-16）时抛 ``UndecodableFileError``，由各工具转成
``is_error`` 回执。写侧同批去掉 ``errors="replace"``，并把“编成字节”提到“打开文件”之前
——``open(path, "w")`` 先截断，正文里有该码页表示不了的字符时抛错就把用户文件清成了空文件。

对照档（UTF-8 中文文件同链路往返）必须保持绿色：它证明丢字不是夹具造成的，
而是"盘上不是 UTF-8"这一个条件触发的。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.abort import AbortController
from engine.write_store import WriteStore
from msgtypes.message import ToolUse
from tools.catalog import build_default_registry

ASCII_OLD = "ascii_line = keep_me"
ASCII_NEW = "ascii_line = changed"


def _body() -> list[str]:
    return [
        "# 配置说明",
        "名称 = 小助手",
        "备注 = 仅本机可见",
        ASCII_OLD,
    ]


async def _read_then_edit(registry, path: Path) -> object:
    read = await registry.run(
        ToolUse("r1", "Read", {"file_path": str(path)}),
        AbortController(),
        skip_ask=True,
    )
    assert not read.is_error, f"夹具自证：Read 必须成功，实际 {read.content!r}"
    edit = await registry.run(
        ToolUse(
            "e1",
            "Edit",
            {
                "file_path": str(path),
                "old_string": ASCII_OLD,
                "new_string": ASCII_NEW,
            },
        ),
        AbortController(),
        skip_ask=True,
    )
    return edit


@pytest.mark.asyncio
async def test_utf8_chinese_body_survives_edit_roundtrip(tmp_path: Path) -> None:
    """对照（必须绿）：UTF-8 中文正文在同一条链路上逐字保留。"""
    path = tmp_path / "notes.txt"
    path.write_bytes(("\r\n".join(_body()) + "\r\n").encode("utf-8"))
    registry = build_default_registry(cwd=str(tmp_path))

    edit = await _read_then_edit(registry, path)
    assert not getattr(edit, "is_error", False), repr(getattr(edit, "content", ""))

    text = path.read_bytes().decode("utf-8")
    assert "配置说明" in text, "对照档里 UTF-8 正文被毁 ⇒ 是夹具坏了，不是缺陷"
    assert ASCII_NEW in text
    assert "\ufffd" not in text


@pytest.mark.asyncio
async def test_gbk_chinese_body_survives_edit_roundtrip(tmp_path: Path) -> None:
    """主档（2026-10-03 修）：GBK 中文正文经 Read→Edit 后逐字节还在盘上。"""
    original = ("\r\n".join(_body()) + "\r\n").encode("gbk")
    path = tmp_path / "notes.txt"
    path.write_bytes(original)
    registry = build_default_registry(cwd=str(tmp_path))

    edit = await _read_then_edit(registry, path)
    assert not getattr(edit, "is_error", False), repr(getattr(edit, "content", ""))

    after = path.read_bytes()
    assert ASCII_NEW.encode("gbk") in after, "被改的那行要真的改掉"
    assert "配置说明".encode("gbk") in after, "中文正文必须逐字节还在盘上"
    assert "\ufffd".encode("utf-8") not in after, "不得把替换符写进用户文件"


async def _read(registry, path: Path) -> object:
    return await registry.run(
        ToolUse("r1", "Read", {"file_path": str(path)}),
        AbortController(),
        skip_ask=True,
    )


@pytest.mark.asyncio
async def test_cp1252_body_survives_edit_roundtrip(tmp_path: Path) -> None:
    """cp1252 正文（西欧重音）同链路往返：改 ASCII 行不得吃掉 é。"""
    body = ["# Notes", "café = 1", ASCII_OLD]
    original = ("\r\n".join(body) + "\r\n").encode("cp1252")
    path = tmp_path / "notes.txt"
    path.write_bytes(original)
    registry = build_default_registry(cwd=str(tmp_path))

    edit = await _read_then_edit(registry, path)
    assert not getattr(edit, "is_error", False), repr(getattr(edit, "content", ""))

    after = path.read_bytes()
    assert "café".encode("cp1252") in after, "重音字符必须按 cp1252 原样在盘上"
    assert ASCII_NEW.encode("cp1252") in after
    assert "\ufffd".encode("utf-8") not in after


@pytest.mark.asyncio
async def test_binary_file_is_refused_and_left_untouched(tmp_path: Path) -> None:
    """含 NUL 的正文（哪怕扩展名是 .txt）：拒读成 is_error，盘上字节一个都不动。

    夹具刻意用 .txt：Read 对未知扩展名本就有前置拦截，用 `.bin` 会让这档在修复前
    也是绿的 ⇒ 判据落不到汇聚点上（变异档实测过）。
    """
    original = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rJUNK\xd6\xd0\xce\xc4"
    path = tmp_path / "blob.txt"
    path.write_bytes(original)
    registry = build_default_registry(cwd=str(tmp_path))

    read = await _read(registry, path)
    assert read.is_error, f"二进制必须被拒读，实际成功：{read.content[:200]!r}"
    assert "cannot read" in read.content, repr(read.content[:200])
    assert path.read_bytes() == original, "拒读不得改动盘上字节"


@pytest.mark.asyncio
async def test_utf16_without_bom_is_refused_and_left_untouched(tmp_path: Path) -> None:
    """无 BOM 的 UTF-16（含 NUL）：拒读，不再被当成 GBK/latin 正文吃掉。"""
    original = "中文正文\r\n".encode("utf-16-le")
    path = tmp_path / "notes.txt"
    path.write_bytes(original)
    registry = build_default_registry(cwd=str(tmp_path))

    read = await _read(registry, path)
    assert read.is_error, f"无 BOM 的 UTF-16 必须拒读，实际：{read.content[:200]!r}"
    assert path.read_bytes() == original, "拒读不得改动盘上字节"


@pytest.mark.asyncio
async def test_edit_that_the_codec_cannot_represent_is_refused_and_file_intact(
    tmp_path: Path,
) -> None:
    """GBK 文件里插入码页外的字符：整枪失败并把原字节留在盘上。

    此前宿主路径是 ``open(path, "w", encoding=...)``——打开即截断，编码抛错时用户
    文件已被清成空文件，比写入替换符更坏。
    """
    original = ("\r\n".join(_body()) + "\r\n").encode("gbk")
    path = tmp_path / "notes.txt"
    path.write_bytes(original)
    registry = build_default_registry(cwd=str(tmp_path))

    read = await _read(registry, path)
    assert not read.is_error, f"夹具自证：GBK 正文要能读，实际 {read.content[:200]!r}"

    edit = await registry.run(
        ToolUse(
            "e1",
            "Edit",
            {
                "file_path": str(path),
                "old_string": ASCII_OLD,
                "new_string": ASCII_NEW + " \U0001F600",
            },
        ),
        AbortController(),
        skip_ask=True,
    )
    assert getattr(edit, "is_error", False), "写不进该码页就不能报成功"
    assert path.read_bytes() == original, "失败的一枪必须逐字节不动用户文件"


def test_store_atomic_write_refuses_unencodable_and_leaves_file_intact(
    tmp_path: Path,
) -> None:
    """子 agent / journal 路由（``write_store._atomic_write``）同口径：编不进去就抛，盘上不动。

    此前那里是 ``encode(..., errors="replace")``，而宿主直通路径是严格的 ⇒
    同一枪 Edit 按"这次有没有挂 write_store"劈成两种字节。
    """
    path = tmp_path / "notes.txt"
    original = ("\r\n".join(_body()) + "\r\n").encode("gbk")
    path.write_bytes(original)

    with pytest.raises(UnicodeEncodeError):
        WriteStore._atomic_write(path, "备注 = 仅本机可见 \U0001F600\r\n", encoding="gbk")
    assert path.read_bytes() == original, "抛错的那一枪必须逐字节不动用户文件"


def test_store_atomic_write_keeps_gbk_bytes(tmp_path: Path) -> None:
    """控制档：能编进去的中文按 GBK 原样落盘（证明上一条红不是夹具坏了）。"""
    path = tmp_path / "notes.txt"
    WriteStore._atomic_write(path, "名称 = 小助手\r\n", encoding="gbk")
    assert path.read_bytes() == "名称 = 小助手\r\n".encode("gbk")


@pytest.mark.asyncio
async def test_grep_output_keeps_gbk_chinese(tmp_path: Path) -> None:
    """族内残留（2026-10-05 修）：Grep 输出解码此前固定 utf-8+replace，
    GBK 文件的匹配行整段变 U+FFFD。现与 Bash 同一条码页链。"""
    path = tmp_path / "gbk.txt"
    path.write_bytes("中文标记 needle\n".encode("gbk"))
    # 前置自证：夹具确实不是合法 UTF-8，否则这条门是装饰。
    with pytest.raises(UnicodeDecodeError):
        path.read_text(encoding="utf-8")

    registry = build_default_registry(cwd=str(tmp_path))
    res = await registry.run(
        ToolUse(
            "g1",
            "Grep",
            {"pattern": "needle", "path": ".", "output_mode": "content"},
        ),
        AbortController(),
        skip_ask=True,
    )
    assert not getattr(res, "is_error", False), repr(getattr(res, "content", ""))
    assert "中文标记" in res.content, res.content
    assert "\ufffd" not in res.content, res.content


@pytest.mark.asyncio
async def test_notebook_edit_keeps_bom(tmp_path: Path) -> None:
    """族内残留（2026-10-05 修）：NotebookEdit 写回硬编 utf-8 ⇒ 带 BOM 的
    .ipynb 被剥 BOM；现沿用读侧判定的 encoding（utf-8-sig）。"""
    import json as _json

    nb = {
        "cells": [
            {
                "cell_type": "code",
                "source": ["print(1)"],
                "outputs": [],
                "execution_count": None,
                "metadata": {},
            }
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path = tmp_path / "n.ipynb"
    path.write_bytes(b"\xef\xbb\xbf" + _json.dumps(nb).encode("utf-8"))

    registry = build_default_registry(cwd=str(tmp_path))
    read = await registry.run(
        ToolUse("r1", "Read", {"file_path": str(path)}),
        AbortController(),
        skip_ask=True,
    )
    assert not getattr(read, "is_error", False), repr(getattr(read, "content", ""))
    edit = await registry.run(
        ToolUse(
            "n1",
            "NotebookEdit",
            {
                "notebook_path": "n.ipynb",
                "edit_mode": "replace",
                "cell_idx": 0,
                "new_source": "print(2)",
            },
        ),
        AbortController(),
        skip_ask=True,
    )
    assert not getattr(edit, "is_error", False), repr(getattr(edit, "content", ""))

    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "BOM 被写回剥掉了"
    assert "print(2)" in raw.decode("utf-8-sig")
