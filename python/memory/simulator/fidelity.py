"""r_summary 的确定性、离线实测——把"内容保真"从假设变成测量。

设计 §4.7 的 P1 备注是"用 \\hat r(方法, 内容) 动态估（可到 0.95）"；本文实现一个
纯函数、离线、无 I/O、不调用模型的测量器。它算两个口径：

- **r_term**（语义近似，建议作为 r_summary）：只看"有信息量的去重主题词"是否仍在
  C2 摘要里。它对应设计的语义先验——"这条消息的主题还在不在摘要里"。
- **r_literal**（字面下界）：把每个 `path:line:`、每个数字都当成独立事实，衡量
  "源内容有多少细节真的还在摘要里"。工具输出几乎必然很低——这正是 C2 会丢弃
  行级细节的诚实度量，可作为下界。

测量流程：把可压区 [0, cursor) 压成 C2 摘要（deterministic_c2_summary，即实际送模型的
那段"语义片段"），逐单元统计事实留存，按单元 token 数加权求 r_summary。
纯函数、确定性、无 I/O、不调用模型。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import mean
from typing import Iterable

from memory.runtime import deterministic_c2_summary
from memory.simulator.state_model import token_len

# 通用停用词：不含信息，不作为"事实"
_STOP = frozenset(
    "the a an and or of to in on for with is are was were be been it its this that these "
    "those into from as at by has have had not do does did will would can could should may "
    "might more most some any all no yes if then else than so also already just only about "
    "there here what when where which who whom how why let us our your my you we they he she"
    .split()
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{3,}")
_PATHLINE_RE = re.compile(r"([A-Za-z0-9_./\\\-]{2,80}):(\d+):")
_ERROR_RE = re.compile(r"\b(?:[A-Z][A-Za-z0-9]*Error|Exception|AssertionError|Traceback)\b")


def extract_terms(text: str) -> set[str]:
    """有信息量的去重主题词 + 报错类型（术语级事实）。"""
    text = text or ""
    terms: set[str] = set()
    for m in _TOKEN_RE.finditer(text.lower()):
        t = m.group(0)
        if len(t) < 3 or t in _STOP or t.isdigit():
            continue
        terms.add("tok:" + t)
    for m in _ERROR_RE.finditer(text):
        terms.add("err:" + m.group(0).lower())
    return terms


def extract_facts(text: str) -> set[str]:
    """更高分辨率事实：术语 + 每个 path:line: + 每个多位数（字面级）。"""
    facts = extract_terms(text)
    for pl in set(re.findall(r"([A-Za-z0-9_./\\\-]{2,80}):\d+:", text)):
        facts.add("pathline:" + pl.lower())
    for num in set(re.findall(r"\b\d{2,}\b", text)):
        facts.add("num:" + num)
    return facts


def _survives(fact: str, summary_low: str) -> bool:
    if fact.startswith("tok:"):
        return fact[4:] in summary_low
    if fact.startswith("err:"):
        return fact[4:] in summary_low
    if fact.startswith("pathline:"):
        return fact[9:] in summary_low
    if fact.startswith("num:"):
        return fact[4:] in summary_low
    return fact in summary_low


def _retention(facts: set[str], summary_low: str) -> tuple[int, int]:
    if not facts:
        return 0, 0
    kept = sum(1 for f in facts if _survives(f, summary_low))
    return kept, len(facts)


def _unit_text(msg: dict) -> str:
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_result":
                parts.append(str(b.get("content") or ""))
            elif b.get("type") == "text":
                parts.append(str(b.get("text") or ""))
            elif b.get("type") == "tool_use":
                parts.append(str(b.get("name") or "") + " " + str(b.get("input") or ""))
            else:
                parts.append(str(b.get("text") or b.get("content") or b.get("input") or ""))
        return "\n".join(parts)
    return ""


def _kind_of(msg: dict) -> str:
    from memory.runtime import _assistant_tool_ids, _tool_result_ids

    if _assistant_tool_ids(msg):
        return "tool_use"
    if _tool_result_ids(msg):
        return "tool_result"
    return str(msg.get("role") or "unknown")


def measure_region(messages: list[dict], *, cursor: int, max_text: int = 160) -> dict:
    """测量一次 C2：把 [0, cursor) 压成摘要，逐单元算术语留存 + 字面留存。"""
    left = messages[:cursor]
    summary = deterministic_c2_summary(left, style="new", max_text=max_text)
    summary_low = summary.lower()
    aggregate = {"r_term": 0.0, "r_literal": 0.0, "wsum": 0.0}
    per_type: dict[str, list[float]] = {}
    total = {"term_facts": 0, "term_kept": 0, "lit_facts": 0, "lit_kept": 0}
    # 顺便统计未压缩前后的字符（给报告用）
    for msg in left:
        txt = _unit_text(msg)
        if not txt.strip():
            continue
        v = max(token_len(txt), 1)
        t_kept, t_total = _retention(extract_terms(txt), summary_low)
        if t_total:
            r_t = t_kept / t_total
            aggregate["r_term"] += v * r_t
            aggregate["wsum"] += v
            name = str(msg.get("name") or "").lower() or _kind_of(msg)
            per_type.setdefault(name, []).append(r_t)
            total["term_facts"] += t_total
            total["term_kept"] += t_kept
        l_kept, l_total = _retention(extract_facts(txt), summary_low)
        if l_total:
            total["lit_facts"] += l_total
            total["lit_kept"] += l_kept
    w = aggregate["wsum"]
    r_term = round(aggregate["r_term"] / w, 4) if w else None
    r_literal = round(total["lit_kept"] / total["lit_facts"], 4) if total["lit_facts"] else None
    return {
        "cursor": cursor,
        "messages_compressed": len(left),
        "chars_left": sum(len(_unit_text(m)) for m in left),
        "summary_chars": len(summary),
        "r_term": r_term,
        "r_literal": r_literal,
        "per_type": {k: round(mean(v), 4) for k, v in per_type.items()},
    }


def build_corpus(*, n_turns: int = 18) -> list[tuple[str, list[dict]]]:
    """构造混合工具会话语料（Grep/Read/Bash/报错 + 纯文本），返回 (label, messages)。"""
    from memory.simulator.scenarios import _msg_asst_use, _msg_tool, _msg_user

    def grep_blob(n: int) -> str:
        return "\n".join(f"src/core/engine.py:{40 + i}:  def run(self):" for i in range(n))

    def read_blob(lines: int) -> str:
        return "".join(f"def func{i}():\n    return {i}\n" for i in range(lines))

    def bash_out() -> str:
        lines = [f"step {i}: ok {i * 11}" for i in range(80)]
        lines.append("ERROR: exit code 2")
        lines.append("Traceback (most recent call last):")
        lines.append('  File "run.py", line 9, in <module>')
        lines.append("    main()")
        lines.append("ValueError: bad value")
        return "\n".join(lines)

    cases: list[tuple[str, list[dict]]] = []
    for rep in range(2):
        msgs: list[dict] = [{"role": "user", "content": "start task"}]
        for i in range(n_turns):
            k = i % 3
            uid = f"{['g', 'r', 'b'][k]}{rep}_{i}"
            if k == 0:
                msgs.append(_msg_asst_use(uid, "Grep", "grep needle"))
                msgs.append(_msg_tool(uid, "Grep", grep_blob(120)))
            elif k == 1:
                msgs.append(_msg_asst_use(uid, "Read", "read file"))
                msgs.append(_msg_tool(uid, "Read", read_blob(100)))
            else:
                msgs.append(_msg_asst_use(uid, "Bash", "run tests"))
                msgs.append(_msg_tool(uid, "Bash", bash_out()))
            msgs.append({"role": "assistant", "content": f"conclusion {i}"})
        cases.append((f"mixed:{rep}:{n_turns}", msgs))
    txt: list[dict] = [{"role": "user", "content": "start"}]
    for i in range(n_turns):
        txt.append(_msg_user(f"short q {i}: 请解释 keep/C1/C2"))
        txt.append({"role": "assistant", "content": f"answer {i}: keep/C1/C2 是三档压缩动作"})
    cases.append(("text_only", txt))
    return cases


def measure_corpus(cases: Iterable[tuple[str, list[dict]]]) -> dict:
    """对语料整体测量，token 加权聚合 r_term 与 r_literal。"""
    r_w = 0.0
    wsum = 0.0
    per_case: list[dict] = []
    per_type_agg: dict[str, list[float]] = {}
    for label, msgs in cases:
        if len(msgs) < 8:
            continue
        cursor = max(0, len(msgs) - 6)  # 预留尾部 KEEP_TAIL=6
        if cursor <= 0:
            continue
        res = measure_region(msgs, cursor=cursor)
        per_case.append({**res, "label": label})
        if res["r_term"] is not None and res["chars_left"]:
            r_w += res["r_term"] * res["chars_left"]
            wsum += res["chars_left"]
        for k, v in res["per_type"].items():
            per_type_agg.setdefault(k, []).append(v)
    agg_r = round(r_w / wsum, 4) if wsum else None
    return {
        "r_summary": agg_r,
        "n_cases": len(per_case),
        "cases": per_case,
        "per_type": {k: round(mean(v), 4) for k, v in per_type_agg.items()},
    }


def run_measured(path: Path | None = None) -> dict:
    """离线跑一遍测量并落盘 JSON，返回结果。"""
    corpus = build_corpus()
    res = measure_corpus(corpus)
    if path is None:
        path = Path(__file__).with_name("out") / "r_summary_measured.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return res


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="离线实测 r_summary（字面/术语留存）")
    ap.add_argument("--apply-live", action="store_true",
                    help="把实测 r_summary 写入 params_overlay.json（默认只报告，不写 overlay）")
    args = ap.parse_args()
    res = run_measured()
    print("r_summary(term) =", res.get("r_summary"))
    print("per_type =", res.get("per_type"))
    for c in res.get("cases", []):
        print(f"  {c['label']:<14s} r_term={c.get('r_term')} r_literal={c.get('r_literal')} "
              f"chars={c.get('chars_left')}->{c.get('summary_chars')}")
    if args.apply_live:
        from memory.simulator.params import write_overlay
        write_overlay({"r_summary": res["r_summary"]})
        print("overlay params_overlay.json r_summary <-", res["r_summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
