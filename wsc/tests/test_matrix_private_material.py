from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmarks'))
from acceptance_matrix_v1.private_material import inventory, verify


class PrivateMaterialChecks(TestCase):
    def setup_files(self, directory):
        root = Path(directory)
        work = root / 'actor'; work.mkdir()
        private = root / 'private'; private.mkdir()
        child = private / 'report'; child.mkdir()
        answer = child / 'answer.json'; answer.write_text('{"answer":3}')
        return work, private, child, answer

    def test_exact_inventory_and_minimal_enclosing_roots(self):
        with TemporaryDirectory() as d:
            work, private, child, answer = self.setup_files(d)
            value = inventory([answer], [private, child], workspace=work)
            self.assertEqual([str(private.resolve())], value['blocked'])
            self.assertEqual(value, verify(value, workspace=work))

    def test_new_artifact_outside_declared_domains_is_rejected(self):
        with TemporaryDirectory() as d:
            work, private, child, answer = self.setup_files(d)
            leak = Path(d) / 'new-report.md'; leak.write_text('answer=3')
            with self.assertRaisesRegex(ValueError, 'private_material_uncovered'):
                inventory([answer, leak], [private], workspace=work)

    def test_changed_answer_or_workspace_is_rejected(self):
        with TemporaryDirectory() as d:
            work, private, child, answer = self.setup_files(d)
            value = inventory([answer], [private], workspace=work)
            other = Path(d) / 'other'; other.mkdir()
            with self.assertRaisesRegex(ValueError, 'inventory_changed'):
                verify(value, workspace=other)
            answer.write_text('{"answer":4}')
            with self.assertRaisesRegex(ValueError, 'inventory_changed'):
                verify(value, workspace=work)

    def test_actor_cannot_be_inside_or_enclose_denied_domain(self):
        with TemporaryDirectory() as d:
            work, private, child, answer = self.setup_files(d)
            for denied in ([Path(d)], [work]):
                with self.assertRaisesRegex(ValueError, 'workspace_overlap'):
                    inventory([answer], denied, workspace=work)


if __name__ == '__main__': main()
