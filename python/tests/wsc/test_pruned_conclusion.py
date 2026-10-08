"""``[PRUNED]`` 助手卡结论位契约：标题行只是片段，不是结论。

现场（本会话热摘要实测）：``[PRUNED] 助手结论: ## 结论（先说现状，再说病因）``——
整行只有一个小标题，无内容、无指针；恢复第一步只能"验盘"。

口径：首行是 Markdown 标题 ⇒ 结论没拿到，**如实降标为片段**并补下一个非标题实质行；
首行非标题 ⇒ 与改动前逐字节一致（不动既有卡面）。
"""

from __future__ import annotations

from synaptic.prune import _assistant_conclusion


def test_heading_only_line_is_labelled_as_fragment_and_backfilled() -> None:
	text = "## 结论（先说现状，再说病因）\n\n正式结论：超时来自 proxy，已改 3000→1000 并复测通过。\n"
	got = _assistant_conclusion(text, 200)
	assert got.startswith("助手片段: ## 结论（先说现状，再说病因）"), got
	assert "已改 3000→1000" in got, f"下一行实质内容没补上：{got!r}"
	assert "助手结论" not in got, "标题行仍被冒充成结论"


def test_heading_without_body_still_labelled_as_fragment() -> None:
	"""补不到实质行时也不得冒充结论：片段就是片段。"""
	got = _assistant_conclusion("## 计划\n\n", 200)
	assert got == "助手片段: ## 计划", got


def test_non_heading_first_line_is_byte_identical_to_before() -> None:
	"""正控：非标题首行的行为与改动前逐字节一致（零 diff）。"""
	got = _assistant_conclusion("结论：登录超时的根因是 proxy 配置。\n第二行无关内容。", 200)
	assert got == "助手结论: 结论：登录超时的根因是 proxy 配置。", got


def test_short_lines_do_not_qualify() -> None:
	assert _assistant_conclusion("\n\n#\n\nok\n", 200) == ""
	assert _assistant_conclusion("", 200) == ""


def test_limit_is_respected(  ) -> None:
	text = "## 标题很长很长很长很长很长很长\n" + "正文" * 80
	got = _assistant_conclusion(text, 60)
	assert len(got) <= 60, (len(got), got)
