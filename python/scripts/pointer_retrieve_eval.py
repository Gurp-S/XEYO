"""pointer_retrieve_eval — 方案B：测「C2 摘要 + 原始历史检索工具」能否让模型找回丢失事实。

对比两模式 pass 率（24 题 × AB_REPEATS）：
- summary  ：只给 C2 摘要投影（无工具）。      —— 对照基线
- retrieve ：摘要投影 + 指针提示 + grep_transcript 工具，模型可主动检索原文。 —— 被测

默认 dry-run（只构建投影+报告，不调 LLM）；加 ``--run`` 才真正调 DeepSeek。
不碰主链路（独立脚本），读 evals.client 复用产品客户端请求构造。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PY_ROOT = Path(__file__).resolve().parents[1]  # python/
sys.path.insert(0, str(PY_ROOT))
sys.path.insert(0, str(PY_ROOT / "scripts"))  # memory_stack_eval import 用（如需）

HOME = Path.home()
SESSION = HOME / ".xeyo" / "sessions" / "sess_mtlpmznl_0iapt2.jsonl"
PROBES = PY_ROOT / "scripts" / "probes" / "ab_real_probes.json"
AB_REPEATS = 3
MAX_TOOL_ROUNDS = 3  # 最多允许的检索-工具回合数（防模型贪心读取）

GREP_TOOL_SCHEMA = {
    "name": "grep_transcript",
    "description": (
        "在本次会话的完整原始记录（JSONL）里按关键字 grep，返回命中的消息行及少量上下文。"
        "当压缩摘要缺细节时，用它检索原始步骤/数值/术语。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {"keyword": {"type": "string", "description": "要检索的关键字/数字/术语"}},
        "required": ["keyword"],
    },
}

_POINTER_BLOCK = (
    "# C2 后原始历史（background only）\n"
    "本会话完整原始消息记录已被压缩进上方摘要；若摘要缺细节，"
    "可用工具 grep_transcript(keyword) 检索原始记录找回（如具体数字、文件名、术语）。\n"
)


def load_messages() -> list[dict]:
    msgs = []
    with open(SESSION, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    msgs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return msgs


def grep_transcript(keyword: str, *, cap: int = 6) -> str:
    """在会话 JSONL 里 grep keyword，返回匹配行 + 少量上下文（封顶，防大读）。"""
    kw = (keyword or "").strip()
    if not kw or len(kw) > 60:
        return "(无效检索词)"
    hits: list[str] = []
    try:
        with open(SESSION, encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                if kw.lower() in line.lower():
                    try:
                        obj = json.loads(line)
                        content = obj.get("content")
                        if isinstance(content, str):
                            txt = content
                        elif isinstance(content, list):
                            txt = " ".join(
                                str(b.get("text") or b.get("content") or "")
                                for b in content if isinstance(b, dict)
                            )
                        else:
                            txt = str(content)
                    except json.JSONDecodeError:
                        txt = line
                    hits.append(f"[{i}] {txt[:220]}")
                    if len(hits) >= cap:
                        break
    except OSError as e:
        return f"(读取失败: {e})"
    if not hits:
        return f"(未命中: {kw})"
    return "\n".join(hits)


def build_summary_projection(region: list[dict]) -> list[dict]:
    from memory.runtime import deterministic_c2_summary

    summary = deterministic_c2_summary(region, style="new", max_text=160)
    return [{"role": "system", "content": summary, "name": "session_summary"}]


def pointer_instruction(text: str) -> str:
    return _POINTER_BLOCK + "\n" + text


def run_one(
    messages: list[dict],
    *,
    tools: list[dict] | None,
    acct,
    max_tokens: int = 240,
) -> str:
    """带工具回合循环：调 chat，若模型请求工具→执行→回传→继续，直到给出答案。"""
    from evals.client import chat

    cur = [dict(m) for m in messages]
    for _round in range(MAX_TOOL_ROUNDS):
        resp = chat(cur, tools=tools, acct=acct, max_tokens=max_tokens, temperature=0.0)
        tool_calls = resp.get("tool_calls") or []
        if not tool_calls:
            return resp.get("content") or ""
        # 追加 assistant tool_use 消息（每个工具调用唯一 id）
        blocks = []
        results = []
        for _idx, tc in enumerate(tool_calls):
            cid = f"call_{_round}_{tc.get('name', 't')}_{_idx}"
            blocks.append({"type": "tool_use", "id": cid, "name": tc.get("name", "t"), "input": tc.get("arguments") or {}})
            out = grep_transcript(str((tc.get("arguments") or {}).get("keyword", "")))
            results.append({"type": "tool_result", "tool_use_id": cid, "content": out})
        cur.append({"role": "assistant", "content": blocks})
        cur.append({"role": "user", "content": results})
    # 超回合：取最后一次答案
    resp = chat(cur, tools=tools, acct=acct, max_tokens=max_tokens, temperature=0.0)
    return resp.get("content") or ""


def judge(text: str, answers: list[str]) -> bool:
    low = (text or "").lower()
    return any(str(a).strip().lower() in low for a in answers)


def main() -> None:
    from evals.client import account, ensure_stdout_utf8
    from memory.runtime import c2_cut_index

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", action="store_true", help="真正调 LLM（否则 dry-run 零成本）")
    args = ap.parse_args()
    ensure_stdout_utf8()

    from memory import runtime as rt
    from memory import session_md  # noqa: F401

    msgs = load_messages()
    left = c2_cut_index(msgs, None)
    region = msgs[:left]
    probes = json.loads(PROBES.read_text(encoding="utf-8"))
    qs = probes.get("questions") or []
    print(f"锚定会话 rows={len(msgs)} 压缩区={left}  题库={len(qs)}题×{AB_REPEATS}次")

    summary_proj = build_summary_projection(region)
    summary_text = summary_proj[0]["content"]
    print(f"摘要字符={len(summary_text)}")

    # 系统指令（普通）
    import os
    base_system = (
        "你是问答助手。基于提供的会话摘要/上下文回答用户问题；"
        "只回答案本身，不要解释。命中关键字即可。"
    )

    # dry-run：构建好投影 & 工具 schema，报告，不调 LLM
    if not args.run:
        print("\n[dry-run] 已构建，不调 LLM。以下为将要运行的两种消息结构：")
        print("\n--- summary 投影（无工具）消息数 =", len(summary_proj) + 2, "---")
        print("  system:", base_system[:60], "...")
        print("  +summary 块(name=session_summary) chars=", len(summary_text))
        print("  +user(问题)")
        print("\n--- retrieve 投影（指针 + grep_transcript 工具）---")
        print("  system(含指针) 前缀:", pointer_instruction(base_system)[:160], "...")
        print("  +summary 块 +user(问题)")
        print("  tools:")
        print("   ", json.dumps(GREP_TOOL_SCHEMA["name"], ensure_ascii=False))
        print("\n要真正测试，运行:  python scripts/pointer_retrieve_eval.py --run")
        return

    # run：两模式对比
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        print("缺 DEEPSEEK_API_KEY（设环境变量或 --load .env）")
        sys.exit(2)

    acct_sum = account("pointer_summary")
    acct_ret = account("pointer_retrieve")
    stats = {"summary": [0, 0], "retrieve": [0, 0]}

    for q in qs:
        qid = q.get("id")
        answers = q.get("expect_contains") or []
        for rep in range(AB_REPEATS):
            # summary 模式
            smsgs = [{"role": "system", "content": base_system}] + summary_proj + [
                {"role": "user", "content": q.get("q", "")}
            ]
            t = run_one(smsgs, tools=None, acct=acct_sum)
            if judge(t, answers):
                stats["summary"][0] += 1
            stats["summary"][1] += 1
            # retrieve 模式（系统指令带指针 + 工具）
            rmsgs = [{"role": "system", "content": pointer_instruction(base_system)}] + summary_proj + [
                {"role": "user", "content": q.get("q", "")}
            ]
            t2 = run_one(rmsgs, tools=[GREP_TOOL_SCHEMA], acct=acct_ret)
            if judge(t2, answers):
                stats["retrieve"][0] += 1
            stats["retrieve"][1] += 1
        print(f"  {qid} done")

    n = stats["summary"][1] or 1
    print("\n=== 结果 ===")
    print(f"summary   : pass {stats['summary'][0]}/{stats['summary'][1]} = {stats['summary'][0]/n*100:.1f}%")
    print(f"retrieve  : pass {stats['retrieve'][0]}/{stats['retrieve'][1]} = {stats['retrieve'][0]/n*100:.1f}%")
    print(f"成本: summary={acct_sum.summary()['cost_cny']}元  retrieve={acct_ret.summary()['cost_cny']}元")


if __name__ == "__main__":
    main()
