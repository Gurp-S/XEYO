"""Transport workspace must not stand in for an observed task workspace."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "experiments")]
from native_generation_scope import generation_scope
from native_rollout_snapshot import parse_rollout


class GenerationScopeTests(unittest.TestCase):
    def fixture(self, contexts):
        snapshot = parse_rollout(('\n'.join(json.dumps({"type": "turn_context", "payload": v})
            for v in contexts) + '\n').encode())
        return snapshot, {"thread_id": "source-thread", "rollout_sha256": snapshot.metadata["sha256"],
                          "usage_completion_evidence": {"turn_id": "source-turn"}}

    def test_source_context_is_historical_and_future_execution_stays_unknown(self):
        source = str((Path.cwd() / "historical-task").resolve())
        snapshot, phase = self.fixture([{"turn_id": "auto-compact-0", "cwd": "ignored"},
            {"turn_id": "source-turn", "cwd": source}])
        result = generation_scope(snapshot, phase, Path.cwd() / "empty-generator")
        self.assertEqual(source, result["source_execution"]["workspace"])
        self.assertNotEqual(source, result["generator_workspace"])
        self.assertEqual({"status": "not_registered", "workspace": None}, result["continuation_execution"])

    def test_missing_ambiguous_or_relative_source_workspace_is_rejected(self):
        valid = {"turn_id": "source-turn", "cwd": str(Path.cwd())}
        for contexts in ([], [valid, valid], [{**valid, "cwd": "relative"}]):
            with self.subTest(contexts=contexts):
                snapshot, phase = self.fixture(contexts)
                with self.assertRaises(ValueError):
                    generation_scope(snapshot, phase, Path.cwd())

    def test_changed_rollout_cannot_reuse_an_old_context_receipt(self):
        snapshot, phase = self.fixture([{"turn_id": "source-turn", "cwd": str(Path.cwd())}])
        phase["rollout_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "rollout_changed"):
            generation_scope(snapshot, phase, Path.cwd())


if __name__ == "__main__":
    unittest.main()
