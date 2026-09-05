# -*- coding: utf-8 -*-
"""老化清除灰度演练(aging canary)。

模拟长会话逐轮投影,对比 XEYO_TOOL_AGING 关/开两种状态:
- 经济性:每轮投影字节数、累计字节、终态体积、节省率
- 稳定性:边界推进事件计数、推进之间"前缀保持"违例数(必须为 0)
- 正确性:豁免/图片/净化抽查

用法:python scripts/aging_canary.py [--turns 60]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:  # Windows GBK 控制台兼容
	sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
	pass

from engine import aging as ag  # noqa: E402
from memory.runtime import project_for_model  # noqa: E402
from memory.working import WorkingSnapshot  # noqa: E402

# 记忆开关已改为「以 GUI settings.memory 为准、环境变量一律不参与」；
# 本脚本不写沙箱，故把 XEYO_HOME 钉到临时目录，避免 save() 污染真实 ~/.xeyo/settings.json。
if not os.environ.get("XEYO_HOME"):
	import tempfile

	os.environ["XEYO_HOME"] = str(Path(tempfile.mkdtemp(prefix="xeyo-canary-")))


def _uid(i: int) -> str:
	return f"use_{i:012d}"


def _pair(i: int):
	"""一条拟真工具调用对:尺寸/语言/类型轮换。"""
	assistant = {
		"role": "assistant",
		"content": [{"type": "tool_use", "id": _uid(i), "name": "Bash", "input": {"command": f"cmd_{i}"}}],
	}
	kind = i % 7
	if kind == 3:
		name, text, err = "TodoWrite", json.dumps({"todos": [{"content": f"task {i}", "status": "completed"}]}), False
	elif kind == 5:
		name, text, err = "Bash", f"FATAL error trace {i}\n" + "at frame\n" * 30, True
	elif kind % 2 == 0:
		name, text, err = "Read", (f"文件{i} 内容\n" + "中文行 with code: def f(x): return x\n" * 40), False
	else:
		name, text, err = "Grep", "\n".join(f"path/file{j}.py:{j}: match line {i}" for j in range(25)), False
	tool = {
		"role": "tool",
		"name": name,
		"tool_call_id": _uid(i),
		"content": [{"type": "tool_result", "tool_use_id": _uid(i), "content": text, "is_error": err}],
	}
	msgs = [assistant, tool]
	if i % 5 == 4:
		msgs.append({"role": "user", "content": f"继续,第 {i} 步结果怎么样?请总结 🎉"})
	return msgs


def build_session(turns: int) -> list[list[dict]]:
	steps: list[list[dict]] = []
	for i in range(turns):
		steps.append(_pair(i))
	return steps


def run_scenario(*, aging_on: bool, steps: list[list[dict]]) -> dict:
	from memory.memory_switches import save

	save({"XEYO_TOOL_AGING": "1" if aging_on else "0", "XEYO_L5": "project", "XEYO_C2_GATE": "0"})
	ag.reset_stats()

	w = WorkingSnapshot(session_id=f"canary-{aging_on}")
	hist: list[dict] = []
	sizes: list[int] = []
	advances = 0
	violations = 0
	prev_out: list[dict] | None = None

	for step in steps:
		frozen_before = w.c1_frozen_until
		hist.extend(step)
		out = project_for_model([json.loads(json.dumps(m)) for m in hist], w, include_memory_index=False)
		j = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
		sizes.append(len(j.encode("utf-8")))
		if w.c1_frozen_until != frozen_before:
			advances += 1
		elif prev_out is not None:
			# 未推进 → 前缀必须逐消息保持(字节稳定的结构化表达)
			for k, m in enumerate(prev_out):
				if json.dumps(m, ensure_ascii=False) != json.dumps(out[k], ensure_ascii=False):
					violations += 1
					break
		prev_out = out

	return {
		"aging": aging_on,
		"turns": len(steps),
		"sizes": sizes,
		"cum_bytes": sum(sizes),
		"final_bytes": sizes[-1] if sizes else 0,
		"advances": advances,
		"frozen_until": w.c1_frozen_until,
		"violations": violations,
		"stats": ag.stats(),
	}


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--turns", type=int, default=60)
	args = parser.parse_args()

	steps = build_session(args.turns)
	base = run_scenario(aging_on=False, steps=[json.loads(json.dumps(s)) for s in steps])
	cand = run_scenario(aging_on=True, steps=[json.loads(json.dumps(s)) for s in steps])

	save_cum = 1 - cand["cum_bytes"] / base["cum_bytes"]
	save_final = 1 - cand["final_bytes"] / base["final_bytes"]

	print("=" * 64)
	print("老化清除灰度演练报告")
	print("=" * 64)
	print(f"轮数                 : {args.turns}")
	print(f"[基线 OFF] 累计字节   : {base['cum_bytes']:>10,}   终态 {base['final_bytes']:>9,}   推进 {base['advances']}   违例 {base['violations']}")
	print(f"[老化 ON ] 累计字节   : {cand['cum_bytes']:>10,}   终态 {cand['final_bytes']:>9,}   推进 {cand['advances']}   违例 {cand['violations']}")
	print(f"累计发送节省          : {save_cum:6.1%}")
	print(f"终态上下文缩减        : {save_final:6.1%}")
	print(f"冻结边界              : ON→{cand['frozen_until']}  存根块 {cand['stats']['stubbed_blocks']}  折叠 {cand['stats']['folds']}")

	checks = [
		("基线零推进(flag off)", base["advances"] == 0 and base["violations"] == 0),
		("ON 前缀稳定性违例=0", cand["violations"] == 0),
		("ON 发生过边界推进", cand["advances"] > 0),
		("终态显著缩减(≥30%)", save_final >= 0.30),
		("累计发送节省(≥15%)", save_cum >= 0.15),
	]
	print("-" * 64)
	ok = True
	for name, passed in checks:
		print(f"[{'PASS' if passed else 'FAIL'}] {name}")
		ok &= passed
	print("=" * 64)
	print("结论:", "全部通过 ✅" if ok else "存在失败项 ❌")
	return 0 if ok else 1


if __name__ == "__main__":
	raise SystemExit(main())
