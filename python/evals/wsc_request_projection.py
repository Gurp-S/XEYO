"""Compare request projection to state contracts using real offline transcripts."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from dataclasses import asdict
import difflib
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.stale_goal_ab import fingerprints, tool_read
from memory.wsc_projection import production_params
from synaptic.project import project
from synaptic.contracts import verify_object
from synaptic.coldstore import node_handle


#: 会话运行时产物：引擎每轮自行写入，与被测投影无关（`engine/turn_snapshot.py` 写
#: `*.turn.json`；`*.working.json` / `*.blobs` 同类）。把它们算进"受保护旧产物"，
#: 本 eval 在自己所属的活动会话里跑就必然红 —— 实测 2026-10-08 03:33（sess_mux0q86a_ea2kv9）：
#: 唯一变化文件就是 `sess_*.turn.json`（mtime 落在 eval 窗口内）。
_RUNTIME_ARTIFACTS = (".turn.json", ".working.json", ".blobs")


def protected_paths(source, home):
    sid = source.stem
    siblings = [p for p in source.parent.glob(sid + ".*") if not p.name.endswith(_RUNTIME_ARTIFACTS)]
    return [source, *siblings, *(home / "wsc_head").glob(sid + "*"),
            *(Path.cwd() / ".xeyo_offload" / "wsc").glob(sid + "*")]


def source_prefix_intact(before_bytes, path):
    """源只允许**尾部追加**：既有字节不得被改写。

    追加是会话增长的合法形态，不是恢复失败；把"文件变了"一律判失败，会在活动会话里
    把合法的同时增长记成假红，进而掩盖真红。
    """
    data = Path(path).read_bytes()
    return len(data) >= len(before_bytes) and data[:len(before_bytes)] == before_bytes


def state_fact_present(messages):
    """发射里是否含目标状态事实（`memory/wsc_goal_events.py::augment` 织入的 `[BOUND_GOAL_STATE]`）。"""
    if not messages:
        return False
    return any("[BOUND_GOAL_STATE]" in json.dumps(message, ensure_ascii=False) for message in messages)


def freeze_replay(rows, output, sid):
    """Replay real rows through the live adapter at operator-selected fold boundaries."""
    from types import SimpleNamespace
    from unittest.mock import patch
    from memory import wsc_projection as live, wsc_head_store as store
    prior = dict(live._STATE)
    working = SimpleNamespace(session_id=sid + "-offline", compact_cursor=66, c1_frozen_until=66)
    output.mkdir(parents=True, exist_ok=True)
    try:
        with arm("1", output / "home"), patch.object(live, "live_enabled", return_value=True), \
             patch.object(live, "freeze_enabled", return_value=True), patch.object(store, "enabled", return_value=True), \
             patch("memory.wsc_extension_economics.absorb_boundary", side_effect=lambda messages, cursor: cursor):
            first = live.project_c2_messages(rows[:66], working, cwd=str(output))
            tail = live.project_c2_messages(rows[:67], working, cwd=str(output))
            working.compact_cursor = working.c1_frozen_until = 67
            folded = live.project_c2_messages(rows[:67], working, cwd=str(output))
            next_round = live.project_c2_messages(rows[:68], working, cwd=str(output))
            live._STATE.clear()
            restart = live.project_c2_messages(rows[:68], working, cwd=str(output))
            stages = {"before_request": first, "request_in_tail": tail, "after_fold": folded,
                      "next_round": next_round, "restart": restart}
            for name, messages in stages.items():
                if messages is None:
                    raise ValueError("offline_adapter_no_projection: " + name)
                (output / (name + ".json")).write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")
            return {"scope": "real transcript; operator-selected fold boundaries; no model calls",
                    "request_in_tail_head_identical": first[0] == tail[0],
                    "one_request_fold_changes_head": first[0] != folded[0],
                    "next_round_head_identical": folded[0] == next_round[0],
                    "restart_emission_identical": next_round == restart,
                    "bound_state_fold_check": "not_exercised_unbound_session"}
    finally:
        live._STATE.clear()
        live._STATE.update(prior)


@contextmanager
def arm(value, home):
    values = {"XEYO_WSC_REQUEST_PROJECTION": value, "XEYO_WSC_STATE_CONTRACTS": "1", "XEYO_STALE_GOAL_RETIRE": "0",
              "XEYO_EXECUTION_FACT_CONTRACTS": "1", "XEYO_WSC_OFFLINE": "1", "XEYO_HOME": str(home)}
    old = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def head_goal(projection):
    return next((pin.text for pin in projection.result.hot.pins if pin.key == "goal"), "")


def evaluate(source, output, cuts):
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    sid = source.stem
    home = source.parent.parent
    protected = protected_paths(source, home)
    before = fingerprints(protected)
    before_source = source.read_bytes()
    params = production_params()
    report = {"schema_version": 1, "source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "rows": len(rows), "params": asdict(params), "scope": "offline reconstruction; no model requests",
              "arm_switches": {label: {"XEYO_WSC_REQUEST_PROJECTION": value,
                  "XEYO_WSC_STATE_CONTRACTS": "1", "XEYO_EXECUTION_FACT_CONTRACTS": "1",
                  "XEYO_STALE_GOAL_RETIRE": "0"} for label, value in (("before", "0"), ("after", "1"))},
              "arms": {}, "comparisons": []}
    results = {}
    for label, value in (("before", "0"), ("after", "1")):
        snapshots = []
        with arm(value, output / label / "home"):
            for cut in cuts:
                folder = output / label / str(cut)
                folder.mkdir(parents=True, exist_ok=True)
                projection = project(rows[:cut], region_end=cut, params=params, session=sid,
                                     view_path=folder / "cold.txt")
                results[label, cut] = projection
                text, ranges = projection.cold.render_text_view()
                view = Path(projection.view_path).read_text(encoding="utf-8")
                recovery = []
                for index, original in projection.cold.texts.items():
                    handle = node_handle(index)
                    start, end = ranges[handle]
                    actual = "\n".join(view.split("\n")[start - 1:end])
                    reference = handle if handle in projection.cold.handles else next(
                        (h for h, nodes in projection.cold.handles.items() if index in nodes), None)
                    recovered = reference is not None and projection.cold.expand(reference)[projection.cold.handles[reference].index(index)] == original
                    recovery.append(actual == original.replace("\r\n", "\n").replace("\r", "\n") and recovered)
                indices = list(dict.fromkeys([0, 66, *projection.seeds.user_nodes[-2:], *[i for i in projection.cold.texts if projection.graph.node(i).is_error][:3],
                                             *list(projection.cold.texts)[-2:]]))
                reads = []
                for index in indices:
                    if index not in projection.cold.texts:
                        continue
                    start, end = ranges[node_handle(index)]
                    reference = {"file_path": str(Path(projection.view_path).resolve()), "offset": start,
                                 "limit": min(10, end - start + 1)}
                    receipt = tool_read(reference, output)
                    reads.append({"node": index, "reference": reference,
                                  "is_error": receipt["is_error"], "content": receipt["content"]})
                (folder / "head.txt").write_text(projection.text, encoding="utf-8")
                snapshots.append({"cut": cut, "goal": head_goal(projection), "head_tokens": projection.tokens,
                                  "view_path": projection.view_path, "sealed": bool(verify_object(projection.view_path)),
                                  "unresolved_facts": list(projection.seeds.unresolved_errors),
                                  "cold_nodes": len(recovery), "cold_exact": sum(recovery), "reads": reads,
                                  "lifecycle": projection.state.lifecycle, "request_source": projection.seeds.request_source,
                                  "request_text": projection.seeds.request_text,
                                  "human_nodes": list(projection.seeds.user_nodes),
                                  "constraints": list(projection.seeds.constraints)})
                (output / "progress.json").write_text(json.dumps({"arm": label, "cut": cut}), encoding="utf-8")
        report["arms"][label] = snapshots
    for cut in cuts:
        a, b = results["before", cut], results["after", cut]
        missing = [p.text for p in a.result.hot.pins if p.key != "goal" and p.text not in {q.text for q in b.result.hot.pins}]
        report["comparisons"].append({"cut": cut, "tokens_before": a.tokens, "tokens_after": b.tokens,
                                       "non_goal_facts_missing": missing})
    final = cuts[-1]
    a, b = results["before", final], results["after", final]
    with arm("1", output / "after" / "home"):
        repeated = project(rows[:final], region_end=final, params=params, session=sid,
                           view_path=output / "after" / str(final) / "cold.txt", persist_view=False)
    report["deterministic_repeat"] = repeated.text == b.text and repeated.cold.texts == b.cold.texts
    (output / "head.diff").write_text("\n".join(difflib.unified_diff(a.text.splitlines(), b.text.splitlines(),
                                          fromfile="before", tofile="after", lineterm="")), encoding="utf-8")
    report["protected_before"] = before
    report["freeze_replay"] = freeze_replay(rows, output / "freeze-replay", sid) if len(rows) >= 68 else {}
    after = fingerprints(protected)
    report["protected_after"] = after
    report["excluded_runtime_artifacts"] = sorted(
        str(p) for p in source.parent.glob(sid + ".*") if p.name.endswith(_RUNTIME_ARTIFACTS))
    source_key = str(source.resolve())
    artifacts_unchanged = ({k: v for k, v in before.items() if k != source_key}
                           == {k: v for k, v in after.items() if k != source_key})
    source_intact = source_prefix_intact(before_source, source)
    report["acceptance"] = {
        "source_and_old_artifacts_unchanged": artifacts_unchanged and source_intact,
        "source_appended_not_rewritten": source_intact,
        "all_cold_nodes_exact": all(s["cold_exact"] == s["cold_nodes"] for snapshots in report["arms"].values() for s in snapshots),
        "actual_reads_succeeded": all(not r["is_error"] for snapshots in report["arms"].values() for s in snapshots for r in s["reads"]),
        "all_candidate_views_content_sealed": all(s["sealed"] for s in report["arms"]["after"]),
        "standing_pin_facts_preserved": all(not row["non_goal_facts_missing"] for row in report["comparisons"]),
        "live_freeze_replay": all(v for k, v in report["freeze_replay"].items() if k != "scope"),
        "unbound_requests_never_inferred_as_goals": all(not s["goal"] for s in report["arms"]["after"]),
        "same_input_deterministic": report["deterministic_repeat"],
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cuts", default="67,200,1844,1845,1879")
    args = parser.parse_args()
    report = evaluate(args.source, args.output.resolve(), [int(x) for x in args.cuts.split(",")])
    print(json.dumps({"acceptance": report["acceptance"], "report": str(args.output / "report.json")}, ensure_ascii=False))
    return 0 if all(report["acceptance"].values()) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
