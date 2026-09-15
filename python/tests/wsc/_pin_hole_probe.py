"""只读探针：区域内用户原话还有几条被渲染进热层？（规则 1 的信息空洞判定）

背景：`assemble.py::render_main` **跳过 `pin_nodes`**，而 `seeds.py` 把**全部**实质用户
节点放进 `pin_nodes`。在 `task_updates`（原「指令」段）存在时，它是这些原话唯一的渲染
通道；规则 1 删掉它之后，除首条（渲染成「目标:」）外，其余用户原话在热层里彻底不可见，
而且因为是 pin ⇒ 不会被剪 ⇒ **连 expand 句柄都没有 ⇒ 不可恢复**。

实测（修复后，199 回合会话末轮）：区域内用户节点 188 条，`[REQUESTS]` 渲染 187 行
+ 「目标」pin 1 行 = **188/188 全覆盖**，句柄往返无损 187/187。

本探针就是这个缺陷的**外部审计量**：区域内实质用户消息数 vs 其中能在热层里找到的条数，
外加「有句柄 / 句柄往返无损」的验证。

⚠️ **两个口径别混（踩过，造成一次误报）**：
`harvest_needles` 的 ``needles["user"]`` 做 ``dict.fromkeys`` **去重**后才 17 条，
而节点级计数是 188 条。拿 17 去对 187 会得出「在导出工具结果当用户原话」的错误结论。
本仓库 ``sess_real_200turn_c2.jsonl`` 是同一组 17 条提问重复 11 轮的合成长会话
（1385 行 = 200 user + 605 assistant + 580 tool，**无**伪用户消息），188 才是真值。

用法：
    ./.venv/Scripts/python.exe tests/wsc/_pin_hole_probe.py <session.jsonl> [turn] [--no-journal] [--no-requests]

``--no-requests`` 把 ``[REQUESTS]`` 通道关掉（monkeypatch），用于复现「修前」状态做同口径前后对比。

零花费、只读，不改任何状态。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def _repo_root() -> Path:
	# .../python/tests/wsc/_pin_hole_probe.py -> 仓库根
	return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
if str(ROOT / "python") not in sys.path:
	sys.path.insert(0, str(ROOT / "python"))

from engine.compact import keep_tail_cut  # noqa: E402
from synaptic.project import default_params, project  # noqa: E402
from synaptic.replay import _as_api_message, load_jsonl, user_turn_starts  # noqa: E402
from synaptic.seeds import collect_seeds, harvest_needles  # noqa: E402
from synaptic.types import KIND_USER, WscParams  # noqa: E402

_REQ_LINE = re.compile(r"^\[REQUESTS\] #(\d+) ")
_HANDLE = re.compile(r"expand\((node://[0-9,]+)\)")


def main(path: str, turn: int = -1, *, journal: bool = True, requests: bool = True) -> int:
	f = Path(path)
	if not f.is_file():
		print(f"no such session: {f}")
		return 2

	if not requests:
		# 复现「修前」状态：把 [REQUESTS] 通道整体摘掉（只影响本进程）。
		import synaptic.assemble as _asm

		_asm.render_requests = lambda *a, **k: []  # type: ignore[assignment]

	api = [_as_api_message(r) for r in load_jsonl(f)]
	starts = user_turn_starts(api)
	if not starts:
		print("no user turns")
		return 2
	t = turn if turn >= 0 else len(starts) - 1
	end = starts[t + 1] if t + 1 < len(starts) else len(api)
	prefix = api[:end]
	region_end = keep_tail_cut(prefix)

	p: WscParams = default_params("Medium+", "closure")
	if not journal:
		from dataclasses import replace

		p = replace(p, journal_layout=False)
	proj = project(prefix, region_end=region_end, params=p, session=f.stem)
	hot = proj.text
	file_states = {s.path: s for s in proj.result.hot.file_states}

	seeds = collect_seeds(proj.graph, prefix, file_states)
	# 分母用 seeds.user_nodes（_substantive 过滤后的实质人类消息），与 [REQUESTS] 的输入同源。
	# **不要**按 kind == KIND_USER 数——本会话 kind=USER 有 200 个，过 _substantive 后 188 个。
	sub_users = [n for n in proj.graph.nodes if n.idx < region_end and n.idx in set(seeds.user_nodes)]

	needles = harvest_needles(proj.graph, file_states, region_end=region_end)
	user_needles = list(needles["user"])
	present = [s for s in user_needles if s in hot]
	missing = [s for s in user_needles if s not in hot]

	pinned = [n.idx for n in sub_users if n.idx in set(seeds.pin_nodes)]

	# [REQUESTS] 通道审计：行数 / 句柄完整性 / 句柄往返无损。
	# R4 去重模式把同文本节点合并成 node://i,j,...；必须逐节点核对，不能只看首 idx。
	req_lines = 0
	handled = 0
	broken: list[int] = []
	for line in hot.splitlines():
		if not _REQ_LINE.match(line):
			continue
		req_lines += 1
		hm = _HANDLE.search(line)
		if not hm:
			broken.append(-1)
			continue
		handle = hm.group(1)
		idxs = [int(x) for x in handle[len("node://") :].split(",") if x]
		try:
			got = tuple(proj.cold.expand(handle))
		except KeyError:
			broken.extend(idxs)
			continue
		want = tuple(
			proj.graph.node(i).text
			for i in idxs
			if proj.graph.node(i) is not None
		)
		if got == want:
			handled += len(idxs)
		else:
			broken.extend(idxs)

	print(f"session={f.stem} msgs={len(prefix)} turns={len(starts)} turn={t}")
	print(f"journal_layout={journal}  requests_channel={requests}")
	print(f"region_end={region_end}  尾部不受压缩的消息数={len(prefix) - region_end}")
	print(
		f"区域内用户节点（节点级，seeds.user_nodes）={len(sub_users)}  "
		f"去重后唯一文本（harvest_needles）={len(user_needles)}  "
		f"其中热层可见={len(present)} 不可见={len(missing)}"
	)
	print(f"[REQUESTS] 行数={req_lines}  句柄往返无损={handled}  句柄异常={len(broken)} {broken[:8]}")
	# 双通道合并计数：首个用户节点走「目标」pin，不占 [REQUESTS] 行。
	by_channel = handled + (1 if sub_users and sub_users[0].idx == seeds.pin_nodes[0] and "目标:" in hot else 0)
	print(f"节点级渲染覆盖 = {by_channel}/{max(1, len(sub_users))}（[REQUESTS] {handled} + 目标 pin）")
	print(f"其中属于 pin_nodes 的={len(pinned)}（pin ⇒ 不剪 ⇒ 无 expand 句柄——所以必须有显式通道）")
	print(f"热层含「目标:」行={'目标:' in hot}  含「指令:」行={'指令:' in hot}")
	print(f"热层 token={proj.result.hot.tokens}  字符={len(hot)}")
	print("不可见的用户原话（前 60 字）：")
	for i, s in enumerate(missing[:20]):
		print(f"  [{i}] {s[:60]}")
	return 0


if __name__ == "__main__":
	args = [a for a in sys.argv[1:] if not a.startswith("--")]
	no_journal = "--no-journal" in sys.argv
	sys.exit(
		main(
			args[0],
			int(args[1]) if len(args) > 1 else -1,
			journal=not no_journal,
			requests="--no-requests" not in sys.argv,
		)
	)
