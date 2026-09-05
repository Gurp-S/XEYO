"""环境声道到达性探针：证明方案A伪造对真实进入发往模型的请求。

用法（在 python/ 目录下）:
  py scripts/probe_env_channel.py                       # dump 模式（离线）
  py scripts/probe_env_channel.py --live                # 追加真实 provider 试叫
  py scripts/probe_env_channel.py --live --api-key sk-xxx \
      --model deepseek-chat --base-url https://api.deepseek.com/v1

key 来源优先级：--api-key > 环境变量 XEYO_API_KEY / DEEPSEEK_API_KEY >
~/.xeyo/config.toml。GUI 的 key 存在 WebView localStorage（按请求传参），
脚本读不到——live 失败时按提示带 key 重跑即可。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model._openai_common import normalize_messages_for_openai
from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject
from prompt.t_now_strategy import (
	ENV_TOOL_NAME,
	STRATEGY_ENV_CHANNEL,
	set_t_now_strategy,
)


def _build_projected() -> tuple[list[dict], list[dict]]:
	"""复刻 production 注入路径：fresh-user 轮 + after_tools 轮各投影一次。"""
	set_t_now_strategy(STRATEGY_ENV_CHANNEL)
	fresh = run_pre_llm_inject(
		[{"role": "user", "content": "帮我确认注入到达性（真实请求预览）"}],
		InjectContext(cwd="", forced_wrap_up=True),
	)
	after_tools = run_pre_llm_inject(
		[
			{"role": "user", "content": "task"},
			{
				"role": "assistant",
				"content": [{"type": "tool_use", "id": "r1", "name": "Read"}],
			},
			{
				"role": "tool",
				"tool_call_id": "r1",
				"content": [
					{
						"type": "tool_result",
						"tool_use_id": "r1",
						"content": "ok",
						"is_error": False,
					}
				],
			},
		],
		InjectContext(cwd="", forced_wrap_up=True),
	)
	return fresh, after_tools


def dump_mode() -> bool:
	fresh, after_tools = _build_projected()
	ok = True
	for label, msgs in (("fresh-user", fresh), ("after_tools", after_tools)):
		use = msgs[-2].get("content", [{}])[0]
		res = msgs[-1].get("content", [{}])[0]
		pair_ok = (
			msgs[-2].get("role") == "assistant"
			and msgs[-1].get("role") == "user"
			and use.get("name") == ENV_TOOL_NAME
			and res.get("type") == "tool_result"
			and res.get("tool_use_id") == use.get("id")
		)
		norm = normalize_messages_for_openai(msgs)
		norm_tail = norm[-2:]
		norm_ok = (
			norm_tail[0].get("role") == "assistant"
			and norm_tail[0].get("tool_calls")
			and norm_tail[1].get("role") == "tool"
			and norm_tail[1].get("tool_call_id")
			== norm_tail[0]["tool_calls"][0]["id"]
		)
		ok = ok and pair_ok and norm_ok
		print(f"[{label}] 伪对结构: {'✅' if pair_ok else '❌'}"
		      f"  normalize→良构tool对: {'✅' if norm_ok else '❌'}")
		print(f"  实际将发送的请求尾部（OpenAI wire 格式，最后 2 条）:")
		print(json.dumps(norm_tail, ensure_ascii=False, indent=2)[:1200])
		print()
	print(f"== 请求侧结论：{'伪对确实在发往模型的 api_messages 里' if ok else '存在结构问题，勿上线'}")
	return ok


def _load_key(args: argparse.Namespace) -> tuple[str, str, str]:
	import os

	if args.api_key:
		return args.api_key, args.base_url, args.model
	for var in ("XEYO_API_KEY", "DEEPSEEK_API_KEY"):
		v = os.environ.get(var, "").strip()
		if v:
			return v, args.base_url, args.model
	cfg = Path.home() / ".xeyo" / "config.toml"
	if cfg.exists():
		import tomllib

		data = tomllib.loads(cfg.read_text(encoding="utf-8"))
		key = str(data.get("api_key") or "").strip()
		if key and not key.upper().startswith("YOUR_"):
			return (
				key,
				args.base_url or str(data.get("base_url") or ""),
				args.model or str(data.get("model") or ""),
			)
	return "", "", ""


async def live_mode(args: argparse.Namespace) -> bool:
	api_key, base_url, model = _load_key(args)
	if not api_key:
		print("== live 结论：❌ 未找到可用 key（GUI 的 key 在 WebView localStorage，"
		      "脚本读不到）。带 --api-key 重跑，或在 GUI 发一条消息后查看后端日志。")
		return False
	from engine.abort import AbortController
	from model.openai_compat import OpenAICompatClient

	fresh, _ = _build_projected()
	client = OpenAICompatClient(
		api_key=api_key,
		base_url=base_url or "https://api.deepseek.com/v1",
		model=model or "deepseek-chat",
		provider="openai",
		thinking="disabled",
		session_id="probe_env_channel",
	)
	parts: list[str] = []
	err: Exception | None = None
	try:
		async for chunk in client.stream(
			fresh, [], AbortController()
		):
			if chunk.kind == "text_delta":
				parts.append(chunk.text)
	except Exception as exc:  # noqa: BLE001
		err = exc
	if err is not None:
		print(f"== live 结论：❌ {type(err).__name__}: {err}")
		print("   （402=欠费、401=key 无效、400=该后端拒绝伪对——最后一种才需要回退）")
		return False
	text = "".join(parts).strip()
	print(f"== live 结论：✅ 后端接受了伪对请求并返回 {len(text)} 字符")
	print(f"   回复预览: {text[:120]!r}")
	return True


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--live", action="store_true")
	parser.add_argument("--api-key", default="")
	parser.add_argument("--base-url", default="")
	parser.add_argument("--model", default="")
	args = parser.parse_args()
	request_ok = dump_mode()
	if args.live:
		print()
		live_ok = asyncio.run(live_mode(args))
		sys.exit(0 if request_ok and live_ok else 1)
	sys.exit(0 if request_ok else 1)


if __name__ == "__main__":
	main()
