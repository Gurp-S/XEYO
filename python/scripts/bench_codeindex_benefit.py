"""33号计划收益评测（离线，无任何 API 调用）。

直接驱动真实工具（FileReadTool / GrepTool），在真实仓库文件上对比：
- 旧路径（没有符号功能）：Grep 定位行号 → Read offset/limit 整段读（agent 实际做法，
  两种策略：保底=读到文件尾不截断；激进=只读150行，token省但可能截断）
- 新路径（本计划）：Read symbol / Grep output_mode=symbols

每个场景统计：工具调用轮次、返回 token（chars//4，与引擎口径一致）、耗时、
内容准确率（与 codeindex ground-truth 比对）。另附边界覆盖清单。

用法：cd python && python scripts/bench_codeindex_benefit.py
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
from codeindex.symbols import clear_cache, iter_symbols, outline  # noqa: E402
from tools.file_read_tool.file_read_tool import FileReadTool  # noqa: E402
from tools.grep_tool.grep_tool import GrepTool  # noqa: E402

REPO = str(REPO_ROOT)
PY_TARGET = str(REPO_ROOT / "python" / "engine" / "query_loop.py")            # 1098 行
TS_TARGET = str(REPO_ROOT / "gui" / "src" / "stores" / "chat" / "rollbackSlice.ts")  # 953 行
PY_SYMBOL = "_eligible_for_early"    # 72-93 行（22 行小函数，文件尾余量 1005 行）
TS_SYMBOL = "continueAndRevert"      # 205-216 行（12 行小方法，文件尾余量 737 行）
STORES_DIR = str(REPO_ROOT / "gui" / "src" / "stores")


def tokens(text: str) -> int:
	"""引擎同款粗估：chars // 4。"""
	return max(1, len(text) // 4) if text else 0


_LINE_NO_RE = re.compile(r"^\s*\d+→")
_SYM_LINE_RE = re.compile(r":\d+:\s")


def strip_line_numbers(content: str) -> str:
	"""去掉 Read 输出的 cat -n 行号前缀（N→content），便于与源码精确比对。"""
	return "\n".join(_LINE_NO_RE.sub("", ln, count=1) for ln in content.split("\n"))


class Recorder:
	"""模拟一次 agent 工作流：记录每步工具调用的轮次/token/耗时/输出。"""

	def __init__(self) -> None:
		self.calls: list[dict] = []

	async def grep(self, tool: GrepTool, params: dict) -> str:
		t0 = time.perf_counter()
		r = await tool.execute(params, AbortController())
		ms = (time.perf_counter() - t0) * 1000
		self.calls.append({"tool": "Grep", "ms": ms, "tokens": tokens(r.content), "error": r.is_error})
		return r.content

	async def read(self, tool: FileReadTool, params: dict) -> str:
		t0 = time.perf_counter()
		r = await tool.execute(params, AbortController())
		ms = (time.perf_counter() - t0) * 1000
		self.calls.append({"tool": "Read", "ms": ms, "tokens": tokens(r.content), "error": r.is_error})
		return r.content

	@property
	def n_calls(self) -> int:
		return len(self.calls)

	@property
	def total_tokens(self) -> int:
		return sum(c["tokens"] for c in self.calls)

	@property
	def total_ms(self) -> float:
		return sum(c["ms"] for c in self.calls)


def parse_grep_line(content: str) -> int:
	"""旧路径第一步：从 grep content 输出里取第一个行号。

	目标为目录时输出形如 path:392:content；为单文件时是 392:content。
	"""
	for line in content.split("\n"):
		parts = line.split(":", 2)
		if len(parts) >= 2 and parts[0].strip().isdigit():
			return int(parts[0])
		if len(parts) >= 3 and parts[1].strip().isdigit():
			return int(parts[1])
	raise ValueError(f"cannot parse line number from: {content[:120]!r}")


async def scenario_read_symbol(target: str, symbol: str, label: str, locate_pattern: str) -> dict:
	# ground truth：codeindex 的符号范围即精确答案
	gt = next(s for s in outline(target) if s.name == symbol)
	src_lines = Path(target).read_text(encoding="utf-8", errors="replace").split("\n")
	truth = "\n".join(src_lines[gt.start - 1 : gt.end])

	rec_old_safe = Recorder()  # 保底：读到文件尾
	rec_old_fast = Recorder()  # 激进：只读150行
	rec_new = Recorder()
	g, r = GrepTool(cwd=REPO), FileReadTool(cwd=REPO)

	locate = {"pattern": locate_pattern, "output_mode": "content", "path": target, "-n": True}

	# 旧路径·保底：grep 定位 → 读到文件尾
	line = parse_grep_line(await rec_old_safe.grep(g, locate))
	old_safe_body = strip_line_numbers(await rec_old_safe.read(r, {"file_path": target, "offset": line, "limit": 2000}))

	# 旧路径·激进：grep 定位 → 只读150行（agent 不知道函数在哪结束的典型猜测）
	line = parse_grep_line(await rec_old_fast.grep(g, locate))
	old_fast_body = strip_line_numbers(await rec_old_fast.read(r, {"file_path": target, "offset": line, "limit": 150}))

	# 新路径：一步直达
	new_body = strip_line_numbers(await rec_new.read(r, {"file_path": target, "symbol": symbol}))

	return {
		"label": label,
		"truth_lines": gt.end - gt.start + 1,
		"old_safe": rec_old_safe, "old_fast": rec_old_fast, "new": rec_new,
		"old_safe_exact": old_safe_body.strip() == truth.strip(),
		"old_fast_exact": old_fast_body.strip() == truth.strip(),
		"new_exact": new_body.strip() == truth.strip(),
	}


async def scenario_browse_symbols() -> dict:
	gt = list(iter_symbols(STORES_DIR, r".", max_symbols=5000))

	rec_old, rec_new, rec_fold = Recorder(), Recorder(), Recorder()
	g = GrepTool(cwd=REPO)

	old_out = await rec_old.grep(g, {
		"pattern": r"^(export )?(async )?(function|class|interface|type|enum)\s+\w+",
		"output_mode": "content", "path": STORES_DIR, "-n": True, "head_limit": 0,
	})
	new_out = await rec_new.grep(g, {
		"pattern": r".", "output_mode": "symbols", "path": STORES_DIR, "head_limit": 0,
	})
	fold_out = await rec_fold.grep(g, {
		"pattern": r".", "output_mode": "symbols", "path": STORES_DIR,
		"detail": "folded", "head_limit": 0,
	})

	old_hits = len([l for l in old_out.split("\n") if l.strip() and "No matches" not in l])
	new_hits = len([l for l in new_out.split("\n") if _SYM_LINE_RE.search(l)])
	fold_hits = len([l for l in fold_out.split("\n") if _SYM_LINE_RE.search(l)])
	return {"ground_truth": len(gt), "old_hits": old_hits, "new_hits": new_hits,
			"fold_hits": fold_hits, "fold_out": fold_out,
			"old": rec_old, "new": rec_new, "fold": rec_fold}


async def coverage_checks() -> list[tuple[str, bool, str]]:
	checks: list[tuple[str, bool, str]] = []
	g, r = GrepTool(cwd=REPO), FileReadTool(cwd=REPO)

	# 1. Python ast 精确解析
	syms = outline(PY_TARGET)
	checks.append(("py ast 解析: _eligible_for_early 存在且起点行号正确",
				   any(s.name == "_eligible_for_early" and s.start == 72 for s in syms), "engine/query_loop.py:72"))

	# 2. TS 解析（装了 tree-sitter → 精确；未装 → 启发式且带 approximate 标记）
	ts_syms = outline(TS_TARGET)
	fn = next((s for s in ts_syms if s.name == TS_SYMBOL), None)
	mode = "精确" if (fn and not fn.approximate) else "启发式"
	checks.append((f"ts 解析（{mode}模式）: {TS_SYMBOL} 可定位且行号有值",
				   fn is not None and fn.start > 0 and fn.end >= fn.start, f"range={fn.start}-{fn.end}" if fn else "missing"))

	# 3. Read 歧义路径：在 PY_TARGET 里找一个真实重名符号（定义多次）
	from collections import Counter

	name_counts = Counter(s.name for s in outline(PY_TARGET))
	dup_names = [n for n, c in name_counts.items() if c > 1]
	if dup_names:
		r_amb = await r.execute({"file_path": PY_TARGET, "symbol": dup_names[0]}, AbortController())
		checks.append(("Read 同名歧义返回候选引导",
					   r_amb.is_error and "ambiguous" in r_amb.content, f"符号 {dup_names[0]} 定义 {name_counts[dup_names[0]]} 次"))
	else:
		checks.append(("Read 同名歧义路径（文件内无重名符号，跳过）", True, "no duplicate names"))

	# 4. Read 未命中引导
	r_nf = await r.execute({"file_path": PY_TARGET, "symbol": "definitely_no_such_sym_xyz"}, AbortController())
	checks.append(("Read 未命中引导先用 Grep symbols 查名",
				   r_nf.is_error and "output_mode" in r_nf.content and "symbols" in r_nf.content, ""))

	# 5. symbol 与 offset/limit 互斥
	r_conf = await r.execute({"file_path": PY_TARGET, "symbol": PY_SYMBOL, "offset": 1}, AbortController())
	checks.append(("Read symbol 与 offset 互斥报错", r_conf.is_error and "cannot be combined" in r_conf.content, ""))

	# 6. Grep symbols 空结果提示
	r_empty = await g.execute({"pattern": "no_such_symbol_xyz_123", "output_mode": "symbols", "path": REPO, "head_limit": 5}, AbortController())
	checks.append(("Grep symbols 空结果有提示", not r_empty.is_error and "No symbols found" in r_empty.content, ""))

	# 7. Grep symbols 分页（pattern 按符号名匹配）
	r_page = await g.execute({"pattern": "test_", "output_mode": "symbols", "path": REPO, "head_limit": 5}, AbortController())
	checks.append(("Grep symbols head_limit 分页生效", "limit: 5" in r_page.content, ""))

	# 8. 内容哈希缓存：热读命中
	clear_cache()
	t0 = time.perf_counter(); outline(PY_TARGET); cold = (time.perf_counter() - t0) * 1000
	t0 = time.perf_counter(); outline(PY_TARGET); warm = (time.perf_counter() - t0) * 1000
	checks.append(("内容哈希缓存: 二次读取命中且更快", warm <= cold or warm < 1.0, f"cold={cold:.2f}ms warm={warm:.2f}ms"))

	return checks


async def main() -> None:
	print(f"# 33号计划收益评测（离线 · 无 API 调用 · 仓库：{REPO_ROOT}）\n")
	clear_cache()

	results = [
		await scenario_read_symbol(PY_TARGET, PY_SYMBOL, "读 Python 文件头部小函数 _eligible_for_early",
								   rf"def {PY_SYMBOL}\b"),
		await scenario_read_symbol(TS_TARGET, TS_SYMBOL, "读 TS 中段小方法 continueAndRevert",
								   rf"{TS_SYMBOL}\s*\("),
	]
	browse = await scenario_browse_symbols()

	print("## 一、读单个符号体：Read symbol vs Grep定位+Read\n")
	print("| 场景 | 精确行数 | 旧·保底: 轮次/token | 旧·激进: token/是否截断 | 新路径: 轮次/token | token 节省* | 内容=符号体 |")
	print("|---|---|---|---|---|---|---|")
	for res in results:
		o_s, o_f, n = res["old_safe"], res["old_fast"], res["new"]
		save = 100 * (1 - n.total_tokens / o_s.total_tokens) if o_s.total_tokens else 0
		print(
			f"| {res['label']} | {res['truth_lines']}行 | "
			f"{o_s.n_calls}次 / {o_s.total_tokens:,}tk | "
			f"{o_f.total_tokens:,}tk / {'截断' if not res['old_fast_exact'] else '完整'} | "
			f"{n.n_calls}次 / {n.total_tokens:,}tk | "
			f"**{save:.0f}%** | 旧={str(res['old_safe_exact']).lower()} 新={str(res['new_exact']).lower()} |"
		)
	print("\n\\* token 节省以旧路径保底策略为基准（不截断的正确做法）；激进策略省 token 但内容截断不可用。\n")

	print("## 二、仓库符号目录浏览：Grep symbols vs 顶层声明正则 grep\n")
	gt_n = browse["ground_truth"]
	cov_old = 100 * browse["old_hits"] / gt_n if gt_n else 0
	cov_new = 100 * browse["new_hits"] / gt_n if gt_n else 0
	cov_fold = 100 * browse["fold_hits"] / gt_n if gt_n else 0
	print("| 指标 | 旧路径（正则grep） | 新路径（symbols 全量） | 新路径（symbols folded） |")
	print("|---|---|---|---|")
	print(f"| 符号条目数（ground truth {gt_n}） | {browse['old_hits']} = **{cov_old:.0f}%** | {browse['new_hits']} = **{cov_new:.0f}%** | {browse['fold_hits']} 容器/顶层 = 折叠视图 |")
	print(f"| 调用轮次 | {browse['old'].n_calls} | {browse['new'].n_calls} | {browse['fold'].n_calls} |")
	print(f"| 返回 token | {browse['old'].total_tokens:,} | {browse['new'].total_tokens:,} | **{browse['fold'].total_tokens:,}** |")
	print("| 信息质量 | 无行号范围、无父级归属、漏方法 | 签名+行号+父级，全展开 | 类折叠成一行含成员数，方法隐藏可展开 |")
	print()

	print("## 三、轮次（agent 往返）对比\n")
	print("| 场景 | 旧路径轮次 | 新路径轮次 | 轮次节省 |")
	print("|---|---|---|---|")
	for res in results:
		o, n = res["old_safe"], res["new"]
		print(f"| {res['label']} | {o.n_calls} | {n.n_calls} | {100 * (1 - n.n_calls / o.n_calls):.0f}% |")
	print()

	print("## 四、边界覆盖清单\n")
	all_ok = True
	for name, ok, detail in await coverage_checks():
		all_ok &= ok
		print(f"- [{'PASS' if ok else 'FAIL'}] {name}" + (f"（{detail}）" if detail else ""))
	print(f"\n总体: {'全部通过' if all_ok else '存在失败项'}")

	print("\n## 五、耗时原始数据\n")
	for res in results:
		print(f"- {res['label']}: 旧·保底 {res['old_safe'].total_ms:.0f}ms | 旧·激进 {res['old_fast'].total_ms:.0f}ms | 新 {res['new'].total_ms:.0f}ms")
	print(f"- 符号浏览: 旧 {browse['old'].total_ms:.0f}ms | 新 {browse['new'].total_ms:.0f}ms | 折叠 {browse['fold'].total_ms:.0f}ms")


if __name__ == "__main__":
	asyncio.run(main())
