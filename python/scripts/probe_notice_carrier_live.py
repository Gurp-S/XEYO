"""阶段 3a-补：拿**实发全文**离线量载体（零厂商调用、零成本）。

为什么另开一条：`ab_notice_channel.py` 用金标正文比三档形状，量的是"开销差"；
把 398 条 transcript 的轮边界喂给装配口量不出发生率（状态复原不出来，三档全空）。
但引擎在每枪都会把**实发的整份 prompt** 落进 `~/.xeyo/sessions/*.working.json`
的 `last_x_sent` —— 那是真数据，不用调模型就能量：

1. 载体实况：真实那一枪里注入块是什么形态、占多少字节、占比多少；
2. 残留：已退役的伪对（``xeyo_env_notice``）在实发里还剩多少次；
3. 聚合的收益里能量出来的一半：逐维一条 vs 整段一条，**信封开销**差多少
   （每片段都自带开标签 + 来源声明，聚合只付一次）；
4. 同枪内重复：同一段状态文本在一枪里出现多次的字节数。

量不出来、必须说清的一半：**跨枪不重发**省多少（台账的收益）——`last_x_sent`
只存最新一枪，样本里没有"上一枪"。那一半只能往后从 ``notice.channel`` 审计与
usage 账本取数，且需要真实使用产生数据（不花钱，但要跑）。

用法（在 ``python/`` 下）::

    py -3.11 -m scripts.probe_notice_carrier_live
    py -3.11 -m scripts.probe_notice_carrier_live --samples 120 -v
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prompt.notice_channel import (  # noqa: E402
	NOTICE_ENVELOPE_CLOSE,
	NOTICE_ENVELOPE_OPEN,
	NOTICE_SOURCE_LINE,
	notice_open_tag,
)

from session.persistence import default_sessions_dir

# 权威解析：会话根被 XEYO_SESSIONS_DIR 搬走时，硬编码 home 会探到一个空目录，
# 探针于是把"读不到"当成"通报不存在"。
_XEYO_SESSIONS = default_sessions_dir()

#: 引擎注入块的自有标题（实发文本里靠它们认块；不靠自造词，只看装配口实际写的）
_INJECT_HEADS = (
	"# Continue",
	"# Memory index",
	"# 模式说明",
	"# Ask 模式",
	"# Plan 模式",
	"# 文件冲突",
	"# MCP 依赖异常",
	"# 浏览器预览",
	"# Nested",
	"# 子目录规则",
	"# Multi-Agent",
	"# Goal",
	"# 输出精简",
	"# 写代码精简",
	"# 工具面变更",
	"# 技能目录变更",
	"# Resume",
)


def _block_spans(text: str) -> list[tuple[int, int]]:
	"""注入块在 text 里的字符区间（合并重叠）。"""
	idxs = sorted({text.find(h) for h in _INJECT_HEADS if text.find(h) >= 0})
	if not idxs:
		return []
	cuts = _h1_positions(text)
	spans: list[tuple[int, int]] = []
	for at in idxs:
		end = next((c for c in cuts if c > at), len(text))
		if end > at:
			spans.append((at, end))
	merged: list[tuple[int, int]] = []
	for s, e in sorted(spans):
		if merged and s <= merged[-1][1]:
			merged[-1] = (merged[-1][0], max(merged[-1][1], e))
		else:
			merged.append((s, e))
	return merged


def _blocks_of(text: str) -> list[str]:
	"""按已知标题切出注入块，块尾止于**下一个任意 H1 标题**或串尾。

	早先只在我这份标题清单里找边界，命中一个早期标题就会把整段尾巴算成块
	（实测把占比顶到 64.6% —— 那是我的量法错，不是载体贵）。
	"""
	return [text[s:e].strip() for s, e in _block_spans(text)]


def _h1_positions(text: str) -> list[int]:
	"""所有行首 ``# ` 标题的位置（块尾候选）。"""
	out: list[int] = []
	pos = text.find("# ")
	while pos >= 0:
		if pos == 0 or text[pos - 1] == "\n":
			out.append(pos)
		pos = text.find("# ", pos + 1)
		if len(out) > 400:
			break
	return out


def _message_texts(sent: str) -> list[tuple[str, str]]:
	"""把实发 prompt 按消息拆开：``[(role, 纯文本)]``（解析失败则退回整串）。"""
	try:
		arr = json.loads(sent)
	except Exception:
		return [("raw", sent)]
	if not isinstance(arr, list):
		return [("raw", sent)]
	out: list[tuple[str, str]] = []
	for m in arr:
		if not isinstance(m, dict):
			continue
		role = str(m.get("role") or "")
		c = m.get("content")
		if isinstance(c, str):
			out.append((role, c))
		elif isinstance(c, list):
			parts: list[str] = []
			for b in c:
				if not isinstance(b, dict):
					continue
				for k in ("text", "content"):
					v = b.get(k)
					if isinstance(v, str):
						parts.append(v)
						break
			out.append((role, "\n".join(parts)))
	return out


def _samples(limit: int) -> list[dict[str, Any]]:
	files = sorted(
		glob.glob(str(_XEYO_SESSIONS / "*.working.json")),
		key=os.path.getmtime,
		reverse=True,
	)[:limit]
	out: list[dict[str, Any]] = []
	for f in files:
		try:
			o = json.loads(Path(f).read_text(encoding="utf-8"))
		except Exception:
			continue
		sent = o.get("last_x_sent")
		if not isinstance(sent, str) or len(sent) < 200:
			continue
		out.append({"path": f, "sent": sent, "mt": os.path.getmtime(f)})
	return out


def main(argv: list[str] | None = None) -> int:
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("--samples", type=int, default=600)
	ap.add_argument("-v", "--verbose", action="store_true")
	args = ap.parse_args(argv)

	samples = _samples(args.samples)
	if not samples:
		print("没有可用样本：~/.xeyo/sessions/*.working.json 里读不到 last_x_sent")
		return 1

	totals: list[int] = []
	inj: list[int] = []
	ratios: list[float] = []
	dup_bytes: list[int] = []
	block_counts: list[int] = []
	env_channel_hits = 0
	frag_hits = 0
	system_note_msgs = 0
	with_blocks = 0
	envelope_overhead = 0
	for s in samples:
		sent = s["sent"]
		msgs = _message_texts(sent)
		total = sum(len(t) for _r, t in msgs)
		totals.append(max(1, total))
		env_channel_hits += int("xeyo_env_notice" in sent)
		frag_hits += int(NOTICE_ENVELOPE_OPEN in sent)
		blocks: list[str] = []
		n_sys = 0
		ib = 0
		for role, text in msgs:
			if role == "system" and text.strip():
				# 中段 system：这就是 system 声道落库的留痕（顶层 system prompt
				# 不在 messages 里，由 PromptAssembler 单发，所以不会误计）。
				# 整条正文都是注入 ⇒ 不再在里面找块，避免重复计数。
				n_sys += 1
				ib += len(text)
				continue
			spans = _block_spans(text)
			blocks.extend(text[s:e] for s, e in spans)
			ib += sum(e - s for s, e in spans)
		system_note_msgs += n_sys
		if blocks:
			with_blocks += 1
		block_counts.append(len(blocks))
		inj.append(ib)
		ratios.append(ib / max(1, total))
		seen: dict[str, int] = {}
		for b in blocks:
			seen[b] = seen.get(b, 0) + 1
		dup_bytes.append(sum(len(k) * (v - 1) for k, v in seen.items() if v > 1))
		# 逐维一条 vs 整段一条的信封开销差：每条 = 开标签 + 换行 + 来源声明 + 闭标签
		if len(blocks) > 1:
			one = (
				len(notice_open_tag("world_state"))
				+ 1
				+ len(NOTICE_SOURCE_LINE)
				+ 1
				+ len(NOTICE_ENVELOPE_CLOSE)
			)
			per_dim = (
				(
					len(notice_open_tag("k"))
					+ 1
					+ len(NOTICE_SOURCE_LINE)
					+ 1
					+ len(NOTICE_ENVELOPE_CLOSE)
				)
				* len(blocks)
			)
			envelope_overhead += per_dim - one

	def _pct(xs: list[float]) -> str:
		s = sorted(xs)
		return f"中位 {statistics.median(xs):.1%}／p90 {s[int(len(s) * 0.9)]:.1%}"

	dist = {
		n: sum(1 for c in block_counts if (c == n if n < 3 else c >= 3))
		for n in (0, 1, 2, 3)
	}
	print(
		f"样本：{len(samples)} 枪实发 prompt（最新 "
		f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(max(s['mt'] for s in samples)))}）"
	)
	print(f"prompt 字数：中位 {statistics.median(totals):,.0f}")
	print(f"含注入块的枪：{with_blocks}/{len(samples)}；块数分布 0/1/2/≥3 = " + "/".join(str(dist[k]) for k in (0, 1, 2, 3)))
	print(f"注入字节/枪：中位 {statistics.median([float(v) for v in inj]):,.0f}")
	print(f"注入占比（按消息累加）：{_pct(ratios)}")
	print(f"同枪内重复注入字节：中位 {statistics.median([float(v) for v in dup_bytes]):,.0f}")
	print(f"中段 system 留痕条数：累计 {system_note_msgs:,}（这些正是要换成片段的形态）")
	print(f"已退役伪对（xeyo_env_notice）残留：{env_channel_hits} 枪的最后一枪")
	print(f"新包封片段（<system-reminder>）出现：{frag_hits} 枪")
	print(
		f"仅信封开销：逐维一条比整段一条多 {envelope_overhead:,} 字"
		f"（全部 {len(samples)} 枪累计）"
	)
	if args.verbose:
		worst = sorted(range(len(samples)), key=lambda i: -ratios[i])[:5]
		print("\n占比最高的五枪：")
		for i in worst:
			print(f"  {ratios[i]:.1%}  注入 {inj[i]:,} 字  {Path(samples[i]['path']).name}")
	print(
		"\n未量到（必须往后取数，不花钱但要真跑）：跨枪不重发省多少 —— "
		"last_x_sent 只存最新一枪，样本里没有上一枪可比。"
	)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
