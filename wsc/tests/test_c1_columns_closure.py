from pathlib import Path
from types import SimpleNamespace
import json,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'benchmarks/deterministic_v1'),str(ROOT/'experiments'),str(ROOT/'src')]
from c1_columns_qualification import settle_bootstrap
from native_latency import LatencyRecorder


class C1ClosureTests(unittest.TestCase):
    def test_cleanup_receipt_and_live_ledger_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);calls=[];receipt={'empty_confirmed':True};snapshot={'inflight':{'unsettled':'retained'}}
            boot=SimpleNamespace(close=lambda:calls.append('close') or receipt);ledger=SimpleNamespace(snapshot=lambda:snapshot)
            with LatencyRecorder(out/'timing.jsonl') as timing:settle_bootstrap(boot,ledger,timing,out)
            self.assertEqual(calls,['close']);self.assertEqual(json.loads((out/'bootstrap-cleanup.json').read_text()),receipt)
            self.assertEqual(json.loads((out/'dispatch-ledger.json').read_text()),snapshot)

    def test_cleanup_failure_keeps_unsettled_usage_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);calls=[];snapshot={'study':{'uncertain':True},'inflight':{'ticket':{'arm':'C'}}}
            def fail():calls.append('close');raise OSError('cleanup unavailable')
            with LatencyRecorder(out/'timing.jsonl') as timing:
                with self.assertRaisesRegex(OSError,'cleanup unavailable'):settle_bootstrap(SimpleNamespace(close=fail),SimpleNamespace(snapshot=lambda:snapshot),timing,out)
            self.assertEqual(calls,['close']);self.assertEqual(json.loads((out/'dispatch-ledger.json').read_text()),snapshot)
            self.assertFalse((out/'bootstrap-cleanup.json').exists())


if __name__=='__main__':unittest.main()
