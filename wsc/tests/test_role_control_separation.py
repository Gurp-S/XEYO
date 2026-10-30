"""Role states the producer; control states whether the text may steer.

Overwriting `role` to express control (the previous behaviour) destroyed the
producer fact. These checks pin the separation and the one behaviour that
depended on the rewrite: control results never go to external storage.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src')]
from wsc.control_grading import apply_control
from wsc.tool_results import ResultStore, ResultPolicy, RuntimeResults, ToolText

BIG = 'x' * 4000


class SeparationChecks(TestCase):
    def test_control_keeps_the_producer_role(self):
        value = ToolText('hello', role='tool')
        graded = apply_control(value, {'role': 'tool', 'control': True})
        self.assertEqual('tool', graded.role)
        self.assertEqual('declared', graded.control)
        self.assertEqual('operator', apply_control(value, {'role': 'user'}).control)
        self.assertEqual('host', apply_control(value, {'role': 'system'}).control)
        self.assertIs(apply_control(value, {'role': 'tool'}), value)

    def test_control_result_never_goes_external(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = ResultStore(Path(temp.name) / 'results', session='s', access=lambda *a: True)
        runtime = RuntimeResults(store, policy=ResultPolicy(enabled=True, externalize_bytes=10))
        original = runtime.present('c1', ToolText(BIG, role='tool', control='declared'))
        self.assertFalse(original['external'])
        self.assertNotIn('result_id', original)
        original = runtime.present('c2', ToolText(BIG, role='tool'))
        self.assertTrue(original['external'])


if __name__ == '__main__':
    main()
