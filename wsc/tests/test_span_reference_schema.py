from copy import deepcopy
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments"))
from span_reference_schema import compact_schema, REFERENCE_PATTERN
from run_quote_selection_probe import output_schema
from wsc.contracts import Usage, WSCError
from wsc.quote_selection import SelectionDraft
from wsc.span_selection import SpanSelectionGenerator, span_material


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.material = {"events": [{"id": "original", "seq": 1, "kind": "message", "role": "assistant",
            "call_id": None, "text": "exact observation", "observed_at": "old"}], "understandings": []}
        self.offered = span_material(self.material)
        self.schema = output_schema(self.offered, "span")
        self.ref = self.offered["events"][0]["spans"][0]["ref"]

    def test_only_reference_membership_shape_changes_without_mutating_original(self):
        original = deepcopy(self.schema)
        compact = compact_schema(self.schema)
        self.assertEqual(original, self.schema)
        self.assertTrue(re.fullmatch(REFERENCE_PATTERN, self.ref))
        self.assertNotIn("enum", compact["properties"]["span_refs"]["items"])
        compact["properties"]["span_refs"] = original["properties"]["span_refs"]
        self.assertEqual(original, compact)

    def test_retention_descriptions_do_not_leak_into_provenance_or_quote_fields(self):
        props = self.schema['properties']
        self.assertIn('description', props['source_ids'])
        self.assertIn('description', props['span_refs'])
        self.assertNotIn('description', props['understanding_refs'])
        for name in ('new_understandings', 'clues'):
            self.assertNotIn('description', props[name]['items']['properties']['sources'])
        self.assertNotIn('description', output_schema()['properties']['source_ids'])

    def test_no_spans_cannot_become_unbounded_arbitrary_strings(self):
        schema = output_schema({"events": []}, "span")
        self.assertEqual(0, compact_schema(schema)["properties"]["span_refs"]["maxItems"])
        schema["properties"]["span_refs"].pop("maxItems")
        with self.assertRaisesRegex(ValueError, "not_enumerated"):
            compact_schema(schema)

    def test_old_unknown_reference_format_rejects_before_call(self):
        self.schema["properties"]["span_refs"]["items"]["enum"] = ["unbound-old-handle"]
        with self.assertRaisesRegex(ValueError, "shape_unknown"):
            compact_schema(self.schema)

    def test_well_shaped_forgery_still_fails_compiler_and_preserves_usage(self):
        forged = self.ref[:-1] + ("0" if self.ref[-1] != "0" else "1")
        self.assertTrue(re.fullmatch(REFERENCE_PATTERN, forged))
        generator = SpanSelectionGenerator(lambda _: SelectionDraft({"span_refs": [forged]}, Usage(3, 4, 5)))
        with self.assertRaisesRegex(WSCError, "missing_or_changed") as ctx:
            generator(self.material)
        self.assertEqual(5, ctx.exception.usage.output)
        valid = SpanSelectionGenerator(lambda _: SelectionDraft({"span_refs": [self.ref]}, Usage(3, 4, 5)))
        selected = valid(self.material)
        self.assertEqual("original", selected.selection.excerpts[0].source_id)
