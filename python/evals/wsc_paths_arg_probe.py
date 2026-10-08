"""旁路探针：`XEYO_WSC_PATHS_ARG_ONLY` 的收益与安全边界（不接主链路）。

只做两件事，不写主链路状态：
  ① 对真实语料量化「refs（含正文提过的路径）→ arg_paths（工具参数点名的路径）」
     会少收多少路径、多少字符；
  ② 对**被滤掉的每一条**做盘上存在性核对 —— 存在性只作**人眼参考**，不作判据
     （投影可能跑在宿主而工具跑在容器，宿主 `stat` 会假阴）。

判据见 `synaptic/paths.py::_touch_span`。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "python"))

from synaptic.graph import build_graph  # noqa: E402
from synaptic.paths import _touch_span  # noqa: E402


def rows_to_messages(path: Path) -> list[dict]:
	"""兼容两种落盘形态：`{"message": {...}}` 事件行 / 裸 message 行。"""
	out: list[dict] = []
	for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
		line = line.strip()
		if not line:
			continue
		try:
			ev = json.loads(line)
		except Exception:
			continue
		msg = ev.get("message") if isinstance(ev, dict) else None
		if isinstance(msg, dict) and msg.get("role") in ("user", "assistant"):
			out.append(msg)
		elif isinstance(ev, dict) and ev.get("role") in ("user", "assistant"):
			out.append(ev)
	return out


def exists_on_disk(rel: str) -> bool:
	"""仅参考：路径在**本机工作区**是否存在（不参与判据）。"""
	try:
		cand = _ROOT / rel
		return cand.exists() or Path(rel).exists()
	except Exception:
		return False


def named_by_tools(messages: list[dict]) -> set[str]:
	"""**唯一有意义的假阴判据**：被工具「点名」过的路径全集。

点名 = ``tool_input_paths``（Read 的 file_path…）∪ ``command_paths``（Bash 命令串）
∪ Bash 单文件 target —— 与 ``graph.py:437`` 组装 ``paths_by_id`` 的口径同源。

为什么 ``existed_on_disk`` 不能当判据：输出正文里「提到」的路径会进 ``refs``，
盘上当然存在（``AGENTS.md`` / ``query_loop.py`` …），但按契约它们**不许**冒充
「被操作的文件」（``types.py:71-72``）⇒ 被 ``arg_paths ∪ scope_paths`` 滤掉是
**期望行为**。真正的假阴只有一种：**被点名了，却不在候选池里**。
"""
	from common.read_target import single_file_target
	from synaptic.graph import tool_use_blocks
	from synaptic.textutil import command_paths, normalize_path, tool_input_paths

	out: set[str] = set()
	for msg in messages:
		for u in tool_use_blocks(msg):
			inp = u.get("input")
			named = tool_input_paths(inp)
			out.update(named)
			out.update(command_paths(inp))
			if not named and isinstance(inp, dict):
				target = single_file_target(str(inp.get("command") or inp.get("cmd") or ""))
				if target:
					out.add(normalize_path(target))
	return out


def measure(path: Path) -> dict:
	messages = rows_to_messages(path)
	if not messages:
		return {"file": path.name, "error": "no messages parsed"}

	graph = build_graph(messages)
	end = len(graph.nodes)

	os.environ.pop("XEYO_WSC_PATHS_ARG_ONLY", None)
	span_refs = _touch_span(graph, end)
	os.environ["XEYO_WSC_PATHS_ARG_ONLY"] = "1"
	span_args = _touch_span(graph, end)
	os.environ.pop("XEYO_WSC_PATHS_ARG_ONLY", None)

	nodes_with_refs = sum(1 for n in graph.nodes if n.refs)
	nodes_with_args = sum(1 for n in graph.nodes if n.arg_paths)

	refs_keys = set(span_refs)
	args_keys = set(span_args)
	dropped = sorted(refs_keys - args_keys)
	kept = sorted(args_keys)
	added = sorted(args_keys - refs_keys)  # 理论上应为空（arg_paths ⊆ refs）

	dropped_chars = sum(len(p) for p in dropped)
	refs_chars = sum(len(p) for p in refs_keys)

	# 被滤掉的里有多少在盘上真实存在 —— **不是事故判据**（见 named_by_tools 说明），
	# 只用来对照：输出正文提到过的真文件被滤掉，正是本改动要的效果。
	dropped_real = [p for p in dropped if exists_on_disk(p)]
	# 保留的里有多少在盘上不存在 —— 参考：保留侧的"已删/未建"残留。
	kept_unreal = [p for p in kept if not exists_on_disk(p)]

	# ===== 真事故判据（唯一可证伪的）=====
	named = named_by_tools(messages)
	missed = sorted(named - args_keys)  # 被工具点名，却不在 arg_paths ∪ scope_paths
	return {
		"file": path.name,
		"messages": len(messages),
		"nodes": end,
		"nodes_with_refs": nodes_with_refs,
		"nodes_with_arg_paths": nodes_with_args,
		"paths_refs": len(refs_keys),
		"paths_args": len(args_keys),
		"paths_named_by_tools": len(named),
		"added_by_arg_only": len(added),
		"dropped": len(dropped),
		"dropped_chars": dropped_chars,
		"refs_chars": refs_chars,
		"pct_paths_dropped": round(100.0 * len(dropped) / max(1, len(refs_keys)), 1),
		"pct_chars_dropped": round(100.0 * dropped_chars / max(1, refs_chars), 1),
		"REAL_DEFECT_named_but_dropped": missed,
		"dropped_but_exists_on_disk": dropped_real,
		"kept_but_absent_on_disk": kept_unreal,
		"sample_dropped": dropped[:25],
	}


def find_session_jsonl(stem: str) -> list[Path]:
	hits: list[Path] = []
	for root in (_ROOT / ".xeyo", _ROOT / ".xeyo_offload", _ROOT / "python" / ".xeyo"):
		if root.exists():
			hits.extend(root.rglob(stem + ".jsonl"))
	return hits


def main() -> int:
	args = sys.argv[1:]
	corpora: list[Path] = []
	for a in args:
		p = Path(a)
		if p.exists():
			corpora.append(p)
	if not corpora:
		corpora = [p for p in [
			_ROOT / "_wsc_out" / "wsc_demo" / "corpus" / "sess_real_200turn_c2.jsonl",
			_ROOT / "_wsc_out" / "project-fix-samples" / "events.jsonl",
		] if p.exists()]
		corpora.extend(find_session_jsonl("sess_mux0q86a_ea2kv9"))

	if not corpora:
		print("没有找到可用语料，显式传入 jsonl 路径。")
		return 2

	report = [measure(p) for p in corpora]
	for r in report:
		print(json.dumps(r, ensure_ascii=False, indent=2))
		print("-" * 70)

	out = _ROOT / "_wsc_out" / "paths_arg_probe.json"
	try:
		out.parent.mkdir(parents=True, exist_ok=True)
		out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
		print("report:", out)
	except Exception as exc:  # noqa: BLE001
		print("report 未落盘:", exc)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
