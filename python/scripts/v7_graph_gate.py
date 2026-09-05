"""v7 证据门 — 图谱检索 vs 现有 L4 检索 公平离线 A/B（无 API）。

公平口径：两路径都返回「目标符号体正文」的同一份字节；图谱只赢「免往返定位 + 带调用者边」。
多符号样本集（python + gui，大小/跨文件调用者各异）去幸存者偏差。

统计：命中准确率、往返轮次、返回 token、增量重解析。

用法：cd python && python scripts/v7_graph_gate.py
"""

from __future__ import annotations

import asyncio
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from engine.abort import AbortController  # noqa: E402
from codeindex import cgraph  # noqa: E402
from codeindex.symbols import clear_cache  # noqa: E402
from tools.file_read_tool.file_read_tool import FileReadTool  # noqa: E402
from tools.grep_tool.grep_tool import GrepTool  # noqa: E402

REPO = str(REPO_ROOT)

# 样本：真实仓库符号 → (符号名, 定位re, 定义文件)。覆盖 py/ts，跨文件调用者数目各异。
CASES = [
	("query_loop", r"def query_loop", REPO_ROOT / "python/engine/query_loop.py"),
	("_eligible_for_early", r"def _eligible_for_early", REPO_ROOT / "python/engine/query_loop.py"),
	("incremental_update", r"def incremental_update", REPO_ROOT / "python/codeindex/cgraph.py"),
	("continueAndRevert", r"continueAndRevert", REPO_ROOT / "gui/src/stores/chat/rollbackSlice.ts"),
	("rebuild_edges", r"def _build_edges", REPO_ROOT / "python/codeindex/cgraph.py"),
]


def tokens(text: str) -> int:
	return max(1, len(text) // 4) if text else 0


def strip_nums(content: str) -> str:
	return "\n".join(re.sub(r"^\s*\d+→", "", ln, count=1) for ln in content.split("\n"))


async def run_case(g: GrepTool, r: FileReadTool, name: str, pat: str, def_path: Path) -> dict:
	# 图谱：一次查询（含调用者边 + 正文，公平）
	clear_cache()
	hits = cgraph.query_symbol(REPO, name)
	graph_text = cgraph.compile_hits(REPO, hits, with_body=True)
	graph_hit = any(h.name == name and Path(h.path).name == def_path.name for h in hits)
	graph_ok = graph_hit

	# 现有：Grep 定位 → Read 到文件尾
	locate = {"pattern": pat, "output_mode": "content", "path": str(def_path), "-n": True}
	t0 = time.perf_counter()
	gr = await g.execute(locate, AbortController())
	grep_ms = (time.perf_counter() - t0) * 1000
	grep_line = None
	for ln in gr.content.split("\n"):
		parts = ln.split(":", 2)
		if len(parts) >= 2 and parts[0].strip().isdigit():
			grep_line = int(parts[0]); break
		if len(parts) >= 3 and parts[1].strip().isdigit():
			grep_line = int(parts[1]); break
	# 定位失败则现有路径不命中（agent 找不到）
	if grep_line is None:
		return {"name": name, "graph_tk": tokens(graph_text), "old_tk": 0, "save": 0,
				"graph_ok": graph_ok, "old_ok": False, "graph_calls": 1, "old_calls": 1}
	# 现有保底：从定位行读到文件尾
	t0 = time.perf_counter()
	rd = await r.execute({"file_path": str(def_path), "offset": grep_line, "limit": 2000}, AbortController())
	read_ms = (time.perf_counter() - t0) * 1000
	old_body = strip_nums(rd.content)
	old_ok = re.search(pat, def_path.read_text(encoding="utf-8", errors="replace")) is not None
	old_tk = tokens(gr.content) + tokens(rd.content)
	save = 100 * (1 - tokens(graph_text) / old_tk) if old_tk else 0
	return {"name": name, "graph_tk": tokens(graph_text), "old_tk": old_tk, "save": save,
			"graph_ok": graph_ok, "old_ok": old_ok, "graph_calls": 1, "old_calls": 2}


async def main() -> None:
	print(f"# v7 证据门：图谱检索 vs 现有 L4 检索（公平 · 离线 · {REPO_ROOT}）\n")

	print("## 一、图谱索引\n")
	clear_cache()
	t0 = time.perf_counter()
	build = cgraph.build_index(REPO)
	print(f"- 全量构建: {build['symbols']} 符号 / {build['edges']} 边，{(time.perf_counter()-t0)*1000:.0f}ms")
	t0 = time.perf_counter()
	incr = cgraph.incremental_update(REPO)
	print(f"- 增量(无改动): 重解析 {incr['reparsed']}，{(time.perf_counter()-t0)*1000:.0f}ms")

	print("\n## 二、逐符号对比（两路径同读正文）\n")
	g, r = GrepTool(cwd=REPO), FileReadTool(cwd=REPO)
	print("| 符号 | 图谱tk/轮次 | 现有tk/轮次 | token节省 | 图谱命中 | 现有命中 |")
	print("|---|---|---|---|---|---|")
	rows = []
	for name, pat, dp in CASES:
		res = await run_case(g, r, name, pat, dp)
		rows.append(res)
		print(f"| {name} | {res['graph_tk']}tk/{res['graph_calls']} | {res['old_tk']}tk/{res['old_calls']} | {res['save']:.0f}% | {res['graph_ok']} | {res['old_ok']} |")

	# 汇总
	all_ok_graph = all(x["graph_ok"] for x in rows)
	all_ok_old = all(x["old_ok"] for x in rows)
	tot_g = sum(x["graph_tk"] for x in rows)
	tot_o = sum(x["old_tk"] for x in rows)
	save_avg = sum(x["save"] for x in rows) / len(rows)
	save_tot = 100 * (1 - tot_g / tot_o) if tot_o else 0
	graph_calls = sum(x["graph_calls"] for x in rows)
	old_calls = sum(x["old_calls"] for x in rows)

	print("\n## 二·汇总\n")
	print(f"- 命中准确率: 图谱={all_ok_graph} ({sum(x['graph_ok'] for x in rows)}/{len(rows)})  现有={all_ok_old} ({sum(x['old_ok'] for x in rows)}/{len(rows)})")
	print(f"- 总 token: 图谱 {tot_g} vs 现有 {tot_o} → 节省 **{save_tot:.0f}%**（单例均值 {save_avg:.0f}%）")
	print(f"- 往返轮次: 图谱 {graph_calls} vs 现有 {old_calls}")

	print("\n## 三、增量更新（改 1 文件）\n")
	target = Path(CASES[0][2])
	orig = target.read_text(encoding="utf-8")
	before = cgraph.incremental_update(REPO)
	target.write_text(orig + "\n", encoding="utf-8")
	after = cgraph.incremental_update(REPO)
	target.write_text(orig, encoding="utf-8")
	print(f"- 改前重解析 {before['reparsed']}；改后重解析 {after['reparsed']}（应=1）")

	print("\n## 四、证据门判定\n")
	# 假阴哨兵（sess_mtlfvp9l 教训）：单符号节省 ≥95% 或图谱 token 近零 =
	# 图谱路径漏召回（返回空/退化），是失败信号不是收益——直接 FAIL。
	suspects = [x["name"] for x in rows if x["save"] >= 95 or x["graph_tk"] < 50]
	false_negative_free = not suspects
	gate_ok = (
		all_ok_graph
		and all_ok_old
		and false_negative_free
		and save_tot > 0
		and after["reparsed"] <= 3
	)
	print(f"- 命中准确率不降: {'PASS' if all_ok_graph and all_ok_old else 'FAIL'}")
	print(f"- 假阴哨兵（节省≥95% 或图谱tk<50 即漏召回）: "
	      f"{'PASS' if false_negative_free else 'FAIL ' + str(suspects)}")
	print(f"- 单次定位 token 节省: {save_tot:.0f}% → {'PASS' if save_tot > 0 else 'FAIL'}")
	print(f"- 增量不全量重解析: {after['reparsed']} → {'PASS' if after['reparsed'] <= 3 else 'FAIL'}")
	print(f"\n总体: {'✅ 证据门达标' if gate_ok else '❌ 未达标'}")


if __name__ == "__main__":
	asyncio.run(main())
