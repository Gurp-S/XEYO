"""Codex rollout JSONL -> XEYO 形状转录（只读、零成本；供 `wsc_fold_watermark_ab.py --session <path>` 回放）。

映射（按"真正进请求的行"取，其余全部跳过）：
  response_item/message(role=user)      -> {"role":"user","content": <字符串>}
  response_item/message(role=assistant) -> 合并进 assistant 行（text 块）
  response_item/function_call            -> assistant 行 tool_use 块（arguments JSON 解析）
  response_item/custom_tool_call         -> assistant 行 tool_use 块（input 为脚本文本时包 {"text": ...}）
  response_item/(custom_)tool_call_output-> {"role":"tool", "tool_call_id", "name", "content":[tool_result 块]}
跳过（并记录计数）：developer/system 消息、reasoning（含加密）、agent_message（payload 加密不可回放）、
compacted 事件、token_usage/event_msg/世界状态等遥测。**不模拟 Codex 自己的压缩**（与 XEYO 回放同口径：
回放原始消息流；Codex 的 compacted 事件只计数不入流）。

用法：
  py -3.11 python/scripts/codex_rollout_to_transcript.py <rollout.jsonl> [...] --out-dir _wsc_out/_codex_replay
"""

from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # 第一行就调（Windows 重定向按 locale 编码会炸）

import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for b in content or []:
        if isinstance(b, dict):
            t = b.get("text")
            if isinstance(t, str):
                parts.append(t)
    return "\n".join(parts)


def convert(src: Path, out_dir: Path) -> dict:
    rows: list[dict] = []
    pending: list[dict] = []          # 当前 assistant 调用里累积的块（text / tool_use）
    names: dict[str, str] = {}        # call_id -> 工具名（为输出行补 name）
    seq = 0
    stats = {
        "src": str(src), "user": 0, "assistant": 0, "tool": 0,
        "skipped_developer": 0, "skipped_reasoning": 0, "skipped_agent_msg": 0,
        "skipped_compacted": 0, "tool_chars": 0, "tool_max": 0, "tool_chars_list": [],
        "total_chars": 0,
    }

    def flush() -> None:
        nonlocal pending, seq
        blocks, pending = pending, []
        if not blocks:
            return
        has_call = any(b["type"] == "tool_use" for b in blocks)
        has_text = any(b["type"] == "text" and b.get("text", "").strip() for b in blocks)
        if not has_call and not has_text:
            return
        seq += 1
        rows.append({"id": f"a{seq}", "role": "assistant", "ts": seq, "content": blocks})
        stats["assistant"] += 1

    with open(src, encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") == "compacted":
                stats["skipped_compacted"] += 1
                continue
            if d.get("type") != "response_item":
                continue
            p = d.get("payload") or {}
            t = p.get("type")
            if t == "message":
                role = p.get("role")
                if role == "user":
                    flush()
                    txt = _text_of(p.get("content"))
                    if txt.strip():
                        seq += 1
                        rows.append({"id": f"u{seq}", "role": "user", "ts": seq, "content": txt})
                        stats["user"] += 1
                elif role == "assistant":
                    txt = _text_of(p.get("content"))
                    if txt.strip():
                        pending.append({"type": "text", "text": txt})
                else:
                    stats["skipped_developer"] += 1
            elif t in ("function_call", "custom_tool_call"):
                name = str(p.get("name") or "tool")
                raw = p.get("arguments") if t == "function_call" else p.get("input")
                if isinstance(raw, str):
                    try:
                        inp = json.loads(raw)
                    except Exception:
                        inp = {"text": raw}
                elif isinstance(raw, dict):
                    inp = raw
                else:
                    inp = {"text": str(raw)}
                cid = str(p.get("call_id") or p.get("id") or "")
                if cid:
                    names[cid] = name
                pending.append({"type": "tool_use", "id": cid, "name": name, "input": inp})
            elif t in ("function_call_output", "custom_tool_call_output"):
                flush()
                cid = str(p.get("call_id") or "")
                out = p.get("output")
                text = out if isinstance(out, str) else _text_of(out)
                seq += 1
                rows.append({
                    "id": f"t{seq}", "role": "tool", "ts": seq,
                    "tool_call_id": cid, "name": names.get(cid, "tool"),
                    "content": [{"type": "tool_result", "tool_use_id": cid, "content": text}],
                })
                stats["tool"] += 1
                stats["tool_chars"] += len(text)
                stats["tool_max"] = max(stats["tool_max"], len(text))
                stats["tool_chars_list"].append(len(text))
            elif t == "reasoning":
                stats["skipped_reasoning"] += 1
            elif t == "agent_message":
                stats["skipped_agent_msg"] += 1
    flush()

    stats["total_chars"] = sum(len(json.dumps(r, ensure_ascii=False)) for r in rows)
    tl = sorted(stats.pop("tool_chars_list"))
    if tl:
        stats["tool_chars_p50"] = tl[len(tl) // 2]
        stats["tool_chars_p90"] = tl[int(len(tl) * 0.9)]
    out_dir.mkdir(parents=True, exist_ok=True)
    name = src.stem.replace("rollout-", "cdx-")
    if len(name) > 60:
        name = name[:60]
    out = out_dir / f"{name}.jsonl"
    with open(out, "w", encoding="utf-8", newline="\n") as w:
        for r in rows:
            w.write(json.dumps(r, ensure_ascii=False) + "\n")
    stats["out"] = str(out)
    stats["bytes"] = out.stat().st_size
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="Codex rollout -> XEYO 形状转录（回放用）")
    ap.add_argument("inputs", nargs="+", help="rollout .jsonl 路径")
    ap.add_argument("--out-dir", default="_wsc_out/_codex_replay")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    for s in args.inputs:
        p = Path(s)
        if not p.is_file():
            print(f"[skip] 不存在: {p}")
            continue
        st = convert(p, out_dir)
        print(json.dumps(st, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
