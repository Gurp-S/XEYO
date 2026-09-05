"""offload_read_eval — #3 L3 机制(offload>512 + 引用) + 测 Read vs offload-read 谁好。

- 把锚定会话的长 tool_result(>512) 外部化到 tmp 文件，投影里留"带头引用"。
- probe 问事实题；模型用工具(offload_read 或 read_file)检索 offload 文件，再答。
- 默认 dry-run（构建+报告，不调 LLM）；加 --run 才调 DeepSeek。
"""
from __future__ import annotations

import argparse, json, os, sys
from pathlib import Path

PY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PY_ROOT))
HOME = Path.home()
SESSION = HOME / ".xeyo" / "sessions" / "sess_mtlpmznl_0iapt2.jsonl"
PROBES = PY_ROOT / "scripts" / "probes" / "ab_real_probes.json"
THRESHOLD = 512
OFFLOAD_DIR = PY_ROOT / ".xeyo_offload_tmp"

OFFLOAD_READ_SCHEMA = {
    "name": "offload_read",
    "description": "按行区间读取一个被外部化的工具结果文件，返回该区间内容。",
    "input_schema": {"type": "object", "properties": {
        "path": {"type": "string", "description": "外部化工具结果文件路径"},
        "start": {"type": "integer", "description": "起始行(含)"},
        "end": {"type": "integer", "description": "结束行(含)"},
    }, "required": ["path"]},
}
READ_FILE_SCHEMA = {
    "name": "read_file",
    "description": "读取一个文件（这里用于取回外部化的工具结果全文）。",
    "input_schema": {"type": "object", "properties": {
        "path": {"type": "string", "description": "文件路径"},
    }, "required": ["path"]},
}

BASELINE = "你是问答助手。基于上下文回答；若上下文缺细节，可用给定工具检索外部化的工具结果文件。只回答案本身。"


def load_messages():
    return [json.loads(l) for l in SESSION.read_text(encoding="utf-8").splitlines() if l.strip()]


def _text(m):
    c = m.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(str(b.get("content") or b.get("text") or "") for b in c if isinstance(b, dict))
    return str(c or "")


def _tool_results(msgs):
    """返回 [(msg_idx, uid, raw, name)] 所有 tool_result。"""
    out = []
    for idx, m in enumerate(msgs):
        c = m.get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                out.append((idx, str(b.get("tool_use_id") or ""), str(b.get("content") or ""), m.get("name") or ""))
    return out


def build_offloaded_projection(msgs, left, *, use_offload=True):
    """把左区 tool_result 逐个：>threshold → offload+引用；否则原样。返回 (投影列表, offload_file_map)."""
    offload_map = {}
    if not use_offload:
        return msgs[:left], offload_map
    proj = []
    for idx, m in enumerate(msgs[:left]):
        c = m.get("content")
        if isinstance(c, list):
            nb = []
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    raw = str(b.get("content") or "")
                    if len(raw) > THRESHOLD:
                        fpath = OFFLOAD_DIR / f"{idx}.tool.txt"
                        fpath.parent.mkdir(parents=True, exist_ok=True)
                        fpath.write_text(raw, encoding="utf-8")
                        head = raw[:120].replace("\n", " ")
                        ref = f"[tool offloaded: {fpath}  ({raw.count(chr(10))+1} lines) 头: {head}...]"
                        nb.append({**b, "content": ref})
                        offload_map[idx] = str(fpath)
                    else:
                        nb.append(b)
                else:
                    nb.append(b)
            m2 = dict(m)
            m2["content"] = nb
            proj.append(m2)
            if idx in offload_map:
                # 记录该消息对应 offload 文件
                pass
        else:
            proj.append(m)
    return proj, offload_map


def _exec_tool(tool_name, args):
    path = args.get("path") or ""
    try:
        p = Path(path)
        if not p.is_file():
            return f"(文件不存在: {path})"
        txt = p.read_text(encoding="utf-8")
        if tool_name == "offload_read":
            s = int(args.get("start") or 1)
            e = int(args.get("end") or 999999)
            lines = txt.split("\n")
            return "\n".join(lines[max(0, s-1):e])
        return txt
    except Exception as ex:
        return f"(read err: {ex})"


def run_one(messages, tools, acct):
    from evals.client import chat
    cur = [dict(m) for m in messages]
    for _ in range(3):
        resp = chat(cur, tools=tools, acct=acct, max_tokens=240, temperature=0.0)
        tcs = resp.get("tool_calls") or []
        if not tcs:
            return resp.get("content") or ""
        blocks, results = [], []
        for i, tc in enumerate(tcs):
            cid = f"call_{_}_{tc.get('name','t')}_{i}"
            args = tc.get("arguments") or {}
            blocks.append({"type": "tool_use", "id": cid, "name": tc.get("name", "t"), "input": args})
            results.append({"type": "tool_result", "tool_use_id": cid, "content": _exec_tool(tc.get("name", ""), args)})
        cur.append({"role": "assistant", "content": blocks})
        cur.append({"role": "user", "content": results})
    return chat(cur, tools=tools, acct=acct, max_tokens=240, temperature=0.0).get("content") or ""


def judge(text, answers):
    low = (text or "").lower()
    return any(str(a).strip().lower() in low for a in answers)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args()
    from evals.client import account, ensure_stdout_utf8
    ensure_stdout_utf8()

    from memory.runtime import c2_cut_index, deterministic_c2_summary
    msgs = load_messages()
    left = c2_cut_index(msgs, None)
    proj, omap = build_offloaded_projection(msgs, left, use_offload=True)
    n_offloaded = len(omap)
    summary = deterministic_c2_summary(msgs[:left], style="new", max_text=160)
    qs = json.loads(PROBES.read_text(encoding="utf-8")).get("questions") or []
    print(f"rows={len(msgs)} 左区={left} offload(>{THRESHOLD})={n_offloaded} 摘要chars={len(summary)}")

    # 投影 = 摘要 system + offloaded 左区 + user 问题（模型可读到 offload 引用）
    proj_msgs = [{"role": "system", "content": summary, "name": "session_summary"}] + proj + []
    if not args.run:
        print(f"\n[dry-run] offload 文件目录: {OFFLOAD_DIR}（已写 {n_offloaded} 个文件）")
        print(f"  将用 offload_read 与 read_file 各跑一遍 24 题×3 次，比较 pass 率 + 检索行为。")
        print("  真正测试: python scripts/offload_read_eval.py --run")
        return

    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    acct_or = account("offload_read"); acct_rf = account("read_file")
    stats = {"offload_read": [0, 0], "read_file": [0, 0]}
    for q in qs:
        ans = q.get("expect_contains") or []
        for rep in range(3):
            for tool, acct, schema, key2 in [
                ("offload_read", acct_or, [OFFLOAD_READ_SCHEMA], "offload_read"),
                ("read_file", acct_rf, [READ_FILE_SCHEMA], "read_file"),
            ]:
                msgs2 = [{"role": "system", "content": BASELINE}] + proj_msgs + [{"role": "user", "content": q.get("q", "")}]
                t = run_one(msgs2, schema, acct)
                if judge(t, ans):
                    stats[key2][0] += 1
                stats[key2][1] += 1
        print(f"  {q.get('id')} done")
    n = stats["offload_read"][1] or 1
    print("\n=== 结果 ===")
    for k in ("offload_read", "read_file"):
        print(f"{k}: pass {stats[k][0]}/{stats[k][1]} = {stats[k][0]/n*100:.1f}%")
    print(f"成本: offload_read={acct_or.summary()['cost_cny']}元  read_file={acct_rf.summary()['cost_cny']}元")


if __name__ == "__main__":
    main()
