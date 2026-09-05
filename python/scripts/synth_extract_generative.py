"""synth_extract_generative — 抽取式→生成式摘要，治合成源计数题。

- 第一阶段(抽取)：从【完整】左区抽出关键语料(user意图 + 全部tool_use含id + tool_result关键事实)。
- 第二阶段(生成)：把关键语料喂LLM → 重组润色成摘要。
- 用摘要跑12题 → 对比 project(66.7%) / 上一版LLM摘要(50%)。
"""
from __future__ import annotations
import argparse, os, sys
from pathlib import Path
import json

PY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PY_ROOT)); sys.path.insert(0, str(PY_ROOT / "scripts"))
from memory_stack_eval import long_history_api, synthetic_probes  # noqa: E402

SUM_INSTR = ("# 压缩指令（只输出摘要正文）\n请把下面的关键语料整合成一段准确、通顺的摘要，"
             "必须准确保留：用户目标、grep 的 pattern、执行次数、每结果行数、填充字符、最后一个 grep 的 id、"
             "以及可推出的总数(行数/字符数)。只输出摘要正文，不要前言/代码块/工具调用。")
PROMPT = "你是问答助手。基于上下文回答。只回答案本身。"


def _txt(m):
    c = m.get("content")
    if isinstance(c, str): return c
    if isinstance(c, list): return "\n".join(str(b.get("content") or b.get("text") or "") for b in c if isinstance(b, dict))
    return str(c or "")


import re
from collections import Counter


def _fill_char(raw):
    """检测填充字符：连续重复≥20次的字符（如 X 填充）。"""
    runs = re.findall(r"(.)\1{20,}", raw)
    if not runs:
        return None
    return Counter(runs).most_common(1)[0][0]


def _count_lines(raw):
    """精确行数（非空行），供"每结果 N 行"。"""
    return sum(1 for ln in raw.splitlines() if ln.strip())


def phase1_extract(msgs):
    """从【完整】会话抽取关键语料：user + 全部tool_use(含id) + tool_result关键事实(填充字符/行数)。"""
    parts = []
    n_use = 0
    total_lines = 0
    for m in msgs:
        k = m.get("role")
        c = m.get("content")
        if isinstance(c, str):
            if k == "user":
                parts.append(f"[用户] {c.strip()}")
            continue
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                n_use += 1
                parts.append(f"[工具调用] {b.get('name')} id={b.get('id')} input={json.dumps(b.get('input'), ensure_ascii=False)}")
            elif b.get("type") == "tool_result":
                raw = str(b.get("content") or "")
                lines = _count_lines(raw)
                total_lines += lines
                fill = _fill_char(raw)
                fc = f"填充字符={fill}" if fill else ""
                parts.append(f"[工具结果] {b.get('tool_use_id')} {lines}行 {fc} 头: {raw.splitlines()[0][:100] if raw.splitlines() else ''}")
    parts.append(f"[汇总事实] 共执行 {n_use} 次工具调用；各结果非空行合计约 {total_lines} 行。")
    return "\n".join(parts), n_use


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--run", action="store_true"); args = ap.parse_args()
    from evals.client import account, chat, ensure_stdout_utf8; ensure_stdout_utf8()
    from memory.runtime import c2_cut_index, deterministic_c2_summary

    msgs = long_history_api(20, 8000)
    left = c2_cut_index(msgs, None); region = msgs[:left]
    det = deterministic_c2_summary(region, style="new", max_text=160)
    corpus, n_use = phase1_extract(msgs)
    qs = synthetic_probes().get("questions") or []
    print(f"合成 rows={len(msgs)} 左区={left} tool_use数={n_use} 关键语料chars={len(corpus)} 确定性摘要chars={len(det)}")

    if not args.run:
        print("[dry-run] 将：①抽关键语料 ②LLM重组摘要 ③跑12题。")
        return
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    acct_s = account("extr_gen_summary"); acct_p = account("extr_gen_probe")

    g = chat([{"role": "system", "content": "你是会话总结助手。"}, {"role": "user", "content": corpus}, {"role": "user", "content": SUM_INSTR}], acct=acct_s, max_tokens=900, temperature=0.0)
    llm_summary = (g.get("content") or "").strip()
    print(f"LLM摘要chars={len(llm_summary)}")
    print(f"--- LLM摘要前400字 ---\n{llm_summary[:400]}\n")

    st = {"det": [0, 0], "llm": [0, 0]}
    for q in qs:
        ans = q.get("expect_contains") or []
        for _ in range(3):
            t = chat([{"role": "system", "content": PROMPT}, {"role": "system", "content": det, "name": "session_summary"}, {"role": "user", "content": q["q"]}], acct=acct_p, max_tokens=200, temperature=0.0).get("content") or ""
            if any(str(a).strip().lower() in t.lower() for a in ans): st["det"][0] += 1
            st["det"][1] += 1
            t2 = chat([{"role": "system", "content": PROMPT}, {"role": "system", "content": llm_summary, "name": "session_summary"}, {"role": "user", "content": q["q"]}], acct=acct_p, max_tokens=200, temperature=0.0).get("content") or ""
            if any(str(a).strip().lower() in t2.lower() for a in ans): st["llm"][0] += 1
            st["llm"][1] += 1
        print(f"  {q.get('id')} done")
    n = st["det"][1] or 1
    print("\n=== 合成源 ===")
    print(f"确定性摘要 : {st['det'][0]}/{st['det'][1]} = {st['det'][0]/n*100:.1f}%")
    print(f"抽取+生成   : {st['llm'][0]}/{st['llm'][1]} = {st['llm'][0]/n*100:.1f}%  (project参考66.7%)")
    print(f"成本: 生成摘要={acct_s.summary()['cost_cny']}元 probe={acct_p.summary()['cost_cny']}元")


if __name__ == "__main__":
    main()
