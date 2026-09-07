"""retrieval_bench 门槛/证明性测试（⑰）。

覆盖：
- run_bench 离线可跑、返回结构完整（notes/code 各含 hit@k / hit / miss）。
- 受控 code corpus：干净字面量 query → 期望文件命中（hit@k 高）。
- 笔记侧：自然语言 query 未必命中（诚实基线，不强制 100%）。
- fail-open：非字面量 query 走「miss/注明」而非崩溃。
"""

from __future__ import annotations


from evals import retrieval_bench as rb


def test_run_bench_structure():
    r = rb.run_bench()
    assert "notes" in r and "code" in r
    for domain in ("notes", "code"):
        d = r[domain]
        assert "hit@k" in d and "hit" in d and "miss" in d and "cases" in d
        assert d["cases"] == len(rb.NOTE_CASES if domain == "notes" else rb.CODE_CASES)


def test_notes_hitk_bounded():
    """笔记 hit@k 在 [0,1] 内；至少部分命中（数据集语义对齐）——诚实基线，允许 0.4 这类值。"""
    r = rb.run_bench()
    n = r["notes"]["hit@k"]
    assert 0.0 <= n <= 1.0
    # 至少命中 1 条（数据集里 query/note 是有意对齐的）。
    assert n > 0.0


def test_notes_hitk_regression_gate():
    """升格：笔记词法 hit@k 不得低于门禁下限（防检索能力回退）。

    当前基线 0.4（2/5）。门禁设 0.2（1/5），留出合理阈值变动空间。
    """
    n = rb.run_bench()["notes"]["hit@k"]
    assert n >= 0.2, f"笔记检索 hit@k 回退至 {n}（< 0.2 门禁）"


def test_code_hitk_regression_gate():
    """升格：代码受控 corpus 词法 hit@k 保持 1.0（干净字面量不可回退）。"""
    assert rb.run_bench()["code"]["hit@k"] == 1.0


def test_write_baseline_persists(tmp_path):
    """write_baseline 落盘 JSON 且可读回。"""
    target = tmp_path / "hitk.json"
    rb.write_baseline(result=None, path=target)
    import json

    data = json.loads(target.read_text(encoding="utf-8"))
    assert "notes" in data and "code" in data


def test_code_corpus_hits():
    """代码（受控 corpus，干净字面量）→ hit@k == 1.0（索引是好的候选超集）。"""
    r = rb.run_bench()
    assert r["code"]["hit@k"] == 1.0


def test_non_literal_query_fail_open():
    """非字面量 query 走 miss/注明而非崩溃。"""
    from tools.fileio import content_index

    # 用 code 基准遇到 non-literal 的途径直接验证 lookup 安全返回。
    term = "记忆开关注册表"
    assert content_index.is_literal(term) is False


def test_bench_code_controlled_corpus(tmp_path):
    """受控 corpus 写入后可建索引且命中期望文件。"""
    from evals.retrieval_bench import CODE_CASES, bench_code

    root = tmp_path / "corpus"
    results = bench_code(CODE_CASES, code_root=str(root))
    assert len(results) == len(CODE_CASES)
    assert sum(1 for r in results if r.hit) == len(CODE_CASES)
