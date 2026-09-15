"""只读探针：会话里 ``kind == KIND_USER`` 的节点到底是什么？

背景：``_pin_hole_probe.py`` 报「区域内实质用户消息=17」但 ``seeds.user_nodes`` 有 188 个。
两者用的是**同一个谓词**（``kind == KIND_USER and _substantive(text)``），差异只可能来自
``harvest_needles`` 里的 ``dict.fromkeys`` 去重 ⇒ 188 个节点里重复文本极多。

真伪必须当面看：如果 188 个节点里绝大多数是同一段文字，那它们不是「人类原话」，
而是引擎/脚本注入的伪用户消息——``_substantive`` 的 ``_ENGINE_INJECTED`` 没拦住它们。
``[REQUESTS]`` 把它们逐条渲染 = 重复计费 + 违反规则 1。

用法：
    ./.venv/Scripts/python.exe tests/wsc/_user_nodes_probe.py <session.jsonl>

零花费、只读。
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path


def _repo_root() -> Path:
	return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
if str(ROOT / "python") not in sys.path:
	sys.path.insert(0, str(ROOT / "python"))

from engine.compact import keep_tail_cut  # noqa: E402
from synaptic.graph import build_graph  # noqa: E402
from synaptic.replay import _as_api_message, load_jsonl, user_turn_starts  # noqa: E402
from synaptic.seeds import _substantive  # noqa: E402
from synaptic.types import KIND_USER  # noqa: E402


def main(path: str, turn: int = -1) -> int:
	f = Path(path)
	if not f.is_file():
		print(f"no such session: {f}")
		return 2

	api = [_as_api_message(r) for r in load_jsonl(f)]
	starts = user_turn_starts(api)
	if not starts:
		print("no user turns")
		return 2
	t = turn if turn >= 0 else len(starts) - 1
	end = starts[t + 1] if t + 1 < len(starts) else len(api)
	prefix = api[:end]
	region_end = keep_tail_cut(prefix)
	graph = build_graph(prefix)

	all_user = [n for n in graph.nodes if n.kind == KIND_USER]
	in_region = [n for n in all_user if n.idx < region_end]
	passed = [n for n in in_region if _substantive(n.text)]

	norm = lambda s: " ".join((s or "").split())  # noqa: E731
	counter = Counter(norm(n.text) for n in passed)

	print(f"session={f.stem} msgs={len(prefix)} turns={len(starts)} turn={t}")
	print(f"region_end={region_end}")
	print(f"kind=USER 节点总数={len(all_user)}  区域内={len(in_region)}  过 _substantive={len(passed)}")
	print(f"去重后不同文本数={len(counter)}")
	print("")
	print("按出现次数降序（前 25）：")
	for text, c in counter.most_common(25):
		print(f"  x{c:<4} idx样例={[n.idx for n in passed if norm(n.text) == text][:4]}")
		print(f"        |{text[:150]}")
	print("")
	short = [(t, c) for t, c in counter.items() if len(t) <= 30]
	print(f"长度 ≤30 的不同文本 = {len(short)}，合计出现 {sum(c for _, c in short)} 次：")
	for text, c in sorted(short, key=lambda x: -x[1])[:30]:
		print(f"  x{c:<4} |{text}")
	return 0


if __name__ == "__main__":
	args = [a for a in sys.argv[1:] if not a.startswith("--")]
	sys.exit(main(args[0], int(args[1]) if len(args) > 1 else -1))
