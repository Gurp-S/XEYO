"""只读探针：规则 1 之后，区域内的用户消息还有几条被渲染进热层？

用于判定 seeds.py「去掉 task_updates」是否造成信息空洞：
render_main 会跳过 pin_nodes，而 pin_nodes 含**全部**实质用户节点，
所以除「目标」（首条）外，其余用户原话现在没有任何渲染通道。
"""

import sys
from pathlib import Path

ROOT = Path(r"D:\lea\XenYon code")
sys.path.insert(0, str(ROOT / "python"))

from engine.compact import keep_tail_cut  # noqa: E402
from synaptic.graph import build_graph  # noqa: E402
from synaptic.project import project, default_params  # noqa: E402
from synaptic.replay import _as_api_message, load_jsonl, user_turn_starts  # noqa: E402
from synaptic.seeds import collect_seeds, harvest_needles  # noqa: E402
from synaptic.types import KIND_USER  # noqa: E402


def main(path: str, turn: int = -1) -> None:
	f = Path(path)
	api = [_as_api_message(r) for r in load_jsonl(f)]
	starts = user_turn_starts(api)
	t = turn if turn >= 0 else len(starts) - 1
	end = starts[t + 1] if t + 1 < len(starts) else len(api)
	prefix = api[:end]
	region_end = keep_tail_cut(prefix)

	p = default_params("Medium+", "closure")
	proj = project(prefix, region_end=region_end, params=p, session=f.stem)
	hot = proj.text

	nodes = [n for n in proj.graph.nodes if n.idx < region_end]
	users = [n for n in nodes if n.kind == KIND_USER and " ".join(n.text.split())]
	sub = [n for n in users if len(n.text.strip()) >= 4]

	needles = harvest_needles(proj.graph, {s.path: s for s in proj.result.hot.file_states},
							  region_end=region_end)
	user_needles = list(needles["user"])

	hit = [s for s in user_needles if s in hot]
	miss = [s for s in user_needles if s not in hot]

	seeds = collect_seeds(proj.graph, prefix, {s.path: s for s in proj.result.hot.file_states})
	pin_node_set = set(seeds.pin_nodes)
	user_pinned = [n.idx for n in sub if n.idx in pin_node_set]

	print(f"session={f.stem} msgs={len(prefix)} turns={len(starts)} turn={t}")
	print(f"region_end={region_end} (尾部 {len(prefix) - region_end} 条消息不受压缩)")
	print(f"区域内实质用户消息={len(user_needles)} 命中={len(hit)} 缺失={len(miss)}")
	print(f"pin_nodes 内用户节点={len(user_pinned)} / 实质用户节点={len(sub)}")
	print(f"热层里出现『目标: 』行={'是' if '目标:' in hot else '否'}"
	      f"  出现『指令: 』行={'是' if '指令:' in hot else '否'}")
	print("缺失的用户原话（前 60 字）：")
	for i, s in enumerate(miss):
		print(f"  [{i}] {s[:60]}")
	if hot.strip():
		print(f"热层 token={proj.result.hot.tokens} 字符={len(hot)}")


if __name__ == "__main__":
	main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else -1)
