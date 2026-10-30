"""Declared control sources survive selection without changing roles or authority."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import Generated, Limits, Selection, Store, Usage, WSC, WSCError
from wsc.contracts import Event, encode
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.generation_frontier import FrontierSpanSelectionGenerator


class ControlRetentionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.core = WSC(Store(self.root / "state.db", session_id="s", workspace=str(self.root)),
                        access=lambda *args: True)
        self.control = Event("scope", "control", {"scope": "declared constraint"},
                             text="declared constraint", observed_at="original", control=True)
        self.core.ingest([self.control,
            Event("observation", "observation", {"value": "optional"}, text="optional"),
            Event("kind_only", "control", {"value": "unmarked"}, text="unmarked")])

    def body(self, view):
        with self.core.store.connect() as db:
            return json.loads(db.execute("SELECT data FROM views WHERE id=?", (view,)).fetchone()[0])["body"]

    def floor(self):
        return len(encode({"sources": [self.core.capture().events[0]],
                           "understandings": [], "clues": []}).encode("utf-8"))

    def test_empty_selection_retains_declared_control_exactly_and_exports_it(self):
        snapshot = self.core.capture()
        self.assertEqual(1, snapshot.control_epoch)
        self.core.ingest([self.control])
        self.assertEqual(1, self.core.capture().control_epoch)
        view = self.core.prepare(snapshot, Selection(), producer="fixture")
        self.assertEqual([snapshot.events[0]], self.body(view)["sources"])
        operation = self.core.stage(view, directory=self.root / "export", adapter=CodexCheckpointAdapter())
        package = self.core.package(operation)
        facts = json.loads(package["items"][-1]["content"][0]["text"])
        self.assertEqual(["scope"], [row["source_id"] for row in facts["historical_excerpts"]])
        self.assertEqual("original", facts["historical_excerpts"][0]["observed_at"])
        self.assertEqual({"scope", "observation", "kind_only"}, set(package["evidence"]))
        self.assertEqual(0, self.core.status()["cursor"])

    def test_all_declared_control_roles_and_kinds_share_the_same_retention_rule(self):
        for role in (None, "assistant", "system", "developer", "user"):
            for kind in ("control", "observation"):
                with self.subTest(role=role, kind=kind):
                    key = str(role) + ":" + kind
                    event = Event(key, kind, {"identity": key}, role=role, control=True)
                    self.core.ingest([event])
        snapshot = self.core.capture()
        view = self.core.prepare(snapshot, Selection(), producer="fixture")
        self.assertEqual([r for r in snapshot.events if r["control"]], self.body(view)["sources"])

    def test_mandatory_floor_rejects_before_generator_and_ignores_forged_snapshot_fields(self):
        called = []
        with self.assertRaisesRegex(WSCError, "mandatory_view_byte_budget_exhausted"):
            self.core.generate(replace(self.core.capture(), events=()),
                lambda m: called.append(m) or Generated(Selection(), Usage(1, 2, 3)),
                producer="fixture", limits=Limits(max_view_bytes=self.floor() - 1))
        self.assertEqual([], called)
        self.assertEqual([], self.core.status()["usage"]["attempts"])

    def test_exact_floor_and_selection_facts_match_actual_retention(self):
        seen = []
        view = self.core.generate(self.core.capture(),
            lambda m: seen.append(m) or Generated(Selection(), Usage(1, 2, 3)),
            producer="fixture", limits=Limits(max_view_bytes=self.floor()), include_selection_facts=True)
        facts = seen[0]["selection_facts"]
        self.assertTrue(facts["source_records"]["scope"]["automatically_retained"])
        self.assertFalse(facts["source_records"]["kind_only"]["automatically_retained"])
        self.assertEqual(self.floor(), facts["mandatory_empty_view_bytes"])
        self.assertEqual(self.floor(), len(encode(self.body(view)).encode("utf-8")))
        self.assertEqual(3, self.core.status()["usage"]["totals"]["output"]["known_sum"])

    def test_control_access_denial_cannot_be_bypassed_by_empty_selection(self):
        snapshot = self.core.capture()
        self.core.access = lambda session, source, action: source != "scope"
        with self.assertRaisesRegex(WSCError, "Permission denied"):
            self.core.prepare(snapshot, Selection(), producer="fixture")

    def test_retained_control_survives_frontier_and_new_control_invalidates_old_snapshot(self):
        previous = self.core.prepare(self.core.capture(), Selection(), producer="fixture")
        self.core.ingest([Event("later", "observation", {}, text="new fact")])
        snapshot = self.core.capture()
        generator = FrontierSpanSelectionGenerator(self.core, snapshot, previous, lambda m: None,
                                                   archive_directory=self.root / "cold")
        offered = generator.offer(self.core.material(snapshot))
        self.assertEqual(["s1", "s4"], [e["id"] for e in offered["events"]])
        self.core.ingest([replace(self.control, id="changed")])
        with self.assertRaisesRegex(WSCError, "control_changed"):
            self.core.prepare(snapshot, Selection(), producer="fixture")

    def test_opaque_control_is_rejected_before_generator_but_unmarked_opaque_stays_cold(self):
        self.core.ingest([Event("opaque", "opaque", {"encrypted": "secret"})])
        self.core.prepare(self.core.capture(), Selection(), producer="fixture")
        self.core.ingest([Event("opaque_control", "opaque", {"encrypted": "secret"}, control=True)])
        called = []
        with self.assertRaisesRegex(WSCError, "opaque_hot_selection_unavailable"):
            self.core.generate(self.core.capture(), lambda m: called.append(m) or Generated(Selection()),
                               producer="fixture")
        self.assertEqual([], called)
        self.assertEqual([], self.core.status()["usage"]["attempts"])


if __name__ == "__main__":
    unittest.main()
