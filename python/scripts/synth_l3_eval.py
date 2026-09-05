"""synth_l3_eval — 验证 L3(T=128+offload_read) 是否收敛合成源 -16.7pp。

对比合成源两道：
- summary   ：只给确定性摘要（无工具）→ 基线（预期 ~50%）。
- offload   ：摘要 + offload引用 + offload_read 工具 → 模型按需读回 → 期望更高。
默认 dry-run；--run 才调 LLM。
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

PY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PY_ROOT)); sys.path.insert(0, str(PY_ROOT / "scripts"))
from memory_stack_eval import long_history_api, synthetic_probes  # noqa: E402

THRESHOLD = 128
OFFLOAD_DIR = PY_ROOT / ".xeyo_offload_tmp"
OFFLOAD_READ_SCHEMA = {
    "name": "offload_read",
    "description": "按行区间读取被外部化的工具结果文件，返回该区间内容。",
    "input_schema": {"type": "object", "properties": {
        "path": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"}}, "required": ["path"]},
}
PROMPT = "你是问答助手。基于上下文回答；若上下文缺细节，可用 offload_read 检索外部化的工具结果文件。只回答案本身。"


def _text(m):
    c = m.get("content")
    if isinstance(c, str): return c
    if isinstance(c, list): return "\n".join(str(b.get("content") or b.get("text") or "") for b in c if isinstance(b, dict))
    return str(c or "")


def build_offloaded(region):
    """offload >THRESHOLD 的 tool_result 到文件+引用。"""
    proj, omap = [], {}
    OFFLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for idx, m in enumerate(region):
        c = m.get("content")
        if isinstance(c, list):
            nb = []
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    raw = str(b.get("content") or "")
                    if len(raw) > THRESHOLD:
                        f = OFFLOAD_DIR / f"s_{idx}.tool.txt"; f.write_text(raw, encoding="utf-8")
                        nb.append({**b, "content": f"[tool offloaded: {f} ({raw.count(chr(10))+1} lines) 头: {raw[:120].replace(chr(10),' ')}...]"})
                        omap[idx] = str(f)
                    else:
                        nb.append(b)
                else:
                    nb.append(b)
            m2 = dict(m); m2["content"] = nb; proj.append(m2)
        else:
            proj.append(m)
    return proj, omap


def _exec(args):
    p = Path(args.get("path") or "")
    if not p.is_file(): return f"(not found: {p})"
    t = p.read_text(encoding="utf-8")
    if args.get("start"):
        lines = t.split("\n"); return "\n".join(lines[max(0, int(args["start"]) - 1): int(args.get("end") or 999999)])
    return t


def run_one(messages, tools, acct):
    from evals.client import chat
    cur = [dict(m) for m in messages]
    for _ in range(3):
        resp = chat(cur, tools=tools, acct=acct, max_tokens=200, temperature=0.0)
        tcs = resp.get("tool_calls") or []
        if not tcs: return resp.get("content") or ""
        bl, rs = [], []
        for i, tc in enumerate(tcs):
            cid = f"call_{_}_{tc.get('name','t')}_{i}"; a = tc.get("arguments") or {}
            bl.append({"type": "tool_use", "id": cid, "name": tc.get("name", "t"), "input": a})
            rs.append({"type": "tool_result", "tool_use_id": cid, "content": _exec(a)})
        cur.append({"role": "assistant", "content": bl}); cur.append({"role": "user", "content": rs})
    return chat(cur, tools=tools, acct=acct, max_tokens=200, temperature=0.0).get("content") or ""


def judge(t, ans):
    low = (t or "").lower()
    return any(str(a).strip().lower() in low for a in ans)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--run", action="store_true"); args = ap.parse_args()
    from evals.client import account, ensure_stdout_utf8; ensure_stdout_utf8()
    from memory.runtime import c2_cut_index, deterministic_c2_summary
    msgs = long_history_api(20, 8000)
    left = c2_cut_index(msgs, None); region = msgs[:left]
    summary = deterministic_c2_summary(region, style="new", max_text=160)
    proj, omap = build_offloaded(region)
    qs = synthetic_probes().get("questions") or []
    print(f"合成 rows={len(msgs)} 左区={left} offload(>{THRESHOLD})={len(omap)} 摘要chars={len(summary)}")
    if not args.run:
        print(f"[dry-run] offload {len(omap)} 文件。将跑 summary vs offload 各 {len(qs)} 题×3 次。")
        return
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    acct_s = account("synth_summary"); acct_o = account("synth_offload")
    st = {"summary": [0, 0], "offload": [0, 0]}
    for q in qs:
        ans = q.get("expect_contains") or []
        for _ in range(3):
            t = run_one([{"role": "system", "content": PROMPT}, {"role": "system", "content": summary, "name": "session_summary"}, {"role": "user", "content": q["q"]}], None, acct_s)
            if judge(t, ans): st["summary"][0] += 1
            st["summary"][1] += 1
            t2 = run_one([{"role": "system", "content": PROMPT}, {"role": "system", "content": summary, "name": "session_summary"}, *proj, {"role": "user", "content": q["q"]}], [OFFLOAD_READ_SCHEMA], acct_o)
            if judge(t2, ans): st["offload"][0] += 1
            st["offload"][1] += 1
    n = st["summary"][1] or 1
    print("\n=== 合成源 ===")
    print(f"summary : {st['summary'][0]}/{st['summary'][1]} = {st['summary'][0]/n*100:.1f}%")
    print(f"offload : {st['offload'][0]}/{st['offload'][1]} = {st['offload'][0]/n*100:.1f}%")
    print(f"成本: summary={acct_s.summary()['cost_cny']}元 offload={acct_o.summary()['cost_cny']}元")


if __name__ == "__main__":
    main()
