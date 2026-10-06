"""结构性门：工具不得用宽 except 把 Aborted（用户停止）吞成普通错误回执。

起因（2026-10-03 实测）：`WebFetchTool.execute` 的 `except Exception` 罩住了含
`abort.raise_if_aborted()` 的 try ⇒ 用户按停被写成
`fetch failed: Aborted: aborted` 的正常 ToolResult（status=error、
error_kind 被兜成 INTERNAL），而 `tools/orchestration.py:285` 的契约是 Aborted
必须上抛（转 StoppedEvent、状态记 unknown）。吞掉之后：模型读到「站点坏了」
而不是「我刚被停了」，会继续重试这条已被取消的调用。

判据（只看"吞成回执"这一族，范围与后果可对齐）：同一个 try 块内能抛 Aborted
——直接的 `x.raise_if_aborted()` / `Aborted(...)`，或本文件内可达的被调函数——
而其 `Exception`/裸 except 分支 **return 了值**，且同一 try 没有 `except Aborted`
兄弟分支 ⇒ 违规。

不在本门范围：只记日志、不 return 的宽 except（吞掉后沿控制流继续，症状不同，
混进来会让门失去可解释性）。分母有断言：扫不到足够多的"含 Aborted 源"函数即红，
防止路径写错把门变成装饰。
"""

from __future__ import annotations

import ast
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOT = ROOT / "tools"

#: 已知违规（不属本轮 / 在途文件）。双向：多一条红，修好不摘牌也红。
KNOWN: set[str] = set()

_MIN_ABORT_BEARING_FUNCS = 30  # 10-03 实测：tools/ 114 个文件 / 36 个函数


def _handler_names(handler: ast.ExceptHandler) -> list[str]:
	t = handler.type
	if t is None:
		return ["BaseException"]
	if isinstance(t, ast.Name):
		return [t.id]
	if isinstance(t, ast.Tuple):
		return [e.id for e in t.elts if isinstance(e, ast.Name)]
	return []


def _raises_aborted(node: ast.AST) -> bool:
	for n in ast.walk(node):
		if isinstance(n, ast.Call):
			if isinstance(n.func, ast.Attribute) and n.func.attr == "raise_if_aborted":
				return True
			if isinstance(n.func, ast.Name) and n.func.id == "Aborted":
				return True
		if isinstance(n, ast.Raise):
			if getattr(getattr(n.exc, "func", None), "id", "") == "Aborted":
				return True
	return False


def _called_names(node: ast.AST) -> set[str]:
	out: set[str] = set()
	for n in ast.walk(node):
		if not isinstance(n, ast.Call):
			continue
		if isinstance(n.func, ast.Attribute):
			out.add(n.func.attr)
		elif isinstance(n.func, ast.Name):
			out.add(n.func.id)
	return out


def _reachable_aborts(funcs: list[ast.AST]) -> set[str]:
	"""本文件内"执行会抛 Aborted"的函数名（含间接：execute → self.call → 抛）。"""
	direct = {f.name for f in funcs if _raises_aborted(f)}
	reachable = set(direct)
	for _ in range(4):
		grew = set(reachable)
		for f in funcs:
			if f.name in grew:
				continue
			if _called_names(f) & reachable:
				grew.add(f.name)
		if grew == reachable:
			break
		reachable = grew
	return reachable


def _violate(tree: ast.AST) -> tuple[list[str], int]:
	funcs = [
		n
		for n in ast.walk(tree)
		if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
	]
	reachable = _reachable_aborts(funcs)
	hits: list[str] = []
	bearing = 0
	for fn in funcs:
		if not (_raises_aborted(fn) or (_called_names(fn) & reachable)):
			continue
		bearing += 1
		for t in ast.walk(fn):
			if not isinstance(t, ast.Try):
				continue
			can_abort = (
				_raises_aborted(t)
				or any(_raises_aborted(h) for h in t.finalbody)
				or bool(_called_names(t) & reachable)
			)
			if not can_abort:
				continue
			if any("Aborted" in _handler_names(h) for h in t.handlers):
				continue
			for h in t.handlers:
				if not (set(_handler_names(h)) & {"Exception", "BaseException"}):
					continue
				returns = any(isinstance(n, ast.Return) for n in h.body)
				raises = any(isinstance(n, ast.Raise) for n in h.body)
				if returns and not raises:
					hits.append(f":: {fn.name}@{h.lineno}")
	return hits, bearing


def _scan_source(name: str, src: str) -> tuple[list[str], int]:
	return _violate(ast.parse(src))


def _scan_tree() -> tuple[set[str], int]:
	violations: set[str] = set()
	bearing = 0
	for p in sorted(SCAN_ROOT.rglob("*.py")):
		if "__pycache__" in p.parts:
			continue
		try:
			src = io.open(p, encoding="utf-8", errors="replace").read()
			hits, n = _scan_source(str(p), src)
		except (SyntaxError, OSError):
			continue
		bearing += n
		violations.update(f"{p.relative_to(ROOT)}{h}" for h in hits)
	return violations, bearing


SWALLOW = """
async def execute(inp, abort):
    try:
        abort.raise_if_aborted()
        return ok()
    except Exception as exc:
        return ToolResult(content=f"failed: {exc}", is_error=True)
"""

PROPER = """
async def execute(inp, abort):
    try:
        abort.raise_if_aborted()
        return ok()
    except Aborted:
        raise
    except Exception as exc:
        return ToolResult(content=f"failed: {exc}", is_error=True)
"""

ONE_HOP = """
def call(abort):
    abort.raise_if_aborted()
    return 1

def execute(inp, abort):
    try:
        return call(abort)
    except Exception as exc:
        return str(exc)
"""

LOG_ONLY = """
def execute(inp, abort):
    try:
        abort.raise_if_aborted()
    except Exception:
        log.warning("nope")
    return "fell through"
"""


def test_positive_controls() -> None:
	# 门必须抓得住真形：同一 try 内直接吞、以及被调函数间接吞。
	for name, src in (("SWALLOW", SWALLOW), ("ONE_HOP", ONE_HOP)):
		hits, bearing = _scan_source(name, src)
		assert hits, f"{name} 未被识别为违规（门是装饰的）"
		assert bearing >= 1


def test_negative_controls() -> None:
	# 已按契约上抛的写法不许红；只记日志不 return 的不在本门范围。
	hits, _b = _scan_source("PROPER", PROPER)
	assert not hits, hits
	hits, _b = _scan_source("LOG_ONLY", LOG_ONLY)
	assert not hits, hits


def test_scan_reaches_a_real_denominator() -> None:
	_violations, bearing = _scan_tree()
	assert bearing >= _MIN_ABORT_BEARING_FUNCS, (
		f"只扫到 {bearing} 个含 Aborted 源的函数，分母不对 ⇒ 门不成立"
	)


def test_production_tree_matches_known_list_exactly() -> None:
	violations, _bearing = _scan_tree()
	assert violations == KNOWN, (
		f"新增吞 Aborted 的站点：{sorted(violations - KNOWN)}；"
		f"已修但没摘牌：{sorted(KNOWN - violations)}"
	)


def test_webfetch_fix_is_in_place() -> None:
	# 本轮修的那处必须真的不再命中（旧形状复现＝红）。
	src = io.open(
		ROOT / "tools" / "web_fetch_tool" / "web_fetch_tool.py",
		encoding="utf-8",
		errors="replace",
	).read()
	hits, bearing = _scan_source("web_fetch_tool.py", src)
	assert bearing >= 1
	assert not hits, hits
