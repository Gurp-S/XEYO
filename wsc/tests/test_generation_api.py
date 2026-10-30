from pathlib import Path
from unittest import TestCase, main
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src')]
from wsc.contracts import Generated, Selection, WSCError
from wsc.generation_api import build_generator, check_generator


class GenerationApiChecks(TestCase):
    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            build_generator('nope')

    def test_the_port_result_is_enforced_at_runtime(self):
        good = lambda material: Generated(Selection())
        self.assertIsInstance(check_generator(good, {}), Generated)
        with self.assertRaisesRegex(WSCError, 'generation_response_invalid'):
            check_generator(lambda material: {'selection': None}, {})

    def test_json_command_kind_constructs_the_bounded_transport(self):
        from wsc.generation import JsonCommandGenerator
        built = build_generator('json-command', ['tool'], legacy=False)
        self.assertIsInstance(built, JsonCommandGenerator)
        with self.assertRaises(Exception):
            build_generator('json-command', [])

    def test_facade_matches_direct_construction(self):
        from wsc.generation import JsonCommandGenerator
        direct = JsonCommandGenerator(['tool'], cwd='.', timeout=5)
        built = build_generator('json-command', ['tool'], cwd='.', timeout=5)
        self.assertEqual(vars(direct), vars(built))


if __name__ == '__main__':
    main()
