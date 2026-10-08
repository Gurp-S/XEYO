"""前提自检助手（#15 / P1）：断言"测试赖以成立的事实"，失败消息必须自报家门。

为什么单列一个词（都有实测）：本会话里两次失败**错在测试而不是产品**——

1. 断言"`files=` 必须出现"，而既有正确行为是"只补结论里未出现的路径"（那张卡已内联
   `src/auth.ts`）⇒ 红的是测试，不是引擎；
2. 改名只改了一半（两处调用点漏改）⇒ `NameError`，2 failed——"我假设它只有一处调用"。

两次的共同形状：**红的时候看不出"是产品坏了"还是"我假设错了"**。于是第一反应容易变成去改产品。
`assert_premise` 把后者显式标出来：消息以「前提失败」起头，并带 `why`（我假设了什么）。

用法：产品断言继续写 `assert`；"我这个测试赖以成立的世界"写 `assert_premise`。
"""

from __future__ import annotations


def assert_premise(cond: object, why: str) -> None:
	"""断言 `cond` 成立；否则抛「前提失败：<why>」。

	与 `assert` 的唯一区别是**归因层级**：`assert` 失败 ⇒ 产品不符预期；
	`assert_premise` 失败 ⇒ 我的假设不符现实（先改测试或改假设，别急着改产品）。
	"""
	if not cond:
		raise AssertionError(f"前提失败：{why}")
