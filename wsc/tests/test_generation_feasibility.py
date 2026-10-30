"""A model cannot remove mandatory source bytes; reject infeasible calls first."""
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import WSC, Store, Generated, Selection, Limits, Usage, WSCError
from wsc.contracts import Event, encode


class GenerationFeasibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.core = WSC(Store(self.root / "state.db", session_id="s", workspace=str(self.root)),
                        access=lambda *args: True)
        self.core.ingest([Event("constraint", "message", {"text": "约束\U0001f50d" * 100},
                               role="user", text="约束\U0001f50d" * 100),
                          Event("optional", "observation", {"text": "unused" * 1000}, text="unused" * 1000)])
        self.calls = 0

    def generator(self, material):
        self.calls += 1
        return Generated(Selection(), Usage(1, 2, 3))

    def minimum(self):
        snapshot = self.core.capture()
        return len(encode({"sources": [snapshot.events[0]], "understandings": [], "clues": []}).encode("utf-8"))

    def test_impossible_control_floor_does_not_call_model_or_create_attempt(self):
        # Public snapshot payload fields cannot be trusted as the authoritative floor.
        snapshot = replace(self.core.capture(), events=(), understandings=())
        with self.assertRaises(WSCError):
            self.core.generate(snapshot, self.generator, producer="offline_fixture",
                               limits=Limits(max_view_bytes=self.minimum() - 1))
        self.assertEqual(0, self.calls)
        self.assertEqual([], self.core.status()["usage"]["attempts"])

    def test_exact_floor_fits_without_charging_unselected_optional_history(self):
        view = self.core.generate(self.core.capture(), self.generator, producer="offline_fixture",
                                 limits=Limits(max_view_bytes=self.minimum()))
        self.assertIsInstance(view, str)
        self.assertEqual(1, self.calls)
        self.assertEqual(3, self.core.status()["usage"]["totals"]["output"]["known_sum"])

    def test_material_budget_still_rejects_before_any_model_attempt(self):
        with self.assertRaisesRegex(WSCError, "generation_material_byte_budget_exhausted"):
            self.core.generate(self.core.capture(), self.generator, producer="offline_fixture",
                               limits=Limits(max_material_bytes=1))
        self.assertEqual(0, self.calls)
        self.assertEqual([], self.core.status()["usage"]["attempts"])


if __name__ == "__main__":
    unittest.main()
