from pathlib import Path
from types import SimpleNamespace
import tempfile,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from native_latency import LatencyRecorder,TimedRPC,summarize,attach


class TimingTests(unittest.TestCase):
    def test_nested_time_is_not_double_counted_and_errors_propagate(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'timing.jsonl';ticks=iter([0,10,20,40,70,80,90])
            recorder=LatencyRecorder(path,clock=lambda:next(ticks))
            with recorder.span('parent'):
                with recorder.span('child'):pass
            with self.assertRaises(ValueError):
                with recorder.span('failure'):raise ValueError('not logged')
            recorder.close();rows={x['label']:x for x in summarize(path)['spans']}
            self.assertAlmostEqual(60e-9,rows['parent']['inclusive_seconds'])
            self.assertAlmostEqual(40e-9,rows['parent']['exclusive_seconds']);self.assertEqual('error',rows['failure']['status'])
    def test_zero_model_proxy_denies_both_dispatch_routes(self):
        with tempfile.TemporaryDirectory() as temp:
            recorder=LatencyRecorder(Path(temp)/'t.jsonl')
            rpc=TimedRPC(SimpleNamespace(),recorder,'test',deny_inference=True)
            for method in ('turn/start','thread/compact/start'):
                with self.assertRaisesRegex(ValueError,'inference_denied'):rpc.call(method,{})
                with self.assertRaisesRegex(ValueError,'inference_denied'):rpc.send({'method':method})
            recorder.close()
    def test_session_wrapper_preserves_arguments_and_result(self):
        with tempfile.TemporaryDirectory() as temp:
            recorder=LatencyRecorder(Path(temp)/'t.jsonl');seen=[];result=object()
            session=SimpleNamespace(server=SimpleNamespace(),execute_stage=lambda *args,**kw:(seen.append((args,kw)) or result))
            attach(session,recorder,'selector')
            self.assertIs(result,session.execute_stage('unchanged',mode='same'))
            self.assertEqual([(('unchanged',),{'mode':'same'})],seen)
            with self.assertRaisesRegex(ValueError,'already_attached'):attach(session,recorder,'again')
            recorder.close()


if __name__=='__main__':unittest.main()
