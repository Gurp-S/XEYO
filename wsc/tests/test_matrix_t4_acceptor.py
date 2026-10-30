from pathlib import Path
import shutil
import sys
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]/'benchmarks'
sys.path.insert(0, str(BASE))
from acceptance_matrix_v1.acceptor_t4 import accept_t4

SUITE = BASE/'acceptance_matrix_v1'


class BrowserAcceptorChecks(unittest.TestCase):
    def mutated(self, before, after):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)/'ui'
            shutil.copytree(SUITE/'tasks/t4_ui/starter', work)
            for source in (SUITE/'calibration/t4_ui').iterdir():
                shutil.copyfile(source, work/source.name)
            source = work/'app.js'
            text = source.read_text(encoding='utf-8')
            self.assertIn(before, text)
            source.write_text(text.replace(before, after), encoding='utf-8')
            return accept_t4(work)

    def test_reference_status_and_output_have_separate_assertions(self):
        result = self.mutated('const key=row=>', 'const key=row=>')
        self.assertTrue(result['success'], result)
        self.assertEqual(13, len(result['checks']))

    def test_provider_alias_collapse_is_detected(self):
        result = self.mutated('JSON.stringify([row.provider,row.model])', 'JSON.stringify([row.model])')
        self.assertFalse(next(r for r in result['checks'] if r['check_id'] == 'provider-filter')['passed'])

    def test_old_request_completion_cannot_replace_latest_result(self):
        result = self.mutated('own===generation', 'true')
        self.assertFalse(next(r for r in result['checks'] if r['check_id'] == 'request-race')['passed'])

    def test_pending_request_after_destroy_is_detected(self):
        result = self.mutated('!destroyed&&own===generation', 'true')
        self.assertFalse(next(r for r in result['checks'] if r['check_id'] == 'destroy-pending')['passed'])


if __name__ == '__main__':
    unittest.main()
