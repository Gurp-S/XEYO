"""输出精简三挡位（lite / full / ultra）token 节省基准。

对同一组任务分别以 关闭 / lite / full / ultra 调本地 XEYO server
（POST /v1/chat/completions，stream=false），从 xy_events 的 usage 事件读
prompt_tokens / completion_tokens，统计各挡位相对「关闭」的输出节省率，
以及注入块本身的 prompt 开销。输出样例落盘，便于人工核对压缩质量。

用法（在 python/ 目录，或把 python 加进 PYTHONPATH）::

    cd "D:\\lea\\XenYon code\\python"
    # 先起服务：py -3.11 -m server
    python scripts/bench_output_compact.py --api-key sk-xxx
    python scripts/bench_output_compact.py --api-key sk-xxx \
        --model deepseek-v4-flash --provider deepseek --repeats 2 --turns 3

API Key 也可用环境变量 DEEPSEEK_API_KEY / OPENAI_API_KEY（跟随 --provider）。
脚本只读账单、不改 engine；结果受模型随机性影响，repeats 越大越稳。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

MODES: list[tuple[str, bool, str | None]] = [
	("off", False, None),
	("lite", True, "lite"),
	("full", True, "full"),
	("ultra", True, "ultra"),
]

# 任务设计：都可直接文字回答（不需要工具），且天然会诱发长输出。
# 想换任务可 --tasks-file 传 JSON 字符串数组。
DEFAULT_TASKS: list[str] = [
	"解释 HTTP 401 和 403 状态码的区别、各自的典型成因与修复方法。直接文字回答，不要使用任何工具。",
	"这个 React 报错是什么原因、怎么修：TypeError: Cannot read properties of undefined (reading 'map')。给出排查清单。直接文字回答，不要使用任何工具。",
	"给出把一个 800 行的 React 单文件组件拆分成子组件与 hooks 的具体步骤清单和注意事项。直接文字回答，不要使用任何工具。",
	"介绍数据库 B+ 树索引的原理、与哈希索引的权衡、以及常见的索引失效场景。直接文字回答，不要使用任何工具。",
]
FOLLOWUP = "继续，就上一条回答未尽的部分再展开讲讲。"


def _post_chat(
	base_url: str,
	api_key: str,
	payload: dict[str, Any],
	timeout: float,
) -> dict[str, Any]:
	req = urllib.request.Request(
		base_url.rstrip("/") + "/v1/chat/completions",
		data=json.dumps(payload).encode("utf-8"),
		headers={
			"Content-Type": "application/json",
			"Authorization": f"Bearer {api_key}",
		},
		method="POST",
	)
	with urllib.request.urlopen(req, timeout=timeout) as res:
		return json.loads(res.read().decode("utf-8"))


def run_one(
	*,
	base_url: str,
	api_key: str,
	model: str,
	provider: str,
	thinking: str,
	task: str,
	session_id: str,
	output_compact: bool,
	output_mode: str | None,
	turns: int = 1,
) -> dict[str, Any]:
	"""单任务单会话跑 turns 轮；返回逐轮的 tokens 统计。"""
	messages: list[dict[str, str]] = [{"role": "user", "content": task}]
	turn_rows: list[dict[str, Any]] = []
	for i in range(turns):
		payload: dict[str, Any] = {
			"model": model,
			"stream": False,
			"session_id": session_id,
			"provider": provider,
			"thinking": thinking,
			"messages": messages,
			"output_compact": output_compact,
			"output_mode": output_mode,
		}
		resp = _post_chat(base_url, api_key, payload, timeout=600.0)
		usage = next(
			(
				ev
				for ev in reversed(resp.get("xy_events") or [])
				if isinstance(ev, dict) and ev.get("type") == "usage"
			),
			{},
		)
		if usage.get("completion_tokens") is None:
			raise RuntimeError(
				f"响应缺少 usage 事件（xy_events），无法统计；session={session_id}"
			)
		text = str(
			((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
		)
		turn_rows.append(
			{
				"turn": i + 1,
				"prompt_tokens": usage.get("prompt_tokens"),
				"completion_tokens": usage.get("completion_tokens"),
				"chars": len(text),
			}
		)
		if i + 1 < turns:
			messages.append({"role": "assistant", "content": text})
			messages.append({"role": "user", "content": FOLLOWUP})
	return {"session_id": session_id, "turns": turn_rows}


def summarize(results: dict[str, list[dict[str, Any]]], turns: int) -> None:
	base = results["off"]
	base_tok = [
		t["completion_tokens"]
		for r in base
		for t in r["turns"]
		if t["completion_tokens"]
	]
	base_avg = sum(base_tok) / len(base_tok) if base_tok else 0.0
	base_prompt = [
		t["prompt_tokens"] for r in base for t in r["turns"] if t["prompt_tokens"]
	]
	base_prompt_avg = sum(base_prompt) / len(base_prompt) if base_prompt else 0.0

	print()
	print(f"{'挡位':<8}{'轮均输出tok':>12}{'vs off':>10}{'轮均输入tok':>12}{'注入开销':>10}")
	print("-" * 56)
	for mode, _, _ in MODES:
		rows = results[mode]
		toks = [
			t["completion_tokens"] for r in rows for t in r["turns"] if t["completion_tokens"]
		]
		prompts = [
			t["prompt_tokens"] for r in rows for t in r["turns"] if t["prompt_tokens"]
		]
		avg = sum(toks) / len(toks) if toks else 0.0
		pavg = sum(prompts) / len(prompts) if prompts else 0.0
		saving = (base_avg - avg) / base_avg * 100 if base_avg else 0.0
		overhead = pavg - base_prompt_avg
		print(f"{mode:<8}{avg:>12.0f}{saving:>9.1f}%{pavg:>12.0f}{overhead:>+10.0f}")

	# 长会话约束：多轮时检查第 2 轮相对第 1 轮是否递增（目标 ≤ 1.0）
	if turns >= 2:
		print()
		print("长会话约束（第2轮 / 第1轮 输出比，目标 ≤ 1.0）：")
		for mode in ("off", "full", "ultra"):
			ratios = [
				r["turns"][1]["completion_tokens"] / r["turns"][0]["completion_tokens"]
				for r in results[mode]
				if len(r["turns"]) >= 2 and r["turns"][0]["completion_tokens"]
			]
			if ratios:
				print(f"  {mode:<8} 平均 {sum(ratios) / len(ratios):.2f}")


def main() -> None:
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("--base-url", default="http://127.0.0.1:8000")
	ap.add_argument("--api-key", default="")
	ap.add_argument("--provider", default="deepseek", choices=["deepseek", "openai"])
	ap.add_argument("--model", default="deepseek-v4-flash")
	ap.add_argument("--thinking", default="disabled", choices=["disabled", "enabled"])
	ap.add_argument("--repeats", type=int, default=2, help="每任务重复次数（默认 2）")
	ap.add_argument("--turns", type=int, default=1, help="每会话追问轮数 1-3（默认 1）")
	ap.add_argument("--tasks-file", default="", help="JSON 字符串数组文件；缺省用内置任务")
	ap.add_argument("--out", default="", help="结果 JSON 落盘路径（含各轮原文路径）")
	args = ap.parse_args()

	api_key = args.api_key or os.environ.get(
		"DEEPSEEK_API_KEY" if args.provider == "deepseek" else "OPENAI_API_KEY",
		"",
	).strip()
	if not api_key:
		sys.exit("缺少 API Key：--api-key 或环境变量 DEEPSEEK_API_KEY / OPENAI_API_KEY")

	tasks: list[str] = DEFAULT_TASKS
	if args.tasks_file:
		tasks = json.loads(Path(args.tasks_file).read_text(encoding="utf-8"))
	turns = max(1, min(3, args.turns))

	results: dict[str, list[dict[str, Any]]] = {}
	samples: dict[str, Any] = {}
	for mode, compact, omode in MODES:
		results[mode] = []
		samples[mode] = []
		for ti, task in enumerate(tasks):
			for rep in range(args.repeats):
				sid = f"ocbench-{mode}-t{ti}-r{rep}-{int(time.time())}"
				print(f"[{mode}] 任务{ti + 1}/{len(tasks)} 重复{rep + 1}/{args.repeats} …")
				try:
					r = run_one(
						base_url=args.base_url,
						api_key=api_key,
						model=args.model,
						provider=args.provider,
						thinking=args.thinking,
						task=task,
						session_id=sid,
						output_compact=compact,
						output_mode=omode,
						turns=turns,
					)
				except Exception as exc:  # noqa: BLE001 —— 基准脚本容忍单点失败
					print(f"    失败：{exc}")
					continue
				r["task"] = task
				results[mode].append(r)
				samples[mode].append(r)

	if not any(results["off"]):
		sys.exit("「关闭」挡位全部请求失败，无法计算节省率；请检查服务与 Key。")
	summarize(results, turns)

	if args.out:
		Path(args.out).write_text(
			json.dumps(
				{"args": vars(args), "results": results},
				ensure_ascii=False,
				indent=2,
			),
			encoding="utf-8",
		)
		print(f"\n明细已写入 {args.out}")


if __name__ == "__main__":
	main()
