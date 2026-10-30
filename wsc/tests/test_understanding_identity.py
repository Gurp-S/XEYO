"""Public write routes retain exact revision identity and atomic failure."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import WSC, Store, Event, Understanding, Selection, Generated, Usage, WSCError
from wsc.generation import selection_from_json
from wsc.generation_boundary import decode_response


class IdentityFixture(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.core = WSC(Store(root / "state.db", session_id="task", workspace=str(root)), access=lambda *args: True)
        self.core.ingest([Event("task", "message", {"text": "task"}, role="user", text="task", control=True)])
        self.first = self.core.remember(Understanding("initial", "hypothesis", id="record"), producer="model")

    def records(self):
        return self.core.material(self.core.capture())["understandings"]


class RevisionContractTests(IdentityFixture):
    def test_boolean_revision_is_rejected_without_writing(self):
        for value in (True, False):
            with self.subTest(value=value):
                before = self.records()
                with self.assertRaises(WSCError):
                    self.core.remember(Understanding("invalid", "hypothesis", id="record", expected_revision=value), producer="model")
                self.assertEqual(before, self.records())

    def test_float_revision_is_rejected_without_writing(self):
        before = self.records()
        with self.assertRaises(WSCError):
            self.core.remember(Understanding("invalid", "hypothesis", id="record", expected_revision=1.0), producer="model")
        self.assertEqual(before, self.records())

    def test_positive_integer_revision_and_stale_cas(self):
        updated = self.core.remember(Understanding("second", "hypothesis", id="record", expected_revision=1), producer="model")
        self.assertEqual(2, updated["revision"])
        self.assertEqual(self.first["ref"], updated["previous"])
        with self.assertRaisesRegex(WSCError, "understanding_revision_conflict"):
            self.core.remember(Understanding("stale", "hypothesis", id="record", expected_revision=1), producer="model")
        self.assertEqual(2, len(self.records()))
        explicit = self.core.remember(Understanding("new", "hypothesis", id="explicit-none", expected_revision=None), producer="model")
        self.assertEqual(1, explicit["revision"])
        selected = selection_from_json({"new_understandings": [{"text": "new", "kind": "hypothesis",
            "id": "json-null", "expected_revision": None}]})
        self.core.prepare(self.core.capture(), selected, producer="model")
        self.assertIn("json-null", {record["id"] for record in self.records()})

    def test_invalid_batch_revision_rolls_back_earlier_new_record(self):
        before = self.records()
        snapshot = self.core.capture()
        with self.assertRaises(WSCError):
            self.core.prepare(snapshot, Selection(new_understandings=(
                Understanding("otherwise valid", "hypothesis", id="second"),
                Understanding("invalid", "hypothesis", id="record", expected_revision=True))), producer="model")
        self.assertEqual(before, self.records())
        self.assertEqual(snapshot.understanding_epoch, self.core.capture().understanding_epoch)

    def test_json_selection_cannot_bypass_shared_revision_validation(self):
        before = self.records()
        with self.assertRaises(WSCError):
            selection = selection_from_json({"new_understandings": [{"text": "invalid", "kind": "hypothesis",
                "id": "record", "expected_revision": 1.0}]})
            self.core.prepare(self.core.capture(), selection, producer="model")
        self.assertEqual(before, self.records())

    def test_invalid_generated_revision_keeps_known_generation_usage(self):
        before = self.records()
        # Actual JSON transport accounts the supplied usage even if construction
        # rejects the selection before the shared writer sees it.
        generator = lambda material: decode_response({"selection": {"new_understandings": [
            {"text": "invalid", "kind": "hypothesis", "id": "record", "expected_revision": True}]},
            "usage": {"input_uncached": 10, "input_cached": 0, "output": 2}}, selection_from_json)
        with self.assertRaises(WSCError):
            self.core.generate(self.core.capture(), generator, producer="model")
        self.assertEqual(before, self.records())
        self.assertEqual(2, self.core.status()["usage"]["totals"]["output"]["known_sum"])


class ExplicitIdentityContractTests(IdentityFixture):
    def test_falsey_explicit_id_is_not_an_omitted_id(self):
        for identity in ("", False, 0, [], {}):
            with self.subTest(identity=identity):
                before = self.records()
                with self.assertRaises(WSCError):
                    self.core.remember(Understanding("invalid", "hypothesis", id=identity), producer="model")
                self.assertEqual(before, self.records())

    def test_none_allocates_distinct_identities(self):
        first = self.core.remember(Understanding("one", "hypothesis"), producer="model")
        second = self.core.remember(Understanding("two", "hypothesis"), producer="model")
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(1, first["revision"])

    def test_named_creation_and_missing_revision_conflict_remain_valid(self):
        value = self.core.remember(Understanding("one", "hypothesis", id="explicit"), producer="model")
        self.assertEqual("explicit", value["id"])
        with self.assertRaisesRegex(WSCError, "understanding_revision_conflict"):
            self.core.remember(Understanding("overwrite", "hypothesis", id="explicit"), producer="model")


if __name__ == "__main__":
    unittest.main()
