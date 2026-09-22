"""阶段 3a：三档注入载体的**承载开销**对照（零厂商调用）。

## 口径（先定后跑）

**测得到什么**：同一份通报正文分别用三种形态承载，各自额外付出多少条消息、
多少字节、以及投影里是否出现"可被模仿的工具形状"。这是三档之间唯一可以
离线 apples-to-apples 比较的东西。

**测不到什么（重要，别当成 0）**：
- *生产发生率*——通报块依赖运行时状态（cwd、WorkingSnapshot、待处理事件、
  浏览器预览 URL），从 transcript 复原不出来。实测把 398 条真实会话的轮边界
  喂给装配口，三档全部产出"无注入"，因此发生率只能靠阶段 2 新加的
  ``notice.channel`` 审计事件往后收数。
- *模型是否把注入当用户发言*——必须真调用（阶段 3b）。

正文取自仓库既有的真实金标 ``evals/changedetect/goldens/trace/inject__channel_env.txt``
里的 env 通报段，不用编造文本。

用法（在 ``python/`` 下）::

    py -3.11 -m scripts.ab_notice_channel
    py -3.11 -m scripts.ab_notice_channel --incidence   # 附带跑覆盖率普查（只报覆盖，不报收益）
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prompt.notice_channel import NOTICE_ENVELOPE_OPEN, render_notice  # noqa: E402
from prompt.t_now_strategy import (  # noqa: E402
	STRATEGY_ENV_CHANNEL,
	STRATEGY_NOTICE_FRAGMENT,
	STRATEGY_SKIP,
	STRATEGY_SYSTEM_CHANNEL,
)

ARMS = (STRATEGY_SYSTEM_CHANNEL, STRATEGY_NOTICE_FRAGMENT, STRATEGY_ENV_CHANNEL, STRATEGY_SKIP)
_PY_ROOT = Path(__file__).resolve().parents[1]
_GOLDEN_TRACE = _PY_ROOT / "evals" / "changedetect" / "goldens" / "trace" / "inject__channel_env.txt"


def _row_text(content: Any) -> str:
	if isinstance(content, str):
		return content
	if not isinstance(content, list):
		return ""
	return "\n".join(
		str(b.get("text") or "")
		for b in content
		if isinstance(b, dict) and b.get("type") == "text"
	)


def real_notice_bodies() -> list[str]:
	"""从金标 trace 里取真实 env 通报正文；取不到就按长度阶梯造等价占位。

	占位只用于量"承载开销随正文长度的曲线"，不参与任何收益宣称，故不伪装成真实文本。
	"""
	if _GOLDEN_TRACE.exists():
		try:
			raw = json.loads(_GOLDEN_TRACE.read_text(encoding="utf-8"))
		except (json.JSONDecodeError, OSError):
			raw = None
		if isinstance(raw, list):
			bodies: list[str] = []
			for item in raw:
				content = item.get("content") if isinstance(item, dict) else None
				for block in content if isinstance(content, list) else []:
					if isinstance(block, dict) and block.get("type") == "tool_result":
						inner = block.get("content")
						if isinstance(inner, str) and "[system-environment]" in inner:
							bodies.append(inner)
			if bodies:
				return bodies
	# 兜底：长度阶梯（明确标注为占位）
	return [
		"# 状态（占位，非真实正文）\n" + ("x" * n)
		for n in (200, 800, 2000, 6000)
	]


def _extra_messages(messages: list[dict[str, Any]], baseline_len: int) -> int:
	return len(messages) - baseline_len


def _has_tool_shape(messages: list[dict[str, Any]]) -> bool:
	for m in messages:
		content = m.get("content")
		if isinstance(content, list) and any(
			isinstance(b, dict) and b.get("type") == "tool_use" for b in content
		):
			return True
	return False


def _carrier_label(messages: list[dict[str, Any]]) -> str:
	if not messages:
		return "空投影"
	last = messages[-1]
	content = last.get("content")
	if isinstance(content, list) and any(
		isinstance(b, dict) and b.get("type") == "tool_use" for b in content
	):
		return "伪对 assistant(tool_use)"
	if last.get("role") == "system":
		return "原生 system"
	if last.get("role") == "user" and isinstance(content, str) and content.lstrip().startswith(NOTICE_ENVELOPE_OPEN):
		return "user 包封片段"
	return "无注入"


def measure_carrier(bodies: list[str]) -> dict[str, Any]:
	"""同一份正文 × 三种形态：量额外条数、额外字节、形态、可调用形状。"""
	out: dict[str, Any] = {"per_arm": {}, "body_sizes": [len(b) for b in bodies]}
	for arm in ARMS:
		extra_msgs: list[int] = []
		extra_bytes: list[int] = []
		carriers: dict[str, int] = {}
		tool_shape = 0
		for body in bodies:
			base = [{"role": "user", "content": "把登录页改掉"}]
			shaped = render_notice(base, body, strategy=arm)
			carrier = _carrier_label(shaped)
			carriers[carrier] = carriers.get(carrier, 0) + 1
			if _has_tool_shape(shaped):
				tool_shape += 1
			extra_msgs.append(_extra_messages(shaped, len(base)))
			extra_bytes.append(
				sum(len(json.dumps(m, ensure_ascii=False)) for m in shaped)
				- sum(len(json.dumps(m, ensure_ascii=False)) for m in base)
			)
		out["per_arm"][arm] = {
			"carriers": carriers,
			"turns_with_tool_shape": tool_shape,
			"extra_msgs_mean": round(statistics.fmean(extra_msgs), 2) if extra_msgs else 0,
			"extra_bytes_mean": round(statistics.fmean(extra_bytes), 1) if extra_bytes else 0,
			"overhead_pct_of_body": (
				round(100.0 * statistics.fmean(extra_bytes) / statistics.fmean([len(b) for b in bodies]), 2)
				if bodies
				else 0
			),
		}
	return out


def measure_incidence_coverage(limit: int, turns: int) -> dict[str, Any]:
	"""普查：真实会话轮边界能不能喂出通报块（测的是覆盖率，不是收益）。"""
	from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject

	root = Path.home() / ".xeyo" / "sessions"
	paths = [p for p in sorted(root.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True) if not p.name.startswith("_")][:limit]
	sessions_used = 0
	boundaries: list[list[dict[str, str]]] = []
	for path in paths:
		try:
			rows = [json.loads(l) for l in path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
		except (json.JSONDecodeError, OSError):
			continue
		history: list[dict[str, str]] = []
		made = 0
		for row in rows:
			role = str(row.get("role") or "")
			text = _row_text(row.get("content")).strip()
			if not text:
				continue
			if role == "user" and history:
				boundaries.append([dict(m) for m in history])
				made += 1
				if made >= turns:
					break
			if role in ("user", "assistant", "system"):
				history.append({"role": role, "content": text})
		if made:
			sessions_used += 1

	produced = 0
	errors = 0
	for hist in boundaries:
		try:
			out = run_pre_llm_inject(
				[dict(m) for m in hist],
				InjectContext(working=None, include_memory_index=True, strategy=STRATEGY_SYSTEM_CHANNEL),
			)
			if _carrier_label(out) != "无注入":
				produced += 1
		except Exception:  # noqa: BLE001
			errors += 1
	return {
		"sessions_scanned": len(paths),
		"sessions_with_boundaries": sessions_used,
		"boundaries": len(boundaries),
		"boundaries_producing_notice": produced,
		"assemble_errors": errors,
	}


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--incidence", action="store_true", help="附带跑离线覆盖率普查")
	parser.add_argument("--sessions", type=int, default=40)
	parser.add_argument("--turns", type=int, default=12)
	parser.add_argument("--json", dest="json_out", default="")
	args = parser.parse_args(argv)

	bodies = real_notice_bodies()
	print(f"正文样本：{len(bodies)} 份，长度 {[len(b) for b in bodies]}")
	src = "金标 trace（真实 env 通报正文）" if "system-environment" in bodies[0] else "占位阶梯（金标不可用）"
	print(f"正文来源：{src}\n")

	result = measure_carrier(bodies)
	for arm, m in result["per_arm"].items():
		print(f"[{arm}]")
		print(f"  承载形态：{m['carriers']}")
		print(f"  投影里出现可模仿的工具形状：{m['turns_with_tool_shape']}/{len(bodies)} 份")
		print(f"  额外消息条数：均值 {m['extra_msgs_mean']}")
		print(
			f"  额外字节：均值 {m['extra_bytes_mean']}"
			f"（占正文 {m['overhead_pct_of_body']}%）"
		)
		print()
	print("注：以上只比承载开销。生产发生率需靠 notice.channel 审计往后收；")
	print("    「是否被当成用户发言」必须真调用（阶段 3b）。")

	if args.incidence:
		cov = measure_incidence_coverage(args.sessions, args.turns)
		print("\n[离线覆盖率普查]")
		for k, v in cov.items():
			print(f"  {k}: {v}")
		result["incidence"] = cov
	if args.json_out:
		Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
		print(f"\n写出 {args.json_out}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
