from unittest import TestCase, main
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src')]
from wsc.control_grading import control_grade, is_control_source


class ControlGradingChecks(TestCase):
    def test_roles_grade_by_authority(self):
        self.assertEqual('host', control_grade({'role': 'system'}))
        self.assertEqual('host', control_grade({'role': 'developer'}))
        self.assertEqual('operator', control_grade({'role': 'user'}))
        self.assertIsNone(control_grade({'role': 'assistant'}))

    def test_explicit_flag_grades_as_declared_on_any_other_role(self):
        self.assertEqual('declared', control_grade({'role': 'tool', 'control': True}))
        self.assertEqual('declared', control_grade({'control': True}))

    def test_role_wins_over_the_explicit_flag(self):
        self.assertEqual('operator', control_grade({'role': 'user', 'control': True}))
        self.assertEqual('host', control_grade({'role': 'system', 'control': True}))

    def test_the_binary_predicate_still_agrees_with_the_grade(self):
        rows = [{'role': 'system'}, {'role': 'developer'}, {'role': 'user'},
                {'role': 'tool'}, {'role': 'assistant', 'control': False},
                {'role': 'tool', 'control': True}, {}, {'control': True}]
        for row in rows:
            self.assertEqual(control_grade(row) is not None, is_control_source(row), row)


if __name__ == '__main__':
    main()
