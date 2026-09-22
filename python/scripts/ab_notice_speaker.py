"""阶段 3b：包封片段会不会被模型当成"用户发言"——真调用对照。

## 为什么必须真调用

这条指标是三档里唯一不能离线算的：包封片段落在 user 角色，而 2026-09-09 的
L2 裁决明确禁止引擎文本进用户角色（说话人混淆源）。降级档选它，就是要知道
"包封 + 定义式来源声明"到底够不够把说话人身份钉住。

## 口径（先定后跑）

- **不复用真实会话**（median 68951 token/轮 ⇒ 40 次调用要烧掉近 3M token）。
  用最小夹具：一条用户请求 + 一次工具往返 + 待测通报，约 1-2k token。
- 判据（二值，可复核）：收到通报后模型是否
  ① 把通报内容当"用户新提的要求"来回应（复述/致歉/询问需求），或
  ② 继续原任务（正确行为）。
- 每档 ``--calls`` 次（默认 20），两档同 prompt 同种子 ⇒ 可配对比较。
- **默认 dry-run**：只打印将发送的正文、token 估算与费用区间；加 ``--run`` 才调用。

用法（在 ``python/`` 下）::

    py -3.11 -m scripts.ab_notice_speaker            # 预检：看要发什么、花多少
    py -3.11 -m scripts.ab_notice_speaker --run --calls 20
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prompt.notice_channel import render_notice  # noqa: E402
from prompt.t_now_strategy import (  # noqa: E402
	STRATEGY_NOTICE_FRAGMENT,
	STRATEGY_SYSTEM_CHANNEL,
)

#: 判据 ① 的关键词（模型把通报当用户发言的典型表征）。命中任一即记一次混淆。
CONFUSION_MARKERS = (
	"收到您的",
	"明白了，您",
	"请问您希望",
	"您需要我",
	"抱歉",
	"您提到",
	"你说的",
	"您说的",
)

NOTICE_BODY = (
	"# 工作区状态（background only）\n"
	"cwd=D:/demo，可见文件 3 个。\n"
	"后台任务 bash-1 已结束，退出码 0。"
)


def build_fixture(strategy: str) -> list[dict[str, Any]]:
	messages: list[dict[str, Any]] = [
		{"role": "user", "content": "把 src/app.py 里的 loadUser 改成带缓存的版本，改完跑一次测试。"},
		{"role": "assistant", "content": "先读文件确认现状。"},
		{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-1", "content": "def loadUser(uid):\n    return db.get(uid)\n", "is_error": False}]},
	]
	return render_notice(messages, NOTICE_BODY, strategy=strategy)


def estimate_cost(messages: list[dict[str, Any]], calls: int) -> tuple[int, float, float]:
	"""粗略估算：字符/2.6 ≈ token（中文工程混合文本的经验值），单价取 DeepSeek 档。"""
	chars = sum(len(str(m.get("content"))) for m in messages)
	tokens_in = int(chars / 2.6) + 400  # + 工具 schema 与固定开销的粗估
	tokens_out = 300
	# 单价（元/百万 token）：flash 命中与未命中两档，取区间
	low = tokens_in * calls / 1e6 * 0.02 + tokens_out * calls / 1e6 * 1.0
	high = tokens_in * calls / 1e6 * 1.0 + tokens_out * calls / 1e6 * 2.0
	return tokens_in, low, high


#: 判据 ②：把通报当"未经核实的转述"打折（不采信）。
DISTRUST_MARKERS = (
	"无法验证",
	"不应作为事实",
	"不作为事实依据",
	"无法确认",
	"未经核实",
	"我无法核实",
	"不能直接采信",
)


def judge(text: str) -> tuple[bool, str]:
	hits = [m for m in CONFUSION_MARKERS if m in text]
	return (bool(hits), "、".join(hits))


class _NullAbort:
	"""脚本夹具用的 abort 桩：stream() 只要 raise_if_aborted() 不抛。"""

	def raise_if_aborted(self) -> None:
		return None


async def _collect(client: Any, messages: list[dict[str, Any]]) -> str:
	parts: list[str] = []
	async for chunk in client.stream(messages, [], _NullAbort()):
		text = getattr(chunk, "text", "") or ""
		if text:
			parts.append(text)
	return "".join(parts)


def run_arm(strategy: str, calls: int) -> dict[str, Any]:
	import asyncio

	from common.errors import ProviderError
	from model.openai_compat import OpenAICompatClient

	messages = build_fixture(strategy)
	client = OpenAICompatClient(
		api_key=os.environ.get("DEEPSEEK_API_KEY", "").strip(),
		model="deepseek-v4-flash",
		provider="deepseek",
		base_url="https://api.deepseek.com",
		reasoning_effort="",
	)
	confused = 0
	distrust = 0
	err = 0
	samples: list[str] = []
	replies: list[str] = []
	for _ in range(calls):
		try:
			text = asyncio.run(_collect(client, messages))
			hit, markers = judge(text)
			confused += 1 if hit else 0
			distrust += 1 if any(m in text for m in DISTRUST_MARKERS) else 0
			if hit and len(samples) < 3:
				samples.append(markers)
			if len(replies) < 2:
				replies.append(" ".join(text.split())[:220])
		except (ProviderError, OSError, KeyError, RuntimeError) as exc:  # noqa: BLE001
			err += 1
			print(f"  调用失败：{type(exc).__name__}: {exc}", file=sys.stderr)
			break
	return {
		"strategy": strategy,
		"calls": calls,
		"confused": confused,
		"distrusted": distrust,
		"errors": err,
		"命中样例": samples,
		"回复样本": replies,
	}


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--calls", type=int, default=20)
	parser.add_argument("--run", action="store_true", help="真调用（默认只预检）")
	args = parser.parse_args(argv)

	total_low = 0.0
	total_high = 0.0
	for strategy in (STRATEGY_SYSTEM_CHANNEL, STRATEGY_NOTICE_FRAGMENT):
		messages = build_fixture(strategy)
		tokens_in, low, high = estimate_cost(messages, args.calls)
		total_low += low
		total_high += high
		print(f"[{strategy}]")
		print(f"  消息条数 {len(messages)}，尾部形态 {messages[-1].get('role')}")
		print(f"  单次输入估算 {tokens_in} token；{args.calls} 次估算费用 元 {low:.2f} ~ 元 {high:.2f}")
		print(f"  判据：回复命中 {CONFUSION_MARKERS} 任一 = 记一次「当成用户发言」")
		print()
	print(f"两档合计估算：元 {total_low:.2f} ~ 元 {total_high:.2f}（--calls {args.calls}）")
	if not args.run:
		print("预检模式，未发起任何调用。确认额度后加 --run。")
		return 0
	if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
		print("环境里没有 DEEPSEEK_API_KEY，不能跑真调用。", file=sys.stderr)
		return 2
	for strategy in (STRATEGY_SYSTEM_CHANNEL, STRATEGY_NOTICE_FRAGMENT):
		print(run_arm(strategy, args.calls))
	return 0


if __name__ == "__main__":
	sys.exit(main())
