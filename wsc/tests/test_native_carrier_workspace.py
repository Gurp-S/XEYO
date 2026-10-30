"""A native opaque checkpoint has no established cross-workspace migration."""
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "experiments")]
from wsc import WSC, Store, Selection, WSCError
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.native_carrier import NativeCarrierCheckpointAdapter
from wsc.contracts import digest
from run_native_pair import phase
from test_contracts import message


class NativeCarrierWorkspaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="wsc-carrier-workspace-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.carrier = {"type": "compaction", "encrypted_content": "opaque-test-value"}
        self.source = [message("user", "Original task")]

    def adapter(self, workspace):
        return NativeCarrierCheckpointAdapter(self.carrier, source_count=1,
            source_digest=digest(self.source), workspace=workspace)

    def core(self):
        core = WSC(Store(self.root / "state.db", session_id="test", workspace=str(self.root / "current")),
                   access=lambda *args: True)
        core.ingest(CodexCheckpointAdapter().import_items(self.source + [self.carrier], thread_id="native"))
        view = core.prepare(core.capture(), Selection(), producer="test")
        return core, view

    def test_cross_workspace_stage_rejected_before_archive_or_operation(self):
        core, view = self.core()
        with self.assertRaisesRegex(WSCError, "native_carrier_workspace_mismatch"):
            core.stage(view, directory=self.root / "exports", adapter=self.adapter(str(self.root / "historical")))
        self.assertFalse((self.root / "exports").exists())
        self.assertEqual([], core.status()["operations"])

    def test_same_workspace_retains_original_native_protocol_value(self):
        core, view = self.core()
        key = core.stage(view, directory=self.root / "exports", adapter=self.adapter(core.store.workspace))
        package = core.package(key)
        self.assertEqual(self.carrier, package["items"][1])
        self.assertEqual(core.store.workspace, package["binding"]["workspace"])

    def test_missing_or_relative_workspace_is_not_a_bound_checkpoint(self):
        for workspace in (None, "", "relative"):
            with self.subTest(workspace=workspace), self.assertRaisesRegex(WSCError, "native_carrier_workspace_required"):
                self.adapter(workspace)

    def test_phase_rejects_migration_before_any_native_request(self):
        server = Mock()
        (self.root / "frozen-workspace").mkdir()
        reg = {"pins": {}, "origin": str(self.root), "initial_manifest": {},
               "workspace": str(self.root / "current"),
               "native_carrier": {"workspace": str(self.root / "historical")}}
        with self.assertRaisesRegex(ValueError, "native_carrier_workspace_mismatch"):
            phase(server, {}, reg, self.root, None, time.monotonic() + 60)
        server.call.assert_not_called()
        self.assertFalse((self.root / "attempt-started.json").exists())


if __name__ == "__main__":
    unittest.main()
