from pathlib import Path
import shutil
import sys
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]/'benchmarks'
sys.path.insert(0, str(BASE))
from acceptance_matrix_v1.acceptors import load_candidate
from acceptance_matrix_v1.acceptor_t2 import accept_t2
from acceptance_matrix_v1.acceptor_t5 import accept_t5

SUITE = BASE/'acceptance_matrix_v1'


class ApiPipelineAcceptorChecks(unittest.TestCase):
    def failed(self, result, identity):
        return not next(r for r in result['checks'] if r['check_id'] == identity)['passed']

    def test_typescript_reference_passes_type_and_all_callers(self):
        result = accept_t2(SUITE/'calibration/t2_api')
        self.assertTrue(result['success'], result)
        self.assertEqual(13, len(result['checks']))

    def test_typescript_starter_fails_real_type_contract(self):
        result = accept_t2(SUITE/'tasks/t2_api/starter')
        self.assertFalse(result['success'])
        self.assertTrue(self.failed(result, 'typescript-contract'))
        self.assertEqual(12, result['runtime_checks_not_run'])

    def test_updating_only_api_does_not_pass_callers(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'source'
            shutil.copytree(SUITE/'tasks/t2_api/starter', target)
            shutil.copyfile(SUITE/'calibration/t2_api/api.ts', target/'api.ts')
            self.assertTrue(self.failed(accept_t2(target), 'typescript-contract'))

    def test_name_only_provider_filter_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'source'
            shutil.copytree(SUITE/'calibration/t2_api', target)
            source = target/'api.ts'
            text = source.read_text(encoding='utf-8')
            before = 'row.provider === key.provider && row.model === key.name'
            self.assertEqual(1, text.count(before))
            source.write_text(text.replace(before, 'row.model === key.name'), encoding='utf-8')
            self.assertTrue(self.failed(accept_t2(target), 'provider-pair'))

    def test_exporting_first_page_only_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'source'
            shutil.copytree(SUITE/'calibration/t2_api', target)
            (target/'exporter.ts').write_text("import {listUsage, Row} from './api';\nexport function run(rows:Row[],tenant:string,provider:string,model:string):Row[]{return listUsage(rows,{tenant,model:{provider,name:model}}).items;}\n", encoding='utf-8')
            self.assertTrue(self.failed(accept_t2(target), 'export-pages'))

    def test_pipeline_reference_passes_all_stages(self):
        result = accept_t5(load_candidate(SUITE/'calibration/pipeline_reference.py'))
        self.assertTrue(result['success'], result)
        self.assertEqual(11, len(result['checks']))

    def test_pipeline_starter_does_not_pass_format_or_lineage(self):
        result = accept_t5(load_candidate(SUITE/'tasks/t5_pipeline/starter/pipeline.py'))
        self.assertFalse(result['success'])
        self.assertEqual(11, len(result['checks']))

    def test_float_cents_and_replacement_decoding_are_detected(self):
        original = (SUITE/'calibration/pipeline_reference.py').read_text(encoding='utf-8')
        replacements = [
            ("cents = (int(whole)*100 + int((fraction+'00')[:2])) * (-1 if amount.startswith('-') else 1)",
             'cents = int(float(amount)*100)', 'exact-integer'),
            ("raw.decode('utf-8')", "raw.decode('utf-8', errors='replace')", 'strict-utf8')]
        for before, after, check in replacements:
            with self.subTest(check=check), tempfile.TemporaryDirectory() as folder:
                self.assertEqual(1, original.count(before))
                source = Path(folder)/'pipeline.py'
                source.write_text(original.replace(before, after), encoding='utf-8')
                self.assertTrue(self.failed(accept_t5(load_candidate(source)), check))

    def test_wrong_stage_relationship_is_detected(self):
        original = (SUITE/'calibration/pipeline_reference.py').read_text(encoding='utf-8')
        before = "from_sha256=sha256(payloads['normalized']).hexdigest()"
        self.assertEqual(1, original.count(before))
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'pipeline.py'
            source.write_text(original.replace(before, "from_sha256='0'*64"), encoding='utf-8')
            self.assertTrue(self.failed(accept_t5(load_candidate(source)), 'stage-files-and-values'))


if __name__ == '__main__':
    unittest.main()
