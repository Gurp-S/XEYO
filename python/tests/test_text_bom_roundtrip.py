"""UTF-8 BOM 是文件的属性：Edit 之后必须还在，且不叠加、不凭空造。

实测缺陷（2026-10-03，产品自己的 Read+Edit）：带 BOM 的 `report.csv` 改一行
ASCII ⇒ 55 → 52 字节，**BOM 被静默剥掉**（中文与 CRLF 都还在）。同一函数
`read_text_file` 对 utf-16-le 是**主动补回 BOM** 的（`text.py:105-109`），
说明"保留原文件 BOM"本来就是既有口径，UTF-8 这一支只是漏了。

后果落在 Windows 侧：PowerShell 5.1 与 Excel 在没有 BOM 时按 ANSI 解读 .ps1/.csv
⇒ 引擎改完一列名，用户自己打开就成乱码。

修法：读到前导 BOM 时把编码报成 ``utf-8-sig``（Python 标准 codec，编码时补 BOM、
解码时剥 BOM），正文一律不含 BOM ⇒ 匹配/哈希口径不变，写回自动带上。

三档都要绿：
- BOM 文件连改两次：BOM 恰好 1 个（**不叠加**——BOM 不是正文，重复落盘会越攒越多）；
- 无 BOM 文件：不得被"顺手补一个"（否则字节级 diff 无端多出 3 字节）；
- ``read_text_file`` 的编码标签本身。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.abort import AbortController
from msgtypes.message import ToolUse
from tools.catalog import build_default_registry
from tools.fileio.text import read_text_file, write_text_file

BOM = b"\xef\xbb\xbf"
OLD = "ascii_line = keep_me"
NEW = "ascii_line = changed"


def _csv_text() -> str:
    return "列名,值\r\n名称=小助手\r\n" + OLD + "\r\n"


async def _edit(registry, path: Path, old: str, new: str, uid: str) -> None:
    result = await registry.run(
        ToolUse(
            uid,
            "Edit",
            {"file_path": str(path), "old_string": old, "new_string": new},
        ),
        AbortController(),
        skip_ask=True,
    )
    assert not result.is_error, f"Edit 失败：{result.content!r}"


@pytest.mark.asyncio
async def test_bom_survives_repeated_edits_without_multiplying(tmp_path: Path) -> None:
    path = tmp_path / "report.csv"
    path.write_bytes(BOM + _csv_text().encode("utf-8"))
    registry = build_default_registry(cwd=str(tmp_path))
    await registry.run(
        ToolUse("r1", "Read", {"file_path": str(path)}),
        AbortController(),
        skip_ask=True,
    )

    await _edit(registry, path, OLD, NEW, "e1")
    after_first = path.read_bytes()
    assert after_first.startswith(BOM), "BOM 被 Edit 剥掉 ⇒ 用户文件在 Windows 上按 ANSI 读"
    assert "小助手".encode("utf-8") in after_first
    assert b"\r\n" in after_first, "行尾不得被顺手归一"
    assert after_first.count(BOM) == 1

    await _edit(registry, path, NEW, NEW + "!", "e2")
    after_second = path.read_bytes()
    assert after_second.count(BOM) == 1, "BOM 叠加＝把上一轮的 BOM 当正文又写了一遍"
    assert after_second.decode("utf-8-sig").startswith("列名"), "正文不得混入 BOM"


@pytest.mark.asyncio
async def test_file_without_bom_does_not_gain_one(tmp_path: Path) -> None:
    """反向校：无 BOM 的文件不能被"顺手补一个"。"""
    path = tmp_path / "plain.csv"
    raw = _csv_text().encode("utf-8")
    path.write_bytes(raw)
    registry = build_default_registry(cwd=str(tmp_path))
    await registry.run(
        ToolUse("r1", "Read", {"file_path": str(path)}),
        AbortController(),
        skip_ask=True,
    )
    await _edit(registry, path, OLD, NEW, "e1")
    after = path.read_bytes()
    assert not after.startswith(BOM), "给没有 BOM 的文件补 BOM＝凭空改头三字节"
    assert after == raw.replace(OLD.encode("utf-8"), NEW.encode("utf-8"))


def test_read_text_file_reports_utf8_sig_for_bom_file(tmp_path: Path) -> None:
    path = tmp_path / "bom.txt"
    path.write_bytes(BOM + "# 标题\n".encode("utf-8"))
    content, _endings, encoding = read_text_file(str(path))
    assert encoding == "utf-8-sig", "编码标签丢了 BOM 事实 ⇒ 写回无从补回"
    assert not content.startswith("\ufeff"), "BOM 不是正文：匹配与哈希口径必须一致"


def test_write_then_read_roundtrips_bom(tmp_path: Path) -> None:
    path = tmp_path / "rt.txt"
    write_text_file(str(path), "# 标题\n", encoding="utf-8-sig", line_endings="LF")
    assert path.read_bytes().startswith(BOM)
    content, _endings, encoding = read_text_file(str(path))
    assert (content, encoding) == ("# 标题\n", "utf-8-sig")


@pytest.mark.asyncio
async def test_write_store_route_also_preserves_bom_and_crlf(tmp_path: Path) -> None:
    """子代理/WriteStore 那条写回路也要保 BOM + 保 CRLF。

    Edit 有两条落盘路：直通 ``write_text_file``，和经 ``write_store.submit_sync``
    → ``_atomic_write``（后者自己不做 line_endings，注释里写明"由调用方在 content
    里定稿"）。只测直通路会让 store 路没人管——正是本仓反复踩的"同一资源的另一种
    形状"。⇒ 显式把工具挂上 WriteStore 再改一次，并且**用 spy 证明这次真的走了
    store**（不然这条断言等于又跑了一遍直通路）。
    """
    from engine.write_store import WriteStore

    path = tmp_path / "sub.csv"
    path.write_bytes(BOM + _csv_text().encode("utf-8"))
    registry = build_default_registry(cwd=str(tmp_path))
    edit_tool = registry.get("Edit")
    assert edit_tool is not None, "夹具自证：注册表里要有 Edit"
    store = WriteStore(root=str(tmp_path))
    seen: list[str] = []
    real_submit = store.submit_sync

    def _spy(intent):
        for op in intent.ops:
            seen.append((str(getattr(op, "path", "")), str(intent.encoding or "")))
        return real_submit(intent)

    store.submit_sync = _spy  # type: ignore[method-assign]
    edit_tool.set_write_store(store)
    await registry.run(
        ToolUse("r1", "Read", {"file_path": str(path)}),
        AbortController(),
        skip_ask=True,
    )

    await _edit(registry, path, OLD, NEW, "e1")
    assert any(str(path) in p for p, _e in seen), "本次没走 WriteStore ⇒ 这条门是装饰"
    assert any(enc == "utf-8-sig" for _p, enc in seen), (
        f"编码事实没传到 store（实收 {[e for _p, e in seen]}）⇒ 只是字节碰巧对"
    )

    after = path.read_bytes()
    assert after.startswith(BOM), "经 WriteStore 的写回路丢了 BOM"
    assert after.count(BOM) == 1
    assert b"\r\n" in after, "store 路的原子写用 newline=''，CRLF 必须由调用方定稿"
    assert NEW in after.decode("utf-8-sig"), "改动本身要真的落进正文"
