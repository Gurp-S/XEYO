"""Non-vacuous real GoalStore transitions through the production frozen adapter."""
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def evaluate(rows, output):
    from evals.wsc_request_projection import arm
    from memory import wsc_projection as live, wsc_head_store as heads
    from engine.goal_state import GoalStore
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    previous = dict(live._STATE)
    sid = "bound-replay-" + uuid.uuid4().hex[:12]
    working = SimpleNamespace(session_id=sid, compact_cursor=67, c1_frozen_until=67)
    def emit(count):
        value = live.project_c2_messages(rows[:count], working, cwd=str(output))
        assert value is not None
        return value
    def facts(messages):
        found = []
        for msg in messages:
            text = msg.get("content", "")
            if isinstance(text, str) and text.startswith("[BOUND_GOAL_STATE]\n"):
                found.append(json.loads(text.split("\n", 1)[1]))
        return found
    try:
        with arm("1", output / "home"), patch.object(live, "live_enabled", return_value=True), \
             patch.object(live, "freeze_enabled", return_value=True), patch.object(heads, "enabled", return_value=True), \
             patch("memory.wsc_extension_economics.absorb_boundary", side_effect=lambda messages, cursor: cursor):
            store = GoalStore(str(output))
            goal = store.create(title="窗口", text="修复 ChatGPT 前台窗口")
            store.bind(sid, goal.goal_id)
            before = emit(68)
            store.transition(goal.goal_id, "paused", revision=1)
            paused = emit(68)
            same = emit(68)
            growing = emit(69)
            live._STATE.clear()
            restarted = emit(69)
            store.transition(goal.goal_id, "active", revision=2)
            store.transition(goal.goal_id, "completed", revision=3)
            done = emit(69)
            live._STATE.clear()
            done_restart = emit(69)
            working.compact_cursor = working.c1_frozen_until = 69
            folded = emit(69)
            live._STATE.clear()
            folded_restart = emit(69)
            stages = dict(before=before, paused=paused, growing=growing, completed=done, folded=folded)
            for key, data in stages.items():
                (output / f"{key}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            checks = {
                "pause_fact_without_fold": bool(facts(paused)) and facts(paused)[-1]["status"] == "paused",
                "frozen_head_unchanged": before[0] == paused[0],
                "prior_emission_prefix_preserved": paused[:len(before)] == before,
                "same_state_no_duplicate": paused == same,
                "new_raw_after_prior_fact": growing[:len(paused)] == paused,
                "restart_emission_identical": growing == restarted,
                "completion_fact_without_fold": bool(facts(done)) and facts(done)[-1]["status"] == "completed",
                "completion_append_only": done[:len(growing)] == growing,
                "completion_restart_identical": done == done_restart,
                "completed_absorbed_after_fold": not facts(folded) and "绑定目标快照（active" not in str(folded[0]),
                "folded_restart_identical": folded == folded_restart,
            }
            report = {"scope":"isolated real GoalStore, real transcript, production adapter, no model call",
                      "acceptance":checks, "pause_facts":facts(paused), "completion_facts":facts(done)}
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return report
    finally:
        live._STATE.clear()
        live._STATE.update(previous)
