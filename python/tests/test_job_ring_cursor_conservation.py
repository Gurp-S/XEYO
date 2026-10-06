"""`_Ring` 的游标守恒契约（后台作业输出通道的算术地基）。

两条不变量按"读法"分开钉，因为它们的期望正好相反：

- 追赶读（每次 push 后立刻 read）⇒ 环不可能把还没交付的字符挤掉 ⇒
  拼起来必须逐字等于原文，且 `truncated` 全程 False（出声=说谎）。
- 懒读（先全 push 再一次 read）⇒ 只剩尾部 ⇒ 读到的必须恰好是最后 cap 个字符，
  且 `truncated` 必须 True（不出声=让模型以为拿到了全文）。

第一版性质档把"总推入量 > cap"当成"一定有丢失"，于是 165/400 轮假红：
追赶读的游标始终追得上，环挤掉的都是已经交付过的字符。这条区分留在文件里，
免得下一次有人按"溢出=丢数据"改判据。
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.job_registry import _Ring  # noqa: E402

ALPHABET = "abcXYZ019 \n"


def _chunks(rng: random.Random, n: int, cap: int) -> list[str]:
    return [
        "".join(rng.choice(ALPHABET) for _ in range(rng.randint(1, cap)))
        for _ in range(n)
    ]


def test_catch_up_reads_are_char_exact() -> None:
	"""追赶读：逐字守恒，且绝不虚报 truncated。"""
	rng = random.Random(20261003)
	cap = 512
	for _ in range(200):
		ring = _Ring(cap=cap)
		pushed: list[str] = []
		seen: list[str] = []
		cur = 0
		for chunk in _chunks(rng, rng.randint(1, 8), cap):
			ring.push(chunk)
			pushed.append(chunk)
			text, new_cur, truncated = ring.read(cur)
			assert new_cur >= cur, "游标不得回退"
			assert not truncated, "每次都读了却报截断=说谎"
			seen.append(text)
			cur = new_cur
		assert "".join(seen) == "".join(pushed)


def test_lazy_read_returns_the_tail_and_says_so() -> None:
	"""懒读：只剩尾部时必须给最后 cap 个字符，并出声。"""
	rng = random.Random(777)
	cap = 512
	overflow_seen = 0
	for _ in range(200):
		ring = _Ring(cap=cap)
		full = "".join(_chunks(rng, rng.randint(1, 10), cap * 2))
		for part in (full[i : i + 40] for i in range(0, len(full), 40)):
			ring.push(part)
		text, cur, truncated = ring.read(0)
		if len(full) <= cap:
			assert text == full and not truncated
			assert cur == len(full)
			continue
		overflow_seen += 1
		assert text == full[-cap:], f"应给最后 {cap} 字，实得 {len(text)} 字"
		assert truncated, "挤掉了早期内容却不出声"
		assert cur == len(full), f"游标应是绝对末尾 {len(full)}，实为 {cur}"
	assert overflow_seen >= 50, f"这一档几乎没走到溢出分支（溢出轮次={overflow_seen}），断言是空门"


def test_empty_and_monotonic_edges() -> None:
	ring = _Ring(cap=256)
	assert ring.read(0) == ("", 0, False)
	ring.push("")  # 空块不进账
	assert ring.read(0) == ("", 0, False)
	ring.push("hello")
	text, cur, trunc = ring.read(2)
	assert text == "llo" and cur == 5 and not trunc
	# 已经读过的游标再读一次 = 空，且不回退
	assert ring.read(cur) == ("", 5, False)
