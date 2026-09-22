"""零成本量"跨枪不重发到底省多少"：本地跑连续边界，不调任何厂商。

`probe_notice_carrier_live` 只能量到单枪快照（`last_x_sent` 存最新一枪），
跨枪重复无从对比。这里换成**用真实装配口在本地推进连续边界**：状态源是真的
（goal / multi-agent / 浏览器预览），边界顺序与生产一致（先落库上一轮登记的
留痕，再装配本轮），所以"值没变的维度重发几次"是可数的。两种模式对照：

- ``XEYO_T_NOW_DEDUP=off``：没有台账 ⇒ 每个边界把全部状态块重发一遍（旧世界）；
- ``on``：台账 + 整段聚合 ⇒ 只有内容变了才重发，且状态消失能把旧版撤走。

顺带把聚合的那笔代价也量出来：聚合下"一个维度变了"要重发整段，
逐维下只发变了那一维 —— 两个数都印出来，不替模型做决定也不替用户粉饰。

用法（在 ``python/`` 下）::

    py -3.11 -m scripts.probe_notice_ledger_saving
    py -3.11 -m scripts.probe_notice_ledger_saving --rounds 12
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prompt import inject_store  # noqa: E402
from prompt.notice_channel import (  # noqa: E402
	WORLD_STATE_KEY,
	notice_texts,
)
from prompt.pre_llm_inject import (  # noqa: E402
	InjectContext,
	run_pre_llm_inject,
)

#: 稳定的状态维度（整个会话内容不变）
_DIM_GOAL = "# Goal（background only）\n目标：给登录页加校验并补测试"
_DIM_MULTI = ""  # multi_agent_hint 由装配口自己渲染，这里只给开关
_DIM_PREVIEW_HEAD = "# 浏览器预览（background only）"
#: 会在中途变化的维度（模拟：目标推进 / 预览页换地址）
_GOAL_LATER = "# Goal（background only）\n目标：改成表单级校验，并补上 e2e"


def _preview_text(round_i: int) -> str:
	return f"{_DIM_PREVIEW_HEAD}\nurl: http://localhost:5173/login?step={round_i // 3}"


def _run(*, dedup_mode: str, rounds: int, per_dim: bool) -> dict[str, float]:
	"""推进 ``rounds`` 个边界，返回累计字节/条数。

	``per_dim=True`` 把聚合口关掉 ⇒ 每个状态维度各自成一条片段、各自记一条账，
	用来对照"整段一条"的形状开销（信封与来源声明每维度各付一次）。
	"""
	import prompt.pre_llm_inject as ppi
	from engine.t_now_notes import persist_pending
	from prompt.t_now_strategy import (
		STRATEGY_NOTICE_FRAGMENT,
		STRATEGY_SYSTEM_CHANNEL,
	)
	from session.message_store import MessageStore

	os.environ[inject_store.FLAG_ENV] = dedup_mode
	inject_store.get_store().clear()
	orig_aggregate = ppi._aggregate_state_sections
	if per_dim:
		ppi._aggregate_state_sections = lambda tagged: tagged  # type: ignore[assignment]
	store = MessageStore([])
	carrier = STRATEGY_NOTICE_FRAGMENT
	sent_carrier = STRATEGY_SYSTEM_CHANNEL if per_dim else carrier
	projected: list[dict] = [{"role": "user", "content": "开工"}]
	frag_bytes = 0
	frag_count = 0
	try:
		for i in range(rounds):
			ppi.browser_preview_block = lambda i=i: _preview_text(i)  # type: ignore[assignment]
			goal = _DIM_GOAL if i < rounds // 2 else _GOAL_LATER
			visible = frozenset(store.note_fingerprints())
			out = run_pre_llm_inject(
				projected,
				InjectContext(
					session_id="probe-ledger",
					cwd=str(Path(tempfile.gettempdir())),
					goal=goal,
					multi_agent=True,
					include_memory_index=False,
					visible_notes=visible,
				),
			)
			frags = notice_texts(out)
			frag_bytes += sum(len(t) for t in frags)
			frag_count += len(frags)
			persist_pending(store, session_id="probe-ledger", carrier=sent_carrier)
			# 模拟一个工具批次结束（下一边界的前提）
			projected = projected + [
				{
					"role": "assistant",
					"content": [{"type": "tool_use", "id": f"t{i}", "name": "Read"}],
				},
				{"role": "tool", "tool_call_id": f"t{i}", "content": "file bytes"},
			]
	finally:
		ppi._aggregate_state_sections = orig_aggregate  # type: ignore[assignment]
	st = inject_store.get_store().stats()
	os.environ.pop(inject_store.FLAG_ENV, None)
	return {
		"bytes": frag_bytes,
		"frags": frag_count,
		"hits": st["hits"],
		"misses": st["misses"],
		"notes": len([m for m in store.items if getattr(m, "note_key", "")]),
		"retracted": st["retracted"],
	}


def main(argv: list[str] | None = None) -> int:
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("--rounds", type=int, default=8)
	args = ap.parse_args(argv)

	# 状态维度名要能被聚合口认出来，先确认 WORLD_STATE_KEY 可用
	assert WORLD_STATE_KEY == "world_state"
	old = {}
	off = _run(dedup_mode=inject_store.MODE_OFF, rounds=args.rounds, per_dim=False)
	on = _run(dedup_mode=inject_store.MODE_ON, rounds=args.rounds, per_dim=False)
	per_dim = _run(dedup_mode=inject_store.MODE_ON, rounds=args.rounds, per_dim=True)
	print(f"边界数：{args.rounds}（中途目标变化 1 次、预览页换址 {args.rounds // 3 - 1} 次）")
	rows = (
		("无台账（每边界全重发）", off),
		("台账+整段聚合（默认档）", on),
		("台账+逐块留痕（对照形状）", per_dim),
	)
	print(f"{'口径':<28}{'注入字节':>10}{'片段条数':>10}{'跳过次数':>10}{'留痕条数':>10}")
	for label, r in rows:
		print(
			f"{label:<28}{int(r['bytes']):>10,}{int(r['frags']):>10}"
			f"{int(r['hits']):>10}{int(r['notes']):>10}"
		)
	saved = off["bytes"] - on["bytes"]
	pct = (saved / off["bytes"] * 100) if off["bytes"] else 0.0
	print(f"\n台账省下的注入字节：{saved:,}（{pct:.1f}%）；"
	      f"聚合 vs 逐块：{on['bytes']:,} vs {per_dim['bytes']:,}")
	print(f"撤回登记次数：{on['retracted']}（本夹具无状态消失，应为 0）")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
