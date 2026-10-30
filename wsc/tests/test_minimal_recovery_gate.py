from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks/deterministic_v1'))
import blackbox_minimal_recovery_group as group


class RecoveryGateTests(unittest.TestCase):
    def test_failure_and_readiness_only_never_dispatch_workers(self):
        for ready,execute,status in [(False,True,'readiness_failed'),(True,False,'service_ready')]:
            with self.subTest(ready=ready,execute=execute),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);parent=root/'parent.json';base=root/'base.json'
                caps=dict(max_total_tokens=1000,max_responses=5,max_seconds=30)
                parent.write_text(json.dumps(dict(remaining_limits=caps,historical_uncertainty=True)))
                base.write_text(json.dumps({'sessions':{'B':{}}}))
                args=SimpleNamespace(out=root/'output',registration=base,parent_envelope=parent,execute=execute,check_service=True)
                reg=dict(arm_limits={'R01/native':caps},limits=caps)
                reuse=root/'reuse';reuse.mkdir();(reuse/'result.json').write_text('{"status":"completed"}')
                args.reuse=reuse
                with patch.object(group,'prepare',return_value=(reg,{},{})),\
                     patch.object(group,'probe_service',return_value=dict(passed=ready,model_calls=0)),\
                     patch.object(group,'ThreadPoolExecutor',side_effect=AssertionError('worker_started')):
                    result=group.run(args)
                self.assertEqual(status,result['status']);self.assertEqual(0,result['ledger']['study']['tokens'])
                self.assertFalse(result['ledger']['inflight'])
                envelope=json.loads((args.out/'next-admission-envelope.json').read_text())
                self.assertEqual(1000,envelope['remaining_limits']['max_total_tokens'])
                self.assertTrue(envelope['historical_uncertainty'])


if __name__=='__main__':unittest.main()
