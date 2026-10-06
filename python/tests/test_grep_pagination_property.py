"""Grep 分页算术随机性质测试（种子确定，seed=777）。

Grep 的 head_limit/offset 分页是模型自翻页的唯一依据（applied_limit 回执）。
历史上有过翻页类缺陷（大小写模式跨页、count 对切片求和）。这里钉四条：

1. 窗口 == items[offset : offset+eff]（参考实现=Python 切片；eff 由契约换算：
   limit==0 → 不限制；None/负 → DEFAULT_HEAD_LIMIT）；
2. applied_limit 为真值 ⇔ 确实发生了截断（未截断必须 None——回执不许骗模型）；
3. **翻页全覆盖**：客户端按 applied 前进，逐页拼起来 == 从 offset 起的全部条目，
   既不漏（丢行）也不重（叠行），且在有限步内必然走到 applied=None；
4. applied 非空 ⇒ 当前窗口非空（不给"有下一页"的空页）。
"""

from __future__ import annotations

import random

from tools.grep_tool.grep_tool import DEFAULT_HEAD_LIMIT, apply_head_limit

_SEED = 777
_CASES = 150
_LIMITS = [None, -3, 0, 1, 2, 7, 50, 250, 1000]


def _expected(items: list[str], limit: int | None, offset: int):
    off = max(0, offset or 0)
    if limit == 0:
        return items[off:], None
    eff = DEFAULT_HEAD_LIMIT if (limit is None or limit < 0) else limit
    sliced = items[off : off + eff]
    return sliced, (eff if (len(items) - off) > eff else None)


def test_head_limit_matches_reference_and_receipt_is_honest() -> None:
    rng = random.Random(_SEED)
    fails: list[tuple] = []
    for case in range(_CASES):
        n = rng.randint(0, 600)
        items = [f"row-{i}" for i in range(n)]
        offset = rng.choice([0, rng.randint(0, max(0, n - 1)), n, n + 5]) if n else rng.choice([0, 3])
        limit = rng.choice(_LIMITS)
        window, applied = apply_head_limit(items, limit, offset)
        exp_window, exp_applied = _expected(items, limit, offset)
        if window != exp_window:
            fails.append((case, "window", n, offset, limit, len(window), len(exp_window)))
            continue
        if applied != exp_applied:
            fails.append((case, "applied", n, offset, limit, applied, exp_applied))
            continue
        if applied is not None and not window:
            fails.append((case, "empty-but-applied", n, offset, limit))

    assert not fails, f"分页反例（seed={_SEED}）：{fails[:6]}"


def test_walking_pages_covers_every_row_exactly_once() -> None:
    rng = random.Random(_SEED + 1)
    fails: list[tuple] = []
    for case in range(_CASES):
        n = rng.randint(1, 600)
        items = [f"row-{i}" for i in range(n)]
        offset = rng.randint(0, n)
        limit = rng.choice([x for x in _LIMITS if x != 0])
        window, applied = apply_head_limit(items, limit, offset)
        if applied is None:
            continue  # 一页到底的情形由上一条覆盖
        seen = list(window)
        pos = offset
        for _step in range(1000):
            pos += applied
            nxt, nxt_applied = apply_head_limit(items, limit, pos)
            if not nxt and nxt_applied is not None:
                fails.append((case, "walk-stuck", n, offset, limit, pos))
                break
            seen.extend(nxt)
            if nxt_applied is None:
                break
        else:
            fails.append((case, "walk-runaway", n, offset, limit))
            continue
        if seen != items[offset:]:
            fails.append((case, "walk-mismatch", n, offset, limit, len(seen), n - offset))

    assert not fails, f"翻页覆盖反例（seed={_SEED + 1}）：{fails[:6]}"


def test_receipt_states_are_both_reachable() -> None:
    """方向控制：两类回执（None / 非空）都必须在这组边界里出现过。"""
    items = [f"r{i}" for i in range(5)]
    # 未截断的三样：刚好够、不限制（limit=0）、offset 已贴近尾部
    assert apply_head_limit(items, 5, 0)[1] is None
    assert apply_head_limit(items, 0, 0)[1] is None
    assert apply_head_limit(items, 2, 3)[1] is None
    # 截断：窗口截了
    window, applied = apply_head_limit(items, 2, 0)
    assert applied == 2 and len(window) == 2
    # 默认档也要出一条截断回执（items 5 < 250 时按未截断，故造 300 条）
    big = [f"b{i}" for i in range(300)]
    window_big, applied_big = apply_head_limit(big, None, 0)
    assert applied_big == DEFAULT_HEAD_LIMIT and len(window_big) == DEFAULT_HEAD_LIMIT
