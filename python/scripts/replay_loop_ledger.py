"""离线回放：今晚事故 transcript 验证 LoopLedger 信号 + fold 等价档。

用法（仓库 python/ 下）:
  py -3.11 scripts/replay_loop_ledger.py ~/.xeyo/sessions/sess_mtohmboz_83gbcc.jsonl

只读回放，不写任何状态；信号语义与 query_loop 接线一致：
  observe_assistant(assistant_text) 在 assistant 写盘前（text 块拼接）；
  observe_tool(tool_name, out_content) 在 tool_result 写盘前（fold 判定之前）。
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, ".")

from engine.aging import EXEMPT_TOOLS  # noqa: E402
from engine.loop_ledger import LoopLedger  # noqa: E402
from engine.repeat_fold import IdenticalResultFold  # noqa: E402


def main(path: str) -> None:
	ledger = LoopLedger(exempt_tools=frozenset(EXEMPT_TOOLS))
	fold = IdenticalResultFold()

	orig_bytes = 0
	folded_bytes = 0
	fold_hits: list[str] = []
	step = 0

	with open(path, encoding="utf-8") as fh:
		for raw in fh.read().splitlines():
			try:
				rec = json.loads(raw)
			except Exception:
				continue
			role = rec.get("role")
			if role == "assistant":
				# assistant_text = text 块拼接（与 query_loop 一致）
				texts = [
					b.get("text", "")
					for b in rec.get("content") or []
					if isinstance(b, dict) and b.get("type") == "text"
				]
				assistant_text = "\n".join(t for t in texts if t)
				step += 1
				ledger.observe_assistant(assistant_text)
				s = ledger.render()
				if s:
					print(f"[step {step}] assistant 后账本:\n{s}\n")
			elif role == "tool":
				for b in rec.get("content") or []:
					if not (isinstance(b, dict) and b.get("type") == "tool_result"):
						continue
					out = b.get("content") or ""
					name = rec.get("name") or "?"
					step += 1
					ledger.observe_tool(name, out)
					s = ledger.render()
					if s:
						print(f"[step {step}] {name} 结果后账本:\n{s}\n")
					# fold 等价档瘦身统计
					stored, folded = fold.process(name, {}, out)
					orig_bytes += len(out.encode("utf-8", "replace"))
					folded_bytes += len(stored.encode("utf-8", "replace"))
					if folded:
						fold_hits.append(f"step {step} {name}")

	print("=== 汇总 ===")
	print(f"s1={ledger.s1} s2={ledger.s2} s3={ledger.s3} tool_calls={ledger.tool_calls}")
	print(f"最终 render:\n{ledger.render() or '(未达阈值)'}")
	print(f"fold 折叠次数: {len(fold_hits)} → {fold_hits}")
	print(
		f"fold 字节: 原 {orig_bytes} → 折后 {folded_bytes} "
		f"(节省 {orig_bytes - folded_bytes} 字节, "
		f"{(orig_bytes - folded_bytes) * 100 // max(orig_bytes, 1)}%)"
	)


if __name__ == "__main__":
	main(sys.argv[1] if len(sys.argv) > 1 else "")
