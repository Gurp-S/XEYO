"""synth_llm_summary_eval — 验证 LLM 摘要(c2_llm_bypass 方向)能否治合成源计数题。

- 用模型读合成对话，生成一段 LLM 摘要（把 20次grep/20行/400/X/grep_019 等直接写进摘要）。
- 用该摘要跑 12 题 → pass 率。对比确定性摘要(~42%)与 project(66.7%)。
无工具。默认 dry-run；--run 调 LLM。
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

PY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PY_ROOT)); sys.path.insert(0, str(PY_ROOT / "scripts"))
from memory_stack_eval import long_history_api, synthetic_probes  # noqa: E402

SUM_INSTR = ("# 压缩指令（请只输出摘要正文）\n请把以上对话压缩成一段纯文本摘要：保留用户目标、关键工具结论（grep 的 pattern、次数、"
             "每结果行数、填充字符、最后 tool_use id）、以及任何可由上下文推出的数值事实（如总行数、总字符），"
             "还有后续仍需要的上下文。省略普通寒暄与无关中间过程。只输出摘要正文，不要前言/代码块/工具调用。")
PROMPT = "你是问答助手。基于上下文回答。只回答案本身。"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--run", action="store_true"); args = ap.parse_args()
    from evals.client import account, chat, ensure_stdout_utf8; ensure_stdout_utf8()
    from memory.runtime import c2_cut_index, deterministic_c2_summary
    from engine.compact import project  # C0/C1 投影
    from memory.runtime import build_tool_use_names

    msgs = long_history_api(20, 8000)
    left = c2_cut_index(msgs, None)
    region = msgs[:left]
    det = deterministic_c2_summary(region, style="new", max_text=160)
    # 投影（供 LLM 摘要与 probe 用）
    names = build_tool_use_names(region)
    proj = project(region, frozen_until=0)
    qs = synthetic_probes().get("questions") or []
    print(f"合成 rows={len(msgs)} 左区={left} 确定性摘要chars={len(det)} 题库={len(qs)}")

    if not args.run:
        print("[dry-run] 将：①用模型读投影生成 LLM 摘要 ②用该摘要跑 12 题。")
        return
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    acct_s = account("synth_llm_summary"); acct_p = account("synth_probe")

    # ①生成 LLM 摘要：把投影 + 压缩指令给模型
    msgs_for_sum = [{"role": "system", "content": "你是会话总结助手。"}] + list(proj) + [{"role": "user", "content": SUM_INSTR}]
    g = chat(msgs_for_sum, acct=acct_s, max_tokens=900, temperature=0.0)
    llm_summary = (g.get("content") or "").strip()
    print(f"LLM摘要chars={len(llm_summary)}")
    print(f"--- LLM摘要前300字 ---\n{llm_summary[:300]}\n")

    # ②probe
    st = {"det": [0, 0], "llm": [0, 0]}
    for q in qs:
        ans = q.get("expect_contains") or []
        for _ in range(3):
            t = chat([{"role": "system", "content": PROMPT}, {"role": "system", "content": det, "name": "session_summary"}, {"role": "user", "content": q["q"]}], acct=acct_p, max_tokens=200, temperature=0.0).get("content") or ""
            low = t.lower()
            if any(str(a).strip().lower() in low for a in ans): st["det"][0] += 1
            st["det"][1] += 1
            t2 = chat([{"role": "system", "content": PROMPT}, {"role": "system", "content": llm_summary, "name": "session_summary"}, {"role": "user", "content": q["q"]}], acct=acct_p, max_tokens=200, temperature=0.0).get("content") or ""
            low2 = t2.lower()
            if any(str(a).strip().lower() in low2 for a in ans): st["llm"][0] += 1
            st["llm"][1] += 1
        print(f"  {q.get('id')} done")
    n = st["det"][1] or 1
    print("\n=== 合成源 ===")
    print(f"确定性摘要 : {st['det'][0]}/{st['det'][1]} = {st['det'][0]/n*100:.1f}%")
    print(f"LLM摘要     : {st['llm'][0]}/{st['llm'][1]} = {st['llm'][0]/n*100:.1f}%  (project参考=66.7%)")
    print(f"成本: 摘要生成={acct_s.summary()['cost_cny']}元 probe={acct_p.summary()['cost_cny']}元")


if __name__ == "__main__":
    main()
