from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from native_execution_binding import report_execution_item, verify_execution_binding
from run_native_pair import phase


class ExecutionBindingTests(unittest.TestCase):
    def setUp(self):
        self.work = str(Path.cwd().resolve())
        self.item = report_execution_item(self.work, {})
        self.reg = {"purpose": "C_qualification", "workspace": self.work, "common_workspace_fact": self.item}
        self.opened = {"thread": {"path": "unused"}}
        self.rows = [{"type": "turn_context", "payload": {"cwd": self.work}},
                     {"type": "response_item", "payload": self.item}]

    def check(self, rows=None):
        with patch("native_execution_binding.records", return_value=self.rows if rows is None else rows):
            verify_execution_binding(self.reg, self.opened)

    def test_registered_current_fact_accepts_native_transport_metadata(self):
        rows = deepcopy(self.rows)
        rows[-1]["payload"]["id"] = "native-id"
        self.check(rows)

    def test_fact_before_later_historical_context_is_rejected(self):
        rows = self.rows + [{"type": "response_item", "payload": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": "old environment"}]}}]
        with self.assertRaisesRegex(ValueError, "not_current_tail"):
            self.check(rows)

    def test_runtime_directory_mismatch_is_rejected(self):
        rows = deepcopy(self.rows)
        rows[0]["payload"]["cwd"] = str(Path(self.work) / "other")
        with self.assertRaisesRegex(ValueError, "runtime_workspace_mismatch"):
            self.check(rows)

    def test_missing_fact_blocks_shared_paid_entry(self):
        self.reg.pop("common_workspace_fact")
        server = Mock()
        with patch("run_native_pair.verify_pins"), self.assertRaisesRegex(ValueError, "fact_missing"):
            phase(server, self.opened, self.reg, Path(self.work), None, 1)
        server.call.assert_not_called()

    def test_unregistered_purpose_cannot_silently_bypass_gate(self):
        self.reg.pop("purpose")
        with self.assertRaisesRegex(ValueError, "purpose_unregistered"):
            self.check()

    def test_explicit_generation_only_has_no_business_execution_binding(self):
        verify_execution_binding({"purpose": "automatic_selection_generation_only"}, {})

    def test_continuity_diagnostic_uses_same_execution_fact_gate(self):
        self.reg["purpose"] = "continuity_task_diagnostic_not_comparison"
        self.check()
        self.reg.pop("common_workspace_fact")
        with self.assertRaisesRegex(ValueError, "fact_missing"):
            self.check()
