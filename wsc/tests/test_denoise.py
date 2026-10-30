"""Denoise rules keep identity and control rows, and report what they removed."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wsc.denoise import DenoisePolicy, RULES, apply_rules, recover, summarize, verify
from wsc.denoise.registry import row_size
from wsc.contracts import WSCError


ENABLED = DenoisePolicy(enabled=True)


def run(rows, rule_ids=None):
    return apply_rules(rows, rule_ids, policy=ENABLED)


def row(seq, kind, payload, text=None, role=None, call_id=None, control=False):
    return {"seq": seq, "id": f"s{seq}", "kind": kind, "payload": payload, "text": text,
            "role": role, "call_id": call_id, "control": control}


class DenoiseTests(unittest.TestCase):
    def test_control_rows_pass_through_every_rule(self):
        rows = [row(1, "message", {"text": "task"}, "task", role="user", control=True),
                row(2, "result", {"output": "x" * 9000}, "x" * 9000, call_id="c1")]
        result, _ = run(rows, None)
        self.assertEqual(rows[0], result[0])

    def test_identity_fields_are_preserved(self):
        rows = [row(1, "result", {"path": "a.py", "content": "old"}, "old", call_id="c1"),
                row(2, "result", {"path": "a.py", "content": "new"}, "new", call_id="c2")]
        result, _ = run(rows, ["dedupe_reads"])
        self.assertEqual([(r["id"], r["kind"], r["call_id"]) for r in rows],
                         [(r["id"], r["kind"], r["call_id"]) for r in result])

    def test_dedupe_identical_points_at_the_first_occurrence(self):
        text = "same output " * 40
        rows = [row(1, "result", {"output": text}, text, call_id="c1"),
                row(2, "result", {"output": text}, text, call_id="c2")]
        result, actions = run(rows, ["dedupe_identical"])
        self.assertEqual(1, len(actions))
        self.assertEqual(rows[0]["id"], actions[0].pointer["same_as"])
        self.assertLess(row_size(result[1]), row_size(rows[1]))

    def test_dedupe_never_grows_a_row(self):
        rows = [row(1, "result", {"output": "a"}, "a", call_id="c1"),
                row(2, "result", {"output": "a"}, "a", call_id="c2")]
        result, actions = run(rows, ["dedupe_identical"])
        self.assertEqual([], actions)
        self.assertEqual(rows, result)

    def test_dedupe_reads_keeps_the_newest_observation(self):
        old, new = "v1\n" * 40, "v2\n" * 40
        rows = [row(1, "result", {"path": "a.py", "content": old}, old, call_id="c1"),
                row(2, "result", {"path": "a.py", "content": new}, new, call_id="c2")]
        result, actions = run(rows, ["dedupe_reads"])
        self.assertEqual(rows[1]["id"], result[1]["id"])
        self.assertEqual(new, result[1]["text"])
        self.assertEqual(rows[1]["id"], actions[0].pointer["superseded_by"])

    def test_truncation_keeps_head_and_tail(self):
        text = "H" * 3000 + "M" * 5000 + "T" * 2000
        rows = [row(1, "result", {"output": text}, text, call_id="c1")]
        result, actions = run(rows, ["truncate_head_tail"])
        trimmed = result[0]["text"]
        self.assertTrue(trimmed.startswith("H" * 100))
        self.assertTrue(trimmed.endswith("T" * 100))
        self.assertIn("chars omitted", trimmed)
        self.assertGreater(actions[0].saved, 0)

    def test_outline_json_is_smaller_and_keeps_a_pointer(self):
        payload = {"items": [{"id": f"i{n}", "body": "x" * 100} for n in range(60)]}
        rows = [row(1, "result", payload, None, call_id="c1")]
        result, actions = run(rows, ["outline_json"])
        self.assertLess(row_size(result[0]), row_size(rows[0]))
        self.assertEqual("source_read", actions[0].pointer["recover"])

    def test_report_totals_match_actions(self):
        rows = [row(1, "result", {"output": "x" * 9000}, "x" * 9000, call_id="c1")]
        result, actions = run(rows, ["truncate_head_tail"])
        report = summarize(actions, len(rows), len(result))
        self.assertEqual(actions[0].saved, report["saved_bytes"])
        self.assertEqual(1.0, report["recoverable_ratio"])

    def test_unknown_rule_is_rejected(self):
        with self.assertRaisesRegex(WSCError, "denoise_rule_unknown"):
            run([], ["nope"])

    def test_denoise_is_disabled_by_default(self):
        with self.assertRaisesRegex(WSCError, "denoise_disabled"):
            apply_rules([row(1, "result", {"output": "x" * 9000}, "x" * 9000, call_id="c1")], None)
        with self.assertRaisesRegex(WSCError, "denoise_disabled"):
            apply_rules([], None, policy=DenoisePolicy())

    def test_every_registered_rule_declares_reversibility(self):
        for name, module in RULES().items():
            self.assertIn(module.REVERSIBLE, {"exact", "pointer", "lossy"}, name)


def noisy_rows():
    rows = []
    seq = 0

    def add(kind, payload, text=None, role=None, call_id=None, control=False):
        nonlocal seq
        seq += 1
        rows.append({"seq": seq, "id": f"s{seq}", "kind": kind, "payload": payload,
                     "text": text, "role": role, "call_id": call_id, "control": control})

    add("message", {"text": "task"}, "task", role="user", control=True)
    log = "\n".join(["PASSED test_a", "." * 40, "progress 10%\rprogress 20%"] + ["line"] * 40)
    for index in range(4):
        add("result", {"output": log}, log, call_id=f"c{index}")
    dup = "same output " * 60
    for index in range(3):
        add("result", {"output": dup}, dup, call_id=f"d{index}")
    for version in range(2):
        content = f"v{version}\n" * 50
        add("result", {"path": "a.py", "content": content}, content, call_id=f"r{version}")
    big = {"items": [{"id": f"i{n}", "body": "x" * 120} for n in range(80)]}
    add("result", big, None, call_id="big")
    diff = "\n".join(["diff --git a/x b/x", "--- a/x", "+++ b/x", "@@ -1,5 +1,5 @@"]
                     + [f"-old {n}" for n in range(15)] + [f"+new {n}" for n in range(15)])
    add("result", {"output": diff}, diff, call_id="diff")
    return rows


class DenoiseGuaranteeTests(unittest.TestCase):
    def test_verify_passes_for_every_rule_and_for_all_rules(self):
        rows = noisy_rows()
        for name in list(RULES()) + [None]:
            result, actions = run(rows, [name] if name else None)
            summary = verify(rows, result, actions)
            self.assertEqual(len(rows), summary["rows"])
            self.assertTrue(summary["control_unchanged"])
            self.assertEqual(len(actions), summary["changed"])

    def test_recover_returns_the_original_row_for_every_action(self):
        rows = noisy_rows()
        result, actions = run(rows, None)
        self.assertGreater(len(actions), 0)
        restored = recover(actions, rows)
        self.assertEqual(len({action.source_id for action in actions}), len(restored))
        for source_id, original in restored.items():
            self.assertEqual(source_id, original["id"])

    def test_denoise_is_idempotent(self):
        rows = noisy_rows()
        once, _ = run(rows, None)
        twice, second = run(once, None)
        self.assertEqual(once, twice)
        self.assertEqual([], second)

    def test_verify_rejects_identity_change(self):
        rows = noisy_rows()
        before = deepcopy(rows)
        result, actions = run(rows, None)
        result[1]["call_id"] = "tampered"
        with self.assertRaisesRegex(WSCError, "denoise_identity_changed"):
            verify(before, result, actions)

    def test_verify_rejects_a_change_without_an_action(self):
        rows = noisy_rows()
        before = deepcopy(rows)
        result, actions = run(rows, None)
        untouched = [index for index, row in enumerate(result) if row == before[index]
                     and not (row.get("control") or row.get("role") in {"system", "developer", "user"})]
        self.assertTrue(untouched)
        result[untouched[0]]["text"] = "silently rewritten"
        with self.assertRaisesRegex(WSCError, "denoise_action_row_mismatch"):
            verify(before, result, actions)

    def test_verify_rejects_a_pointer_hash_mismatch(self):
        rows = noisy_rows()
        result, actions = run(rows, None)
        self.assertGreater(len(actions), 0)
        actions[0].pointer["content_sha256"] = "0" * 64
        with self.assertRaisesRegex(WSCError, "denoise_pointer_hash_mismatch"):
            verify(rows, result, actions)

    def test_verify_rejects_a_control_row_change(self):
        rows = noisy_rows()
        result = [dict(row) for row in rows]
        result[0]["text"] = "changed control"
        with self.assertRaisesRegex(WSCError, "denoise_control_row_changed"):
            verify(rows, result, [])


if __name__ == "__main__":
    unittest.main()
