# -*- coding: utf-8 -*-
"""LoCoMo-Refined 冒烟（v61 开，真记忆系统投影）：60 题。

真记忆系统：长对话 → C2 压缩投影（XEYO_L5=v61）→ 用投影上文（压缩后记忆）答官方题。
非直接塞上下文——测的是"压缩/会话边界后早期事实保留"。
预算护栏：XEYO_LOCOMO_BUDGET_CNY（默认 2）、题量 60。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BUDGET = float(os.environ.get("XEYO_LOCOMO_BUDGET_CNY", "2.0").strip() or 0.0)
N_Q = int(os.environ.get("XEYO_LOCOMO_NQ", "60").strip() or 60)


def _msgs_of(conv) -> list[dict]:
    out: list[dict] = []
    for sess in conv.get("sessions") or []:
        for m in sess.get("messages") or []:
            t = m.get("text")
            if isinstance(t, str) and t.strip():
                out.append({"role": "user" if m.get("speaker") == conv.get("speaker_a") else "assistant",
                            "content": f"[{m.get('speaker')}] {t.strip()}"})
    return out


async def main() -> int:
    ap = __import__("argparse").ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    qs = [json.loads(l) for l in (data_dir / "questions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    convs = {json.loads(l)["sample_id"]: json.loads(l) for l in (data_dir / "conversations.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
    qs = [q for q in qs if q.get("sample_id") in convs][:N_Q]
    print(f"冒烟题={len(qs)}")

    from memory.memory_switches import save
    save({"XEYO_L5": "v61"}, cwd=str(ROOT))  # 工作区级 settings（v61 开）
    from evals.client import chat, account, ensure_stdout_utf8
    from memory.runtime import apply_c2_messages, c2_cut_index
    from memory.working import WorkingSnapshot
    from memory.simulator.scenarios import state_from_messages
    ensure_stdout_utf8()
    acct = account("locomo_smoke")
    cost = 0.0
    out = []
    done = 0

    for q in qs:
        conv = convs[q["sample_id"]]
        api = _msgs_of(conv)
        if not api:
            continue
        try:
            s0 = state_from_messages(api, cursor=0)
            cut = c2_cut_index(api, s0)
            w = WorkingSnapshot(session_id=f"locomo_{q['sample_id']}", turns_since_c2=4, compact_cursor=max(0, cut - 4))
            if cut > 0:
                proj = apply_c2_messages(api, w)  # v61 开：C2 压缩左段
            else:
                proj = api
            # 用投影上文（压缩后）答题
            ctx = "\n".join(str(m.get("content"))[:200] for m in proj[:60])
            g = chat([
                {"role": "system", "content": "你是问答助手。基于提供的会话历史回答。只回答案本身。"},
                {"role": "user", "content": "会话历史（对话压缩后保留事实）：\n" + ctx},
                {"role": "user", "content": "问题：" + q["question"]},
            ], acct=acct, model="deepseek-v4-flash", max_tokens=200, temperature=0.0)
            pred = (g.get("content") or "").strip()
            cost += acct.summary()["cost_cny"]
            out.append({"qa_id": q["qa_id"], "prediction": pred})
            done += 1
            if done % 20 == 0:
                print(f"  已答 {done}/{len(qs)} 成本≈{cost:.3f}元")
            if BUDGET > 0 and cost >= BUDGET:
                print(f"  [护栏] 达预算 {BUDGET}元，停")
                break
        except Exception as e:
            out.append({"qa_id": q["qa_id"], "prediction": ""})
            print(f"  题 {q['qa_id']} 异常: {e}")
            done += 1

    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in out) + "\n", encoding="utf-8")
    print(f"写出 {len(out)} → {p}; 成本≈{acct.summary()['cost_cny']:.4f}元")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
