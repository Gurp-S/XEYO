"""结构性门：生产模块里**不允许**出现"从未绑定的全局名加载"（LOAD_GLOBAL）。

起因（2026-10-03 两条实测崩溃）：
1. `channels/filehelper/service.py::_state_payload` 写 `"streaming": _stream_active` —
   那是 `ChannelMirror` 的实例属性，本模块从未绑定 ⇒ 每次状态广播 NameError，
   `/v1/filehelper/start|stop` 直接 500，登录二维码/错误态永远推不到界面。
   （由 HTTP 普查打出来：78 个 GET 端点 0 命中，变更型端点第一条就命中它。）
   **该文件已于 2026-10-05 随 filehelper 远程通道整体删除**——此处保留事故记录，
   下面 `test_the_two_shipped_crashes_are_now_gone` 只再校验存活的另外两处。
2. `engine/query_loop.py` 在计划衰减分支里把 `approved_plan_decays_on` 当全局名调用，
   而函数住在 `prompt/pre_llm_inject.py`、本模块从未导入 ⇒ 批准过计划的会话
   第一条工具结果落盘就炸。
   同批还发现 `rewind/service.py` 的**错误上报语句**引用了签名里不存在的 `plan`：
   回填失败时先抛 NameError，把原异常顶掉、audit 也写不进去。

为什么判据用字节码而不是 AST 名字表：
`from __future__ import annotations` 之下注解不求值 ⇒ 只看 LOAD_GLOBAL 就不会把
`Any`/`Sequence` 这类"仅标注出现"的名字误报；而局部名是 LOAD_FAST，
未绑定的全局加载必然是运行期 NameError（除运行中被注入 globals，未见此形态）。
模块级/类体用 LOAD_NAME，不参与本判据——那里的笔误在 import 当场炸，套件已兜住。

KNOWN 是**双向**的：多一条违规红，少一条（修好了却没摘牌）也红。
"""

from __future__ import annotations

import ast
import builtins
import dis
import re
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILTINS = set(dir(builtins))
_DUNDER = re.compile(r"^__[A-Za-z0-9_]+__$")
_SKIP_DIRS = {".venv", "__pycache__", "node_modules", ".pytest_cache", "tests", "scripts", "evals"}
_SKIP_PREFIX = (".tmp", ".pytest_tmp", ".pytmp", "_wsc_out", ".xeyo")

#: 已知且**本轮不归我改**的违规（他人/在途文件）。修好后必须从这里摘掉，否则本门红。
# 2026-10-05：两条历史欠账（subagent_runner 缺局部 import、deepseek 包装函数引用未绑定名）已修复并摘牌。
# 此后本门零容忍：任何一条未绑定全局名都直接红。
KNOWN: set[str] = set()


def module_bound_names(tree: ast.Module) -> set[str]:
	"""模块运行期 globals 的名字集合（含 try/if 块内的模块级绑定与 global 写入）。"""
	bound: set[str] = set()

	def add_targets(tgt: ast.AST) -> None:
		for n in ast.walk(tgt):
			if isinstance(n, ast.Name):
				bound.add(n.id)
			elif isinstance(n, (ast.Tuple, ast.List)):
				for e in n.elts:
					add_targets(e)

	in_scope: list[ast.AST] = []

	def collect(node: ast.AST) -> None:
		for child in ast.iter_child_nodes(node):
			if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
				bound.add(child.name)
				continue
			in_scope.append(child)
			if isinstance(
				child,
				(ast.Try, ast.If, ast.With, ast.AsyncWith, ast.For, ast.AsyncFor, ast.While),
			):
				collect(child)

	collect(tree)
	for st in in_scope:
		if isinstance(st, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
			for t in getattr(st, "targets", None) or [st.target]:
				add_targets(t)
		elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
			bound.add(st.name)
		elif isinstance(st, (ast.Import, ast.ImportFrom)):
			for a in st.names:
				bound.add((a.asname or a.name).split(".")[0])
		elif isinstance(st, (ast.For, ast.AsyncFor)):
			add_targets(st.target)
		elif isinstance(st, (ast.With, ast.AsyncWith)):
			for item in st.items:
				if item.optional_vars is not None:
					add_targets(item.optional_vars)
		elif isinstance(st, ast.Try):
			for h in st.handlers:
				if h.name:
					bound.add(h.name)

	for n in ast.walk(tree):
		if isinstance(n, ast.Global):
			bound.update(n.names)
		elif isinstance(n, ast.ExceptHandler) and n.name:
			bound.add(n.name)  # 宽松：宁可漏报也不误报
		elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
			declared = {nm for g in ast.walk(n) if isinstance(g, ast.Global) for nm in g.names}
			if not declared:
				continue
			for sub in ast.walk(n):
				if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store) and sub.id in declared:
					bound.add(sub.id)
	return bound


def global_loads(co: types.CodeType, out: set[tuple[str, str]]) -> None:
	for ins in dis.get_instructions(co):
		if ins.opname == "LOAD_GLOBAL":
			name = ins.argval or ""
			if name:
				out.add((co.co_name, name))
	for c in co.co_consts:
		if isinstance(c, types.CodeType):
			global_loads(c, out)


def violations(src: str, filename: str) -> set[str]:
	tree = ast.parse(src)
	co = compile(tree, filename, "exec")
	bound = module_bound_names(tree) | BUILTINS
	loads: set[tuple[str, str]] = set()
	global_loads(co, loads)
	return {
		f"{filename}:{fn}:{name}"
		for fn, name in loads
		if name not in bound and not _DUNDER.match(name)
	}


def production_files() -> list[Path]:
	out = []
	for p in sorted(ROOT.rglob("*.py")):
		rel = p.relative_to(ROOT)
		if set(rel.parts) & _SKIP_DIRS or str(rel).startswith(_SKIP_PREFIX):
			continue
		out.append(p)
	return out


# ---- 判据自证：正向对照（合成夹具必须被报）------------------------------------

def test_positive_controls() -> None:
	bug_attr = '''
_mirror = object()

def _state_payload():
	return {"streaming": _stream_active}
'''
	bug_call = '''
async def query_loop():
	if approved_plan_decays_on("Write", False):
		return 1
'''
	bug_in_handler = '''
def f():
	try:
		pass
	except Exception:
		return plan.target_turn_id
'''
	assert "_stream_active" in str(violations(bug_attr, "a.py"))
	assert "approved_plan_decays_on" in str(violations(bug_call, "b.py"))
	assert "plan" in str(violations(bug_in_handler, "c.py"))
	assert violations(bug_attr, "a.py") == {"a.py:_state_payload:_stream_active"}


# ---- 判据自证：反向对照（三种合法形态不得被报）--------------------------------

def test_negative_controls() -> None:
	optional_dep = '''
try:
    import httpx
except ImportError:
    httpx = None

def client():
    return httpx.AsyncClient()
'''
	annotation_only = '''
from __future__ import annotations
from typing import Any

def f(x: Any, y: "Sequence[int]") -> int:
    return len(x) + y[0]
'''
	local_import = '''
def g():
	from prompt.pre_llm_inject import approved_plan_decays_on
	return approved_plan_decays_on("Write", False)
'''
	global_write = '''
_default = None

def set_it(v):
	global _default
	_default = v

def use_it():
	return _default
'''
	assert violations(optional_dep, "d.py") == set()
	assert violations(annotation_only, "e.py") == set()
	assert violations(local_import, "f.py") == set()
	assert violations(global_write, "g.py") == set()


def test_the_two_shipped_crashes_are_now_gone() -> None:
	"""本次修掉的两处必须真从判据里消失（不是被豁免清单收走）。"""
	for rel in ("engine/query_loop.py", "rewind/service.py"):
		src = (ROOT / rel).read_text(encoding="utf-8").lstrip("﻿")
		assert violations(src, rel) == set(), violations(src, rel)


def test_production_tree_matches_known_list_exactly() -> None:
	found: set[str] = set()
	scanned = 0
	for p in production_files():
		rel = p.relative_to(ROOT).as_posix()
		try:
			# utf-8-sig：树里确实有带 BOM 的已提交 .py（model/chunks.py 等），
			# 直接按 utf-8 读会把 BOM 留在首字符，compile 当场 SyntaxError。
			src = p.read_text(encoding="utf-8-sig")
		except (OSError, UnicodeError):
			continue
		scanned += 1
		found |= violations(src, rel)
	assert scanned > 400, f"只扫到 {scanned} 个生产文件 ⇒ 探针作用域有问题，结论不成立"
	assert found == KNOWN, (
		f"新增未绑定全局名 {sorted(found - KNOWN)}；"
		f"已修好但没摘牌 {sorted(KNOWN - found)}"
	)
