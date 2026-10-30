import unittest
from unittest import mock

from wsc import material_v2
from wsc.contracts import encode
from wsc.projection import public_material


def row(seq, kind="message", text="t"):
    return {"id": f"e{seq}", "seq": seq, "kind": kind, "role": "user",
            "call_id": None, "text": text, "observed_at": "2026-01-01T00:00:00Z"}


class MaterialViewChecks(unittest.TestCase):
    def setUp(self):
        self.rows = [row(1), row(2), row(3, kind="opaque"), row(4)]
        self.records = [{"id": "u1", "sources": ["e1"], "text": "u"}]
        self.view = material_v2.MaterialView(self.rows, self.records, session_id="s", cut=4)

    def test_public_matches_the_reference_projection(self):
        self.assertEqual({"session_id": "s", "source_boundary": 4,
                          **public_material(self.rows, self.records)}, self.view.public())

    def test_byte_size_is_the_exact_serialized_size(self):
        self.assertEqual(len(encode(self.view.public())), self.view.byte_size())

    def test_slice_projects_only_the_window(self):
        page = self.view.event_slice(1, 2)
        self.assertEqual(["e2", "e4"], [event["id"] for event in page["events"]])
        self.assertEqual([], page["understandings"])
        head = self.view.event_slice(0, 1)
        self.assertEqual(["e1"], [event["id"] for event in head["events"]])
        self.assertEqual(["u1"], [record["id"] for record in head["understandings"]])

    def test_slice_never_builds_the_full_projection(self):
        with mock.patch("wsc.material_v2.public_material",
                        side_effect=AssertionError("full projection built")):
            self.assertEqual(2, len(self.view.event_slice(0, 2)["events"]))


if __name__ == "__main__":
    unittest.main()
