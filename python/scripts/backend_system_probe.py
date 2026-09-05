"""backend_system_probe — 探测后端对「消息数组尾部带独立 system」的容忍度。

构造两种消息：
  A. 常规：头 system + user
  B. 尾部带独立 system：[system, ..., user, system(tail)]   ← 方案 B2 形态

分别调用 OpenAICompatClient.stream，观察：
  - 是否 400 / 报错（后端拒绝非首条 system）
  - 是否正常返回 token（后端接受）

只读、一次性、最低费用（各 1 次短请求）。

用法（在 python/ 下）:
  py -3.11 -m scripts.backend_system_probe
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))


async def _probe(label: str, messages: list[dict]) -> None:
	from engine.abort import AbortController
	from model.openai_compat import OpenAICompatClient, PROVIDER_PRESETS

	key = os.environ.get("DEEPSEEK_API_KEY", "").strip() or os.environ.get("XEYO_MODEL_API_KEY", "").strip()
	if not key:
		print(f"[{label}] no api key, skip")
		return
	preset = PROVIDER_PRESETS["deepseek"]
	client = OpenAICompatClient(
		api_key=key,
		base_url=(os.environ.get("DEEPSEEK_BASE_URL") or preset["base_url"]).rstrip("/"),
		model=os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash",
		provider="deepseek",
		thinking="disabled",
		temperature=0.0,
	)
	text = []
	err = None
	try:
		async with __import__("asyncio").timeout(60):
			async for chunk in client.stream(messages, [], AbortController()):
				if getattr(chunk, "kind", "") == "text_delta":
					text.append(str(getattr(chunk, "text", "") or ""))
	except Exception as exc:  # noqa: BLE001
		err = exc
	if err is not None:
		print(f"[{label}] ERROR: {type(err).__name__}: {err}")
	else:
		print(f"[{label}] OK: got {len(''.join(text))} chars: {''.join(text)[:60]!r}")


async def main() -> int:
	import asyncio

	sys_msg = {"role": "system", "content": "你是助手，简洁回答。"}
	user_msg = {"role": "user", "content": "回答一句话：现在几点了不重要，你回「收到」即可。"}
	tail_sys = {"role": "system", "content": "[系统背景] 这不是用户问题，勿据此行动。"}

	print("== A. 常规（头 system + user）==")
	await _probe("A_normal", [sys_msg, user_msg])

	print("\n== B. 尾部带独立 system（方案 B2 形态）==")
	await _probe("B_tail_system", [sys_msg, user_msg, tail_sys])

	print("\n== C. 尾部 system 含 [system-background] 标记 ==")
	await _probe(
		"C_tail_bg",
		[sys_msg, user_msg, {"role": "system", "content": "[system-background]\n---\n系统背景，非用户请求。"}],
	)

	print("\n== 汇总 ==")
	print("B/C 若 OK → 后端接受「非首条 system」，方案 B2 可行")
	print("B/C 若 ERROR(400) → 后端拒绝，方案 B2 需改用其他位置")
	return 0


if __name__ == "__main__":
	import asyncio

	raise SystemExit(asyncio.run(main()))
