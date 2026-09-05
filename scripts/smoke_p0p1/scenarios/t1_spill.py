"""T1 输出经济 + 原始证据先行：非豁免工具（Grep）大输出 -> registry spill 落盘 + 预览。

Bash/Read 豁免注册表 spill，故用 Grep 对预先埋好的大文件做全量匹配，输出
> 16000 字符触发 spill。断言 spill 文件存在且含完整原文、预览被替换为
「全文路径」marker。
"""

from typing import Any


def responses(h: Any) -> list[dict[str, Any]]:
    ws = str(h.workspace).replace("\\", "/")
    return [
        {"tool_calls": [{"name": "Grep", "arguments": {
            "pattern": "line", "path": ws + "/big.txt",
            "output_mode": "content", "-n": False}}]},
        {"content": "匹配完成。"},
    ]


def _tool_results(tr: Any) -> list[dict[str, Any]]:
    return [e for e in tr.events if e.get("type") == "tool_result"]


def run(h: Any) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    # 预埋大文件：1000 行，每行 200 字符 -> 匹配全量 > 16000
    lines = ["line " + ("B" * 200) for _ in range(1000)]
    (h.workspace / "big.txt").write_text("\n".join(lines), encoding="utf-8")

    sid = h.create_session()
    tr = h.chat(sid, "搜一下 line")
    results = _tool_results(tr)
    checks.append(("tool_result produced", len(results) >= 1,
                   f"n={len(results)} types={tr.event_types()}"))

    spill_files = h.read_spill_files()
    checks.append(("spill file written", len(spill_files) >= 1,
                   f"n_spill={len(spill_files)}"))

    # 预览应含 "full output" 路径 marker（registry spill）
    body = str(results[0].get("output") or "") if results else ""
    checks.append(("preview has full-output marker",
                   "full output" in body.lower(),
                   f"body_len={len(body)} first={body[:80]!r}"))

    # spill 文件应保留完整原始证据（1000 行 * 200 字符，> 16000）
    has_raw = False
    for p in spill_files:
        try:
            if p.stat().st_size >= 16000:
                has_raw = True
                break
        except OSError:
            pass
    checks.append(("raw evidence preserved (size)", has_raw,
                   f"sizes={[p.stat().st_size for p in spill_files]}"))
    return checks
