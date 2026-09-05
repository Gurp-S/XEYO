"""memory.simulator.fidelity：r_summary 的离线确定性测量。"""

from __future__ import annotations

from memory.simulator.fidelity import (
    build_corpus,
    extract_facts,
    extract_terms,
    measure_corpus,
    measure_region,
)


def _msg_user(text: str) -> dict:
    return {"role": "user", "content": text}


def _asst_use(uid: str, name: str) -> dict:
    return {"role": "assistant", "content": [{"type": "tool_use", "id": uid, "name": name, "input": {"q": "x"}}]}


def _tool(uid: str, content: str, *, name: str = "Grep") -> dict:
    return {"role": "user", "content": [{"type": "tool_result", "tool_use_id": uid, "content": content, "is_error": False}], "name": name}


# ---------- 事实抽取 ----------

def test_extract_terms_excludes_stopwords_and_digits():
    terms = extract_terms("the quick brown fox 12345 runs")
    assert "tok:quick" in terms
    assert "tok:brown" in terms
    assert "tok:fox" in terms
    assert not any((" " + t + " ") == " the " for t in terms)  # 停用词被剔除
    assert not any(t.startswith("num:") for t in terms)  # 术语级不含数字


def test_extract_facts_adds_pathline_and_numbers():
    facts = extract_facts("src/engine.py:42: x == 99 ValueError")
    assert any(f.startswith("pathline:") for f in facts)
    assert any(f.startswith("num:") for f in facts)
    assert any(f.startswith("err:") for f in facts)


# ---------- 留存 ----------

def test_region_text_only_high_term_retention():
    # 纯文本：摘要保留原文 → r_term 接近 1.0
    msgs = [
        _msg_user("start"),
        _msg_user("请解释 alpha 规则"),
        {"role": "assistant", "content": "answer beta 规则"},
        _msg_user("短 q"),
        {"role": "assistant", "content": "短 a"},
    ]
    res = measure_region(msgs, cursor=len(msgs) - 2)
    assert res["r_term"] is not None
    assert res["r_term"] > 0.9
    assert res["r_literal"] > 0.9


def test_region_grep_term_retention_high_literal_low():
    grep = "\n".join(f"src/core/engine.py:{40 + i}: def run(self):" for i in range(120))
    msgs = [
        _msg_user("find caller"),
        _asst_use("g1", "Grep"),
        _tool("g1", grep),
        {"role": "assistant", "content": "done"},
    ]
    # 把 grep tool_result 也纳入测量区（cursor=3 含前 3 条）
    res = measure_region(msgs, cursor=3)
    # 类型感知摘要保留 文件/关键词/统计 → 术语留存高
    assert res["r_term"] is not None and res["r_term"] > 0.7
    # 但每条匹配行/行号的"细节"大多被丢弃 → 字面留存低
    assert res["r_literal"] is not None and res["r_literal"] < res["r_term"]


def test_literal_is_lower_bound():
    from memory.simulator.fidelity import _survives, extract_facts, extract_terms

    txt = "src/a.py:1: alpha\n" * 50
    summary_low = "src/a.py alpha"
    t_facts = extract_terms(txt)
    l_facts = extract_facts(txt)
    t_kept = sum(1 for f in t_facts if _survives(f, summary_low))
    l_kept = sum(1 for f in l_facts if _survives(f, summary_low))
    assert len(t_facts) <= len(l_facts)  # 字面更多独立事实
    assert (t_kept / len(t_facts)) >= (l_kept / len(l_facts))


# ---------- 语料 ----------

def test_corpus_measurement_bounded():
    res = measure_corpus(build_corpus(n_turns=6))
    assert res["n_cases"] >= 1
    assert res["r_summary"] is not None
    assert 0.0 <= res["r_summary"] <= 1.0
    for c in res["cases"]:
        assert 0.0 <= c["r_term"] <= 1.0
        assert c["chars_left"] > 0
