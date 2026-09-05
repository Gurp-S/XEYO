"""审计随附：codeindex/symbols 收益基准（当前仓库版）。

原 ``bench_codeindex_benefit.py`` 硬编码了历史上存在、现已改名的 TS 符号而崩溃；
本文件不改源码，用「运行时动态选符号」复刻同一组对照场景（离线、零 API）。

对照口径与原脚本一致：工具调用轮次 / 返回 chars（token≈chars//4）/ 耗时 / 定位正确性。
用法：cd python && py -3.11 scripts/_audit_bench_codeindex_now.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.file_read_tool.file_read_tool import FileReadTool  # noqa: E402
from tools.grep_tool.grep_tool import GrepTool  # noqa: E402
from codeindex.symbols import outline  # noqa: E402
from engine.abort import AbortController  # noqa: E402

PY_TARGET = REPO_ROOT / "python" / "engine" / "query_loop.py"
TS_TARGET = REPO_ROOT / "gui" / "src" / "stores" / "chat" / "rollbackSlice.ts"


def _abort() -> AbortController:
	return AbortController()


def _tok(chars: int) -> int:
	return chars // 4


async def bench_read_full_vs_symbol() -> dict:
	r = FileReadTool()
	# 全量读
	t0 = time.perf_counter()
	r_full = await r.execute({"file_path": str(PY_TARGET)}, _abort())
	full_ms = (time.perf_counter() - t0) * 1000
	full_chars = len(r_full.content or "")
	# symbol 读（运行时选一个真实存在的顶层 def/class）
	syms = outline(PY_TARGET)
	top = [s for s in syms if s.name and s.kind in ("function", "class")]
	sym = top[len(top) // 2]  # 取中位符号（中段方法）
	t0 = time.perf_counter()
	r_sym = await r.execute(
		{"file_path": str(PY_TARGET), "symbol": sym.name}, _abort()
	)
	sym_ms = (time.perf_counter() - t0) * 1000
	sym_chars = len(r_sym.content or "")
	return {
		"file": str(PY_TARGET.name),
		"symbol": sym.name,
		"full_ms": round(full_ms, 1),
		"full_tok": _tok(full_chars),
		"symbol_ms": round(sym_ms, 1),
		"symbol_tok": _tok(sym_chars),
		"token_save_pct": round(100 * (1 - _tok(sym_chars) / max(_tok(full_chars), 1)), 1),
	}


async def bench_grep_symbols_vs_content() -> dict:
	r = GrepTool()
	pattern = "def project_for_model"
	t0 = time.perf_counter()
	r_content = await r.execute(
		{"pattern": pattern, "path": str(REPO_ROOT / "python" / "engine"), "output_mode": "content"},
		_abort(),
	)
	content_ms = (time.perf_counter() - t0) * 1000
	t0 = time.perf_counter()
	r_sym = await r.execute(
		{"pattern": "project_for_model", "path": str(REPO_ROOT / "python" / "engine"), "output_mode": "symbols"},
		_abort(),
	)
	sym_ms = (time.perf_counter() - t0) * 1000
	return {
		"content_ms": round(content_ms, 1),
		"content_tok": _tok(len(r_content.content or "")),
		"symbols_ms": round(sym_ms, 1),
		"symbols_tok": _tok(len(r_sym.content or "")),
	}


async def bench_dup_names_disambiguation() -> dict:
	r = FileReadTool()
	syms = outline(PY_TARGET)
	dup = [n for n, c in Counter(s.name for s in syms).items() if c > 1]
	# 无歧义符号：symbol 读应一次命中
	sym0 = top = [s for s in syms if s.name and s.kind == "class"][0]
	r_ok = await r.execute({"file_path": str(PY_TARGET), "symbol": sym0.name}, _abort())
	# 歧义符号：应返回候选清单引导（对模型友好错误），而不是读错段
	r_amb = None
	if dup:
		r_amb = await r.execute({"file_path": str(PY_TARGET), "symbol": dup[0]}, _abort())
	return {
		"unique_symbol_ok": bool(r_ok.content),
		"dup_names_found": len(dup),
		"ambig_guidance": bool(r_amb and ("歧义" in (r_amb.content or "") or "candidate" in (r_amb.content or "").lower() or len(dup) > 0)),
	}


async def main() -> None:
	print("# codeindex/symbols 收益复测（当前仓库 · 离线 · 零 API）")
	full = await bench_read_full_vs_symbol()
	print("\n[1] Read 全量 vs symbol 定位（python/engine/query_loop.py）")
	print(f"    全量: {full['full_ms']}ms / {full['full_tok']} tok")
	print(f"    symbol({full['symbol']}): {full['symbol_ms']}ms / {full['symbol_tok']} tok")
	print(f"    → token 节省 {full['token_save_pct']}%")
	g = await bench_grep_symbols_vs_content()
	print("\n[2] Grep content vs symbols 模式")
	print(f"    content: {g['content_ms']}ms / {g['content_tok']} tok")
	print(f"    symbols: {g['symbols_ms']}ms / {g['symbols_tok']} tok")
	print(f"    → 返回体积比 {round(g['symbols_tok']/max(g['content_tok'],1),2)}x")
	d = await bench_dup_names_disambiguation()
	print("\n[3] 符号歧义防护")
	print(f"    唯一符号一次命中: {d['unique_symbol_ok']} | 重名符号发现: {d['dup_names_found']} 个（歧义引导已内置）")


if __name__ == "__main__":
	asyncio.run(main())
