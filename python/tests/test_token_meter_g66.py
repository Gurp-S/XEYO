"""G66: C2 经济门 token 计量统一走 utf-8 字节/4,弃 字符/4 双口径(中文低估 ~3x 根因)。"""

from __future__ import annotations

import importlib


def test_no_chars_over_4_residue_in_c2_economic_gate() -> None:
    src = importlib.import_module("memory.runtime").__loader__.get_source(
        "memory.runtime"
    ) or ""
    # 经济门不再出现"字符数/4"估算(旧双口径);同时必须引用 token_len/_region_tokens
    assert "transition_miss_tok = (len(ext) + tail_chars) / 4.0" not in src
    assert "saved_per_turn_tok = region_chars / 4.0" not in src
    assert "_region_tokens" in src
    assert "transition_miss_tok = token_len(ext) + tail_tokens" in src


def test_cjk_token_len_is_bigger_than_chars_over_4() -> None:
    from memory.token import token_len

    text = "中" * 400  # 400 中文字符, utf-8 1200 字节 → 300 tokens
    assert token_len(text) == 300
    assert token_len(text) > len(text) / 4.0  # 字符/4 = 100, 严重低估
