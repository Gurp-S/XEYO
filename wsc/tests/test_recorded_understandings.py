from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import Store, WSC, Selection, Understanding, WSCError
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.recorded_codex import RecordedCodexCheckpointAdapter
from wsc.publication import check_evidence
from wsc.recorded_understandings import recorded_items


class RecordedUnderstandingTests(unittest.TestCase):
    def setUp(self):
        self.record = {"ref": "r@2", "previous": "r@1", "producer": "model-call-2",
            "kind": "verification", "text": "incorrect copied value", "scope": None, "sources": ["s1"]}
        self.value = {**{k: self.record[k] for k in ("ref", "kind", "text", "scope")},
                      "sources": [{"source_id": "s1", "path": "archive", "observed_at": "then"}]}
        self.facts = {"kind": "working_state", "understandings": [self.value],
                      "historical_excerpts": [{"source_id": "s1", "text": "exact observed value"}]}
        self.item = {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": json.dumps(self.facts)}]}

    def test_interpretation_is_unchanged_and_revision_identity_visible_before_observations(self):
        original = deepcopy(self.item)
        result = recorded_items([self.item], [self.record], working_state_index=0)
        facts = json.loads(result[0]["content"][0]["text"])
        self.assertEqual(original, self.item)
        self.assertEqual(self.record["text"], facts["model_records"][0]["text"])
        self.assertEqual("r@1", facts["model_records"][0]["previous"])
        self.assertEqual("model-call-2", facts["model_records"][0]["producer"])
        self.assertEqual(self.facts["historical_excerpts"], facts["historical_excerpts"])
        self.assertLess(list(facts).index("model_records"), list(facts).index("historical_excerpts"))

    def test_other_historical_working_state_messages_and_tail_are_not_reinterpreted(self):
        items = [deepcopy(self.item), self.item, {"type": "message", "role": "user", "content": []}]
        result = recorded_items(items, [self.record], working_state_index=1)
        self.assertEqual(items[0], result[0])
        self.assertEqual(items[2], result[2])

    def test_changed_text_or_sources_cannot_borrow_another_records_provenance(self):
        for key, changed in [("text", "different"), ("sources", ["other"]), ("scope", {"new": True})]:
            record = {**self.record, key: changed}
            with self.subTest(key=key), self.assertRaisesRegex(WSCError, "binding_changed"):
                recorded_items([self.item], [record], working_state_index=0)

    def test_duplicate_record_identity_is_rejected(self):
        with self.assertRaisesRegex(WSCError, "identity_ambiguous"):
            recorded_items([self.item], [self.record, self.record], working_state_index=0)

    def test_real_export_retains_controls_sources_revisions_and_cold_proofs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            core = WSC(Store(root / "state.db", session_id="s", workspace=str(root)), access=lambda *args: True)
            messages = [{"type": "message", "role": role,
                         "content": [{"type": "input_text", "text": text}]}
                        for role, text in [("user", "task"), ("assistant", "exact observed value")]]
            ids = core.ingest(CodexCheckpointAdapter().import_items(messages, thread_id="t"))
            first = core.remember(Understanding("old hypothesis", "hypothesis", (ids[1],)), producer="first-model")
            second = core.remember(Understanding("revised hypothesis", "hypothesis", (ids[1],),
                id=first["id"], expected_revision=1), producer="second-model")
            view = core.prepare(core.capture(), Selection(source_ids=(ids[1],),
                understanding_refs=(second["ref"],)), producer="selection")
            op = core.stage(view, directory=root / "out", adapter=RecordedCodexCheckpointAdapter())
            package = core.package(op)
            check_evidence(core, package)
            self.assertEqual(messages, package["items"][:2])
            facts = json.loads(package["items"][2]["content"][0]["text"])
            self.assertEqual(first["ref"], facts["model_records"][0]["previous"])
            self.assertEqual("second-model", facts["model_records"][0]["producer"])
            self.assertEqual("unverified", package["semantic_status"])
