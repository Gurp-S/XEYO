"""T17 项目指令加载：嵌套同名 XEYO.md 去重（同内容只注入一次）+ 变更通知。"""

from typing import Any


def responses(h: Any) -> list[dict[str, Any]]:
    return [
        {"content": "好的。"},
        {"content": "收到。"},
    ]


def run(h: Any) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    # 根 XEYO.md 与嵌套子目录同名文件（同内容）——应只渲染一次
    text = "A_UNIQUE_INSTRUCTION_MARKER_12345"
    (h.workspace / "XEYO.md").write_text(text, encoding="utf-8")
    (h.workspace / "sub").mkdir(parents=True, exist_ok=True)
    (h.workspace / "sub" / "XEYO.md").write_text(text, encoding="utf-8")

    sid = h.create_session()
    h.chat(sid, "你好")
    # 只统计第一条主轮次请求（单份 system prompt）：同内容根+嵌套应只渲染一次
    main_reqs = [r for r in h.mock_requests() if r.get("tools")]
    blob = " ".join(str(m.get("content")) for m in (main_reqs[0].get("messages") or [])
                    if main_reqs)
    occurrences = blob.count(text)
    checks.append(("nested dedup (content rendered once)", occurrences == 1,
                   f"occurrences={occurrences} n_main={len(main_reqs)}"))

    # 编辑嵌套文件 -> 下一轮出现变更通知
    (h.workspace / "sub" / "XEYO.md").write_text("CHANGED", encoding="utf-8")
    h.chat(sid, "看看变更")
    blob2 = " ".join(str(r.get("messages")) for r in h.mock_requests())
    checks.append(("change notice emitted", ("通知" in blob2 or "变更" in blob2),
                   f"has_change={('通知' in blob2 or '变更' in blob2)}"))
    return checks
