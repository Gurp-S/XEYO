from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'validation'))
from run_matrix_first_slice import tool_evidence


class ToolProbeEvidenceChecks(unittest.TestCase):
    def check(self, *, kind='function_call_output', denied_code='EPERM', wrong_path=False):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)
            paths=['public','private','peer']
            (out/'registration.json').write_text(json.dumps(dict(probe_paths=paths)),encoding='utf-8')
            (out/'tool-probe').mkdir()
            (out/'tool-probe/write-probe.txt').write_bytes(b'owned-write')
            result=dict(schema='matrix.tool_boundary/1',workspace_write=True,reads=[
                dict(path='wrong' if wrong_path else 'public',readable=True,bytes=19),
                dict(path='private',readable=False,code=denied_code),dict(path='peer',readable=False,code=denied_code)])
            output=json.dumps(dict(output='Output:\n'+json.dumps(result)))
            row=dict(type='response_item',payload=dict(type=kind,output=output))
            area=out/'coordinator-private/tool-probe-phase'
            area.mkdir(parents=True)
            (area/'rollout.jsonl').write_text(json.dumps(row)+'\n',encoding='utf-8')
            return tool_evidence(out)

    def test_exact_actual_tool_output_is_accepted(self):
        self.assertTrue(self.check()['success'])

    def test_model_final_self_report_is_not_tool_evidence(self):
        self.assertFalse(self.check(kind='message')['success'])

    def test_native_custom_tool_result_is_accepted_too(self):
        self.assertTrue(self.check(kind='custom_tool_call_output')['success'])

    def test_missing_file_and_wrong_paths_do_not_prove_denial(self):
        self.assertFalse(self.check(denied_code='ENOENT')['success'])
        self.assertFalse(self.check(wrong_path=True)['success'])


if __name__=='__main__':
    unittest.main()
