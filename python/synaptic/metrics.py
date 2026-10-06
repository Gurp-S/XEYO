"""WSC 度量：关键信息存活率 / 可恢复性 / 前缀连续性 / 确定性 / 零 LLM。

这里的每个指标都刻意设计成**非同义反复**：
- 关键信息针来自原始历史，不是 PIN 集的产物 → 存活率检验真实携带能力；
- 可恢复性靠 expand 往返逐字节比对，不靠自述；
- 前缀连续性只数 token，不猜 KV 行为。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from synaptic.textutil import node_token_len, normalize_path
from synaptic.types import WscResult

FORBIDDEN_IMPORTS = (
	"anthropic",
	"openai",
	"httpx",
	"requests",
	"aiohttp",
	"urllib.request",
	"http.client",
	"socket",
	"litellm",
	"transformers",
	"torch",
)


def lcp_tokens(a: str, b: str) -> int:
	"""两段文本的最长公共前缀折算 token（前缀缓存友好度的近似）。"""
	if not a or not b:
		return 0
	n = min(len(a), len(b))
	i = 0
	while i < n and a[i] == b[i]:
		i += 1
	return node_token_len(a[:i])


def needle_survival(
	hot_text: str, needles: dict[str, tuple[str, ...]]
) -> dict[str, dict[str, float | int]]:
	"""按类别统计关键信息针在热层的存活率。"""
	norm_hot = " ".join(hot_text.split())
	out: dict[str, dict[str, float | int]] = {}
	for cat, items in needles.items():
		if not items:
			out[cat] = {"n": 0, "hit": 0, "rate": 1.0}
			continue
		hit = 0
		for it in items:
			target = " ".join(str(it).split())
			if not target:
				continue
			if target in norm_hot:
				hit += 1
				continue
			# 路径类允许命中其归一化形态的最后一段（热层可能写全路径或短名）。
			# path_recent 是 path 的近期子集，必须使用同一宽松口径，否则会在
			# 完全相同的渲染下报出偏低存活率。
			#
			# 2026-09-16：``failure_site`` 与 ``path`` **是同一批字符串**
			# （都是 `is_error` 节点的 refs，见 seeds.harvest_needles），此前却只在
			# `path` 上有回退 ⇒ 同一条路径在同一个热层里「path 记命中、failure_site 记漏失」。
			# 实测纯口径差 7.7pp（最大 4 会话末 6 回合，n=336）。补上后三类同判据。
			# 已知代价：basename 子串匹配会多计（`src/config.ts` 命中 `src/myconfig.ts`），
			# 三类一并承担，故仍是**上界**口径，不改变相对比较。
			if cat in ("path", "path_recent", "failure_site"):
				short = normalize_path(target).split("/")[-1]
				if short and short in norm_hot:
					hit += 1
		out[cat] = {"n": len(items), "hit": hit, "rate": hit / max(1, len(items))}
	return out


def recoverability(proj) -> dict[str, float | int]:
	"""可恢复性：被剪节点是否都有句柄，且句柄往返是否逐字节无损。"""
	graph = proj.graph
	cold = proj.cold
	pruned = set(proj.result.hot.pruned_nodes)

	bound: set[int] = set()
	for handle, nodes in cold.handles.items():
		bound.update(nodes)

	unbound = sorted(pruned - bound)
	# 逐句柄往返比对
	checked = 0
	lossless = 0
	for handle, nodes in cold.handles.items():
		try:
			texts = cold.expand(handle)
		except KeyError:
			continue
		for idx, got in zip(nodes, texts):
			node = graph.node(idx)
			if node is None:
				continue
			checked += 1
			if got == node.text:
				lossless += 1
	return {
		"pruned": len(pruned),
		"bound": len(pruned & bound),
		"unbound": len(unbound),
		"unbound_idx": unbound[:20],
		"coverage": (len(pruned & bound) / len(pruned)) if pruned else 1.0,
		"checked": checked,
		"lossless": lossless,
		"lossless_rate": (lossless / checked) if checked else 1.0,
	}


def exposed_handles(proj) -> int:
	"""发射文本内不同取回引用的出现数；不代表可执行、被使用或任务成功。

	Read 按实际路径和范围去重，expand 按句柄去重。冷层隐藏绑定不计；
	原文内引用形态的文本也属于出现，不能用这个数替代恢复合同验收。
	"""
	from synaptic.handle_coverage import visible_reference_count
	from synaptic.handles import _EXPAND_RE, _READ_RE

	return visible_reference_count(getattr(proj, "text", "") or "", _EXPAND_RE, _READ_RE)




def assert_no_llm_dependency(package_dir: Path | None = None) -> list[str]:
	"""静态检查：WSC 包内不得 import 任何 LLM / 网络依赖。

这是「零 LLM 调用」的机器执法口径——比运行期计数器更难绕过。
	"""
	root = package_dir or Path(__file__).resolve().parent
	problems: list[str] = []
	for py in sorted(root.rglob("*.py")):
		for lineno, mod in _imports_of(py):
			for bad in FORBIDDEN_IMPORTS:
				if mod == bad or mod.startswith(bad + "."):
					problems.append(f"{py.name}:{lineno} imports {mod}")
	return problems


#: 算法层模块：旁路形态的核心，必须对生产链零依赖（harness 层不受此约束）。
ALGORITHM_MODULES = (
	"__init__.py",
	"types.py",
	"memo.py",
	"freshness.py",
	"state_source.py",
	"failure_modes.py",
	"qa_visibility.py",
	"qa_grading.py",
	"eval_stats.py",
	"textutil.py",
	"graph.py",
	"filestate.py",
	"seeds.py",
	"todo_snapshot.py",
	"todo_fields.py",
	"todo_state.py",
	"paths.py",
	"visible_paths.py",
	"pin_render.py",
	"pin_sources.py",
	"read_receipt.py",
	"handle_coverage.py",
	"read_plan.py",
	"read_budget.py",
	"fixed_budget.py",
	"freeze.py",
	"rehydrate.py",
	"retrieval.py",
	"budget.py",
	"closure.py",
	"prune.py",
	"handles.py",
	"cadence.py",
	"timing.py",
	"assemble.py",
	"journal_rollover.py",
	"group_recovery.py",
	"journal_snapshot.py",
	"coldstore.py",
	"cold_evidence.py",
	"group_reference.py",
	"project.py",
	"metrics.py",
)

#: harness 层：允许（且必须）借用生产链的口径与成本模型。
HARNESS_MODULES = ("replay.py", "report.py", "__main__.py")

PRODUCTION_ROOTS = ("engine", "memory", "server", "usage", "permissions", "prompt", "tools", "slash", "cli")


def _imports_of(py: Path) -> list[tuple[int, str]]:
	try:
		tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
	except (SyntaxError, OSError) as exc:
		return [(0, f"<unparsable: {exc}>")]
	out: list[tuple[int, str]] = []
	for node in ast.walk(tree):
		mods: list[str] = []
		if isinstance(node, ast.Import):
			mods = [a.name for a in node.names]
		elif isinstance(node, ast.ImportFrom) and node.module:
			mods = [node.module]
		for m in mods:
			out.append((getattr(node, "lineno", 0), m))
	return out


def assert_algorithm_isolation(package_dir: Path | None = None) -> list[str]:
	"""机器执法「算法层对生产链零依赖」。

融不融入主链之前，这条不变量保证 WSC 可以整目录删除而不留残根；一旦有人
在算法层写下 ``from engine.compact import ...``，本检查立刻变红。
	"""
	root = package_dir or Path(__file__).resolve().parent
	problems: list[str] = []
	allowed_extra = {"synaptic"}
	for name in ALGORITHM_MODULES:
		py = root / name
		if not py.is_file():
			problems.append(f"{name}: missing")
			continue
		for lineno, mod in _imports_of(py):
			top = mod.split(".")[0]
			if top in allowed_extra:
				continue
			if top.startswith("<"):
				problems.append(f"{name}:{lineno} {mod}")
				continue
			if top in PRODUCTION_ROOTS:
				problems.append(f"{name}:{lineno} imports production module {mod}")
	return problems


def determinism_digest(result: WscResult) -> str:
	"""同输入必同输出：热层文本 + 关键结构一起做摘要。"""
	import hashlib

	parts = [
		result.hot.text,
		",".join(str(i) for i in result.hot.kept_nodes),
		",".join(str(i) for i in result.hot.pruned_nodes),
		",".join(c.card_id for c in result.hot.cards),
		result.level,
		result.mode,
	]
	return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:16]
