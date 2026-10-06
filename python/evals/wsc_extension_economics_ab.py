"""零 API 的逐请求配对回放；输入/源码清单、容量压力与估算口径均落盘。

system/tools 历史快照缺失，使用明确标注的固定前缀敏感性场景，非真实厂商账单。
此台检查扩展经济门；初折统一在同一边界发生，不评估初折触发的优劣。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import time


def without_repeat_facts(messages: list[dict]) -> list[dict]:
	"""离线消融重复次数文本；保留相邻 TODO、目录规则及其他状态全文。"""
	import re
	from prompt.inject_store import fingerprint
	from prompt.notice_channel import _unwrap_notice, wrap_notice

	out = []
	previous = None
	for row in messages:
		if row.get("note_key") != "world_state" or not isinstance(row.get("content"), str):
			out.append(row)
			continue
		body = _unwrap_notice(row["content"])
		sections = re.split(r"\n(?=# )", body)
		body = "\n".join(s for s in sections if not s.startswith("# Repeat guard")).strip()
		if not body or body == previous:
			continue
		previous = body
		out.append({**row, "content": wrap_notice(body, key="world_state"), "note_fp": fingerprint(body)})
	return out


def canonical_projection(messages: list[dict], message_format: str) -> str:
	"""选用生产序列化形状；internal 只供历史实验口径对照。"""
	if message_format == "openai":
		from model._openai_common import normalize_messages_for_openai

		# 历史图片可能已清理；文本回放保留相同身份，不能按 base64 长度计视觉 token。
		# 不读/改媒体文件，不调用网络。manifest 明示视觉成本未计。
		image_safe = []
		for row in messages:
			content = row.get("content")
			if isinstance(content, list):
				blocks = []
				for block in content:
					if isinstance(block, dict) and block.get("type") == "image_url":
						url = str((block.get("image_url") or {}).get("url") or "")
						block = {**block, "image_url": {"url": "offline-media://" + hashlib.sha256(url.encode()).hexdigest()}}
					blocks.append(block)
				row = {**row, "content": blocks}
			image_safe.append(row)
		messages = image_safe
		messages = normalize_messages_for_openai(messages, provider="deepseek", model="deepseek-v4-flash")
	return json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--arm", choices=("off", "proxy", "projected", "marginal"), required=True)
	parser.add_argument("--output", type=Path, required=True)
	parser.add_argument("--case", type=int, default=-1)
	parser.add_argument("--window", type=int, default=128_000)
	parser.add_argument("--prefix-tokens", type=int, default=8192)
	parser.add_argument("--message-format", choices=("internal", "openai"), default="internal")
	parser.add_argument("--gap-cap", type=int, default=0)
	parser.add_argument("--min-interval", type=int, default=0)
	parser.add_argument("--head-layout", choices=("journal", "snapshot", "bounded"), default="journal")
	parser.add_argument("--hydrate-history", action="store_true")
	parser.add_argument("--drop-repeat-facts", action="store_true")
	parser.add_argument("--state-layout", choices=("historical", "tail", "stable-equal", "visible-equal", "store-equal", "store-current", "lifecycle-current", "lifecycle-equal"), default="historical")
	parser.add_argument("--state-persist", choices=("late", "early", "native-early"), default="late")
	parser.add_argument("--state-dedup", choices=("ledger", "visible"), default="ledger")
	parser.add_argument("--state-storage", choices=("history", "detached", "changing", "append"), default="history")
	parser.add_argument("--state-switch-at", type=int, default=-1)
	parser.add_argument("--switch-on-source-change", action="store_true")
	parser.add_argument("--transition-control", action="store_true")
	parser.add_argument("--keep-ledger-on-transition", action="store_true")
	parser.add_argument("--soft-watermark", type=int, default=0)
	parser.add_argument("--native-source", action="store_true")
	parser.add_argument("--audit-source", action="store_true")
	parser.add_argument("--audit-recent-prefix", action="store_true")
	parser.add_argument("--ordinary-gate", action="store_true")
	args = parser.parse_args()
	if args.audit_recent_prefix and not args.audit_source:
		parser.error("recent prefix audit requires source audit")
	if args.state_persist == "native-early" and not args.native_source:
		parser.error("native-early persistence requires native source")
	if args.ordinary_gate and not args.native_source:
		parser.error("ordinary gate requires native source")
	if args.switch_on_source_change and args.state_switch_at >= 0:
		parser.error("choose source-change transition or fixed switch point")
	deferred_switch = args.state_switch_at >= 0 or args.switch_on_source_change
	if args.native_source and (not args.switch_on_source_change or args.state_storage != "append" or args.state_layout != "lifecycle-current" or args.transition_control):
		parser.error("native source requires conditional append lifecycle-current without transition control")
	root = Path(__file__).resolve().parents[2]
	harness = runpy.run_path(str(root / "_wsc_out" / "_fold_veto_ab.py"))
	# 每臂一进程；清掉继承的策略覆盖值。
	for key in ("XEYO_C2_GAP_CAP", "XEYO_C2_MARGIN", "XEYO_C2_PRICE_RATIO",
	            "XEYO_WSC_FOLD_MIN_INTERVAL", "XEYO_C2_SAVE_RATIO"):
		os.environ.pop(key, None)
	os.environ.update(
		XEYO_WSC_EXTENSION_ECONOMICS="1" if args.arm in ("projected", "marginal") else "0",
		XEYO_WSC_FOLD_COOLDOWN_VETO="0" if args.arm == "off" else "1", XEYO_WSC_OFFLINE="1",
		XEYO_WSC_HEAD_STORE="0",
		XEYO_WSC_SOFT_WATERMARK=str(max(0, args.soft_watermark)),
	)
	if args.gap_cap > 0:
		os.environ["XEYO_C2_GAP_CAP"] = str(args.gap_cap)
	if args.min_interval > 0:
		os.environ["XEYO_WSC_FOLD_MIN_INTERVAL"] = str(args.min_interval)
	from memory import wsc_extension_economics as economics
	from memory import wsc_projection as wp
	from memory.runtime import c2_cut_index, try_extend_c2
	from memory import wsc_watermark
	from memory.simulator.params import load_params
	from synaptic.textutil import node_token_len
	from evals.wsc_prefix_accounting import estimate, leading_assistant_outputs
	from evals import wsc_marginal_economics as marginal
	comparison_context = {"previous": None, "response": None}
	if args.arm == "marginal":
		original_compare = economics.compare
		def marginal_compare(keep, fold):
			if comparison_context["previous"] is None:
				return original_compare(keep, fold)
			prefix = "S" * (4 * args.prefix_tokens)
			return marginal.compare(prefix + canonical_projection(keep, args.message_format),
			                        prefix + canonical_projection(fold, args.message_format),
			                        previous=comparison_context["previous"],
			                        response_prefix=comparison_context["response"])
		economics.compare = marginal_compare
	if args.state_layout == "historical":
		# 仅离线旧版对照：保留旧位置、旧 API 身份形状。
		from session import message_store
		from session.state_projection import current_context_items

		def historical_items(items, *, include_system_notes):
			selected = {id(item) for item in current_context_items(items, include_system_notes=include_system_notes)}
			return [item for item in items if id(item) in selected]

		message_store.current_context_items = historical_items
	elif args.state_layout in ("store-equal", "store-current", "lifecycle-current", "lifecycle-equal"):
		pass  # Exercise the persistent MessageStore admission path below.
	elif args.state_layout == "visible-equal":
		from session import message_store
		from evals.wsc_equal_state import VisibleEqualState

		state_selector = VisibleEqualState()
		message_store.current_context_items = state_selector.select
		original_emit = wp._emit

		def observe_tail(head, messages, base, frozen_attr, **kwargs):
			out = original_emit(head, messages, base, frozen_attr, **kwargs)
			state_selector.record_tail(base)
			return out

		wp._emit = observe_tail
	elif args.state_layout == "stable-equal":
		from session import message_store
		from evals.wsc_equal_state import equal_state_items

		message_store.current_context_items = equal_state_items
	else:
		# 被否决的尾部布局只留在离线对照，生产不新增布局开关。
		from session import message_store
		from session.state_projection import current_context_items
		from memory import runtime

		def tail_items(items, *, include_system_notes):
			selected = current_context_items(items, include_system_notes=include_system_notes)
			return [item for item in selected if not item.note_key] + sorted(
				(item for item in selected if item.note_key), key=lambda item: item.note_key
			)

		def note_start(messages):
			return next((i for i, row in enumerate(messages) if row.get("note_key")), len(messages))

		original_cut = c2_cut_index
		c2_cut_index = runtime.c2_cut_index = lambda messages, s0: min(original_cut(messages, s0), note_start(messages))
		original_boundary = economics.absorb_boundary
		economics.absorb_boundary = lambda messages, cursor: min(original_boundary(messages, cursor), note_start(messages))
		message_store.current_context_items = tail_items
	if args.head_layout != "journal":
		from dataclasses import replace

		production_params = wp.production_params
		wp.production_params = lambda: replace(production_params(), journal_layout=args.head_layout != "snapshot",
		                                     journal_rebase=args.head_layout == "bounded")
	shadow_hooks = None
	if args.state_storage == "append":
		if args.state_layout != "lifecycle-current" or not args.hydrate_history:
			parser.error("append source requires hydrated lifecycle-current replay")
		from evals.wsc_append_state import install_note_exclusion
		if not deferred_switch and not args.native_source:
			shadow_hooks = install_note_exclusion()
	elif deferred_switch:
		parser.error("state switch requires append source")
	if args.transition_control and not deferred_switch:
		parser.error("transition control requires a switch point")

	args.output.parent.mkdir(parents=True, exist_ok=True)
	# 所有旁路产物隔离；原始会话在设置 XEYO_HOME 前由 harness 读取。
	indices = [args.case] if args.case >= 0 else range(len(harness["CASES"]))
	cases = [(harness["CASES"][i][0], harness["load_case"](harness["CASES"][i][1])) for i in indices]
	os.environ["XEYO_HOME"] = str(args.output.parent / "extension-replay-home")
	os.environ["XEYO_USAGE_DIR"] = str(args.output.parent / "extension-replay-usage")
	# 不同候选各有独立落地目录；Read 引用仍按相同相对路径长度渲染。
	replay_cwd = str(args.output.parent / "extension-replay-workspace" / args.output.stem)
	sources = ("evals/wsc_extension_economics_ab.py", "memory/runtime.py", "memory/wsc_extension_economics.py", "memory/wsc_projection.py",
	           "memory/fold_cadence_veto.py", "synaptic/project.py", "synaptic/coldstore.py", "synaptic/cadence.py",
	           "model/_openai_common.py", "engine/compact.py", "memory/offload.py")
	sources += ("synaptic/types.py", "synaptic/assemble.py", "synaptic/journal_rollover.py")
	sources += ("session/message_store.py", "session/hydrate.py")
	sources += ("session/state_projection.py",)
	sources += ("evals/wsc_prefix_accounting.py",)
	sources += ("evals/wsc_marginal_economics.py",)
	sources += ("evals/wsc_equal_state.py",)
	sources += ("evals/wsc_state_reuse.py",)
	sources += ("evals/wsc_state_lifecycle.py",)
	sources += ("evals/wsc_ordinary_gate.py",)
	sources += ("evals/wsc_recent_prefixes.py",)
	sources += ("evals/wsc_append_state.py",)
	sources += ("evals/wsc_source_transition.py",)
	sources += ("memory/wsc_source_transition.py", "session/compression_source.py", "prompt/state_emission.py", "memory/wsc_source_layout.py", "memory/wsc_head_store.py", "memory/working.py", "synaptic/state_source.py")
	sources += ("memory/wsc_source_policy.py", "memory/memory_switches.py", "evals/wsc_source_audit.py")
	sources += ("evals/wsc_wire_difference.py",)
	manifest = {
		"arm": args.arm, "window_tokens": args.window, "fixed_prefix_tokens": args.prefix_tokens,
		"cooldown_veto": args.arm != "off", "projected_gate": args.arm in ("projected", "marginal"),
		"marginal_transition": args.arm == "marginal",
		"message_format": args.message_format, "gap_cap_override": args.gap_cap,
		"min_interval_override": args.min_interval,
		"soft_watermark_override": args.soft_watermark,
		"cache_scenarios": "input-only LCP and optimistic previous-response prefix; neither is provider usage; primary hit/miss remain input-only",
		"head_layout": args.head_layout,
		"hydrate_history": args.hydrate_history,
		"drop_repeat_facts": args.drop_repeat_facts,
		"state_layout": args.state_layout,
		"state_persist": args.state_persist,
		"state_dedup": args.state_dedup,
		"state_storage": args.state_storage,
		"native_source": args.native_source,
		"audit_source": args.audit_source,
		"audit_recent_prefix": args.audit_recent_prefix,
		"ordinary_gate": args.ordinary_gate,
		"native_scope": "Source reader, conditional reset, graph exclusion, seals and state selection are native; archived state generation and persistence remain simulated" if args.native_source else None,
		"state_switch_at": args.state_switch_at,
		"switch_on_source_change": args.switch_on_source_change,
		"transition_target": "history" if args.transition_control else "append",
		"keep_ledger_on_transition": args.keep_ledger_on_transition,
		"state_oracle": "archived state snapshots, reinjection and persistence simulated" if args.state_layout.startswith("lifecycle-") else None,
		"image_accounting": "stable reference only; vision token cost excluded; no media materialization",
		"token_counter": "UTF8 bytes/4 estimate", "prices": "input only: hit=0.05 miss=1.5 CNY/M",
		"source_sha256": {s: hashlib.sha256((root / "python" / s).read_bytes()).hexdigest() for s in sources},
		"harness_sha256": hashlib.sha256((root / "_wsc_out" / "_fold_veto_ab.py").read_bytes()).hexdigest(),
		"inputs": {name: hashlib.sha256(json.dumps(msgs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
		           for name, msgs in cases},
		"params": str(load_params()), "scope": "paired extension replay; fixed prefix scenario; no API",
	}
	args.output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
	point_path = args.output.with_suffix(".points.jsonl")
	with args.output.open("w", encoding="utf-8") as summary, point_path.open("w", encoding="utf-8") as points:
		for name, messages in cases:
			if deferred_switch and shadow_hooks is not None:
				shadow_hooks.close()
				shadow_hooks = None
			lifecycle = None
			if args.state_layout.startswith("lifecycle-"):
				from evals.wsc_state_lifecycle import StateLifecycle
				lifecycle = StateLifecycle(reuse_equal_state=args.state_layout == "lifecycle-equal", persist=args.state_persist, dedup=args.state_dedup, storage="history" if deferred_switch else args.state_storage)
			if args.state_layout in ("store-equal", "store-current"):
				from evals.wsc_state_reuse import StateReuseStore
				persistent_store = StateReuseStore(reuse_equal_state=args.state_layout == "store-equal")
				store_end = 0
			if args.state_layout == "visible-equal":
				state_selector.ordered = []
				state_selector.visible = set()
				state_selector.checked = state_selector.reused = 0
			wp._STATE.clear()
			wsc_watermark._STATE.clear()
			w = harness["Work"]()
			if args.native_source:
				from memory.wsc_source_layout import LEGACY
				w.compression_source_layout = LEGACY
				w.compression_source_transition_enabled = True
				lifecycle.native_working = w
			# 两臂同时运行也不共写视图，单字母标识保持引用长度完全相同。
			w.session_id = "extension_ab_" + {"off": "o", "proxy": "a", "projected": "b", "marginal": "c"}[args.arm] + hashlib.sha256(name.encode()).hexdigest()[:12]
			params = load_params()
			previous = None
			previous_projection = None
			previous_wire = None
			previous_wire_states = set()
			if args.audit_recent_prefix:
				from evals.wsc_recent_prefixes import RecentPrefixes
				recent_prefixes = RecentPrefixes(32)
			previous_end = 0
			totals = dict(shots=0, folds=0, forced=0, prompt=0, hit=0, miss=0, peak=0, over_window=0,
			              measured=0, measurement_unavailable=0, response_prefix_hit=0, response_prefix_miss=0)
			started = time.perf_counter()
			source_switched = False
			for shot, end in enumerate(harness["shot_marks"](messages, 24)):
				transition = False
				if shot == args.state_switch_at:
					from evals.wsc_source_transition import transition_to_append, rebase_compression
					if args.transition_control:
						rebase_compression(w)
						transition = True
					else:
						transition = transition_to_append(lifecycle, w)
					# The eval head store is explicitly disabled. Discard in-memory
					# legacy heads too; resume_inputs forks existing cold files.
					wp._STATE.clear()
					if not args.transition_control:
						shadow_hooks = install_note_exclusion()
				history = messages[:end]
				if args.drop_repeat_facts:
					history = without_repeat_facts(history)
				if args.hydrate_history:
					from session.hydrate import message_from_row
					from session.message_store import MessageStore

					if lifecycle is not None:
						history = lifecycle.prepare(history)
					elif args.state_layout in ("store-equal", "store-current"):
						persistent_store.note_fingerprints(projected=previous_projection or [])
						for row in history[store_end:]:
							if (msg := message_from_row(row)) is not None:
								persistent_store.append(msg)
						store_end = len(history)
						history = persistent_store.as_api_messages()
						from session.state_projection import current_context_items
						latest = current_context_items(persistent_store.items, include_system_notes=True)
						def state_facts(items):
							return {m.note_key: (m.role, m.content, m.note_fp, m.note_kind) for m in items if m.note_key}
						if state_facts(persistent_store._api_items) != state_facts(latest):
							raise AssertionError("store reuse changed authoritative state")
						if [m for m in persistent_store._api_items if not m.note_key] != [m for m in latest if not m.note_key]:
							raise AssertionError("store reuse changed non-state history")
					else:
						history = MessageStore([msg for row in history if (msg := message_from_row(row)) is not None]).as_api_messages()
					# Keep note metadata for actual-emission visibility; provider
					# serialization removes it before accounting.
				if args.switch_on_source_change and not source_switched:
					if args.native_source:
						from memory.wsc_source_transition import prepare_compression_source
						from session.compression_source import compression_messages
						transition = prepare_compression_source(lifecycle.store, w, cwd=replay_cwd, fold=False)
						if transition:
							lifecycle.storage = "append"
							history = compression_messages(lifecycle.store, w)
							source_switched = True
					else:
						from evals.wsc_source_transition import invalid_frozen_source, transition_to_append, rebase_compression
						cached = wp._STATE.get(wp._state_key(w.session_id, replay_cwd))
						if invalid_frozen_source(cached, history):
							if args.transition_control:
								rebase_compression(w)
							else:
								transition_to_append(lifecycle, w)
								history = lifecycle.store.as_api_messages()
								shadow_hooks = install_note_exclusion()
							wp._STATE.clear()
							transition = source_switched = True
				cut = min(len(history), max(int(c2_cut_index(history, None)), 1))
				source_audit = None
				if args.audit_source:
					from evals.wsc_source_audit import audit_source
					source_audit = audit_source(history, int(w.compact_cursor or 0))
				generated = leading_assistant_outputs(messages[:end], previous_end)
				response_prefix = (
					"S" * (4 * args.prefix_tokens) + canonical_projection(previous_projection + generated, args.message_format)
					if previous_projection is not None and generated else None
				)
				comparison_context.update(previous=previous, response=response_prefix)
				account = {}
				fold = False
				if cut > w.compact_cursor:
					if w.compact_cursor == 0:
						w.compact_cursor = w.c1_frozen_until = cut
						w.turns_since_c2 = 0
						fold = True
					else:
						from evals.wsc_ordinary_gate import ordinary_gate
						with ordinary_gate(w, args.ordinary_gate):
							fold = try_extend_c2(w, history, cut, params, account=account, cwd=replay_cwd)
				out = wp.project_c2_messages(history, w, cwd=replay_cwd)
				if out is None:
					raise RuntimeError(f"empty projection: {name} shot={shot}")
				projected_base = out
				if lifecycle is not None:
					out = lifecycle.preview(projected_base)
				# 真实完整前缀未知；显式加入相同固定前缀并检查容量，不能伪称真实请求装配。
				body = "S" * (4 * args.prefix_tokens) + canonical_projection(out, args.message_format)
				prompt = node_token_len(body)
				forced = False
				if prompt + params.reserve_tokens > args.window and cut > w.compact_cursor:
					forced = try_extend_c2(w, history, cut, params, force=True, cwd=replay_cwd)
					if forced:
						out = wp.project_c2_messages(history, w, cwd=replay_cwd)
						projected_base = out
						if lifecycle is not None:
							out = lifecycle.preview(projected_base)
						body = "S" * (4 * args.prefix_tokens) + canonical_projection(out, args.message_format)
						prompt = node_token_len(body)
				if lifecycle is not None:
					out = lifecycle.finish(projected_base, fold=bool(fold or forced) and not (transition and args.keep_ledger_on_transition))
				if source_audit is not None:
					from evals.wsc_wire_difference import first_difference, state_identities
					wire = json.loads(body[4 * args.prefix_tokens:])
					states = state_identities(out)
					source_audit["wire_difference"] = first_difference(previous_wire, wire, previous_wire_states, states)
					previous_wire, previous_wire_states = wire, states
				cache = estimate(body, previous=previous, response_prefix=response_prefix)
				if args.audit_recent_prefix:
					source_audit["recent_prefix"] = recent_prefixes.observe(body)
					assert source_audit["recent_prefix"]["latest_input_hit"] == cache.input_hit
				hit, miss = cache.input_hit, cache.input_miss
				previous = body
				previous_projection, previous_end = out, end
				w.turns_since_c2 += 1
				w.last_prompt_tokens = prompt
				row = dict(case=name, shot=shot, end=end, fold=bool(fold or forced), forced=forced,
				           prompt=prompt, hit=hit, miss=miss, reason=account.get("reason"),
				           economics_basis=account.get("economics_basis"),
				           measurement=account.get("economics_measurement"),
				           gap_next=account.get("gap_next"))
				if deferred_switch:
					row.update(source_transition=transition)
				if source_audit is not None:
					live = wp._STATE.get(wp._state_key(w.session_id, replay_cwd))
					source_audit["fold_gate"] = {key: account[key] for key in (
						"region_tokens", "head_tokens", "tail_tokens", "saved_net", "transition",
						"payback_shots", "gap_shots", "prompt_tokens", "hit_gap_required",
						"hit_gap_capped", "turns_since_c2") if key in account}
					source_audit.update(
						head_sha256=hashlib.sha256(live.head.encode("utf-8")).hexdigest() if live is not None else None,
						region_end=live.region_end if live is not None else None,
					)
					row.update(source_audit=source_audit)
				row.update(response_prefix_hit=cache.response_hit, response_prefix_miss=cache.response_miss,
				           response_prefix_available=response_prefix is not None,
				           incremental_miss_input=account.get("incremental_miss_input"),
				           incremental_miss_response=account.get("incremental_miss_response"))
				if lifecycle is not None:
					row.update(detached_state_keys=sorted(lifecycle.detached_keys))
				points.write(json.dumps(row) + "\n")
				totals["shots"] += 1
				totals["folds"] += int(fold or forced)
				totals["forced"] += int(forced)
				for key, value in (("prompt", prompt), ("hit", hit), ("miss", miss)):
					totals[key] += value
				totals["response_prefix_hit"] += cache.response_hit
				totals["response_prefix_miss"] += cache.response_miss
				totals["peak"] = max(totals["peak"], prompt)
				totals["over_window"] += int(prompt + params.reserve_tokens > args.window)
				totals["measured"] += int(account.get("economics_basis") in (economics.BASIS, marginal.BASIS))
				totals["measurement_unavailable"] += int(account.get("economics_measurement") == "unavailable")
			result = dict(arm=args.arm, case=name, **totals,
			              input_cost_estimate=(totals["hit"] * 0.05 + totals["miss"] * 1.5) / 1e6,
			              response_prefix_cost_estimate=(totals["response_prefix_hit"] * 0.05 + totals["response_prefix_miss"] * 1.5) / 1e6,
			              wall_seconds=round(time.perf_counter() - started, 3))
			if args.state_layout == "visible-equal":
				result.update(state_quality_checks=state_selector.checked,
				              equal_state_reuses=state_selector.reused)
			elif args.state_layout in ("store-equal", "store-current"):
				result.update(state_quality_checks=totals["shots"])
			elif lifecycle is not None:
				result.update(state_quality_checks=lifecycle.shots, state_injections=lifecycle.injected,
				              stale_state_rows=lifecycle.stale_visible)
			summary.write(json.dumps(result) + "\n")
			summary.flush()
			print(json.dumps(result), flush=True)
	if shadow_hooks is not None:
		shadow_hooks.close()


if __name__ == "__main__":
	main()
