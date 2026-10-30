"""Error text must not carry host paths to stderr or into status."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch
import contextlib
import io
import json
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src')]
from wsc import WSC, Store, WSCError
from wsc.cli import main
from wsc.redaction import redact


class RedactionChecks(TestCase):
    def test_windows_path_becomes_a_placeholder(self):
        self.assertEqual('failed at <path>', redact(r'failed at C:\Users\me\secret\a.txt'))

    def test_a_known_root_is_replaced_by_name(self):
        text = redact(r'cannot open D:\lea\work\wsc\s.db', roots=[r'D:\lea\work'])
        self.assertIn('<workspace>', text)
        self.assertNotIn('lea', text)

    def test_plain_codes_pass_through_and_text_is_capped(self):
        self.assertEqual('generation_command_timeout', redact('generation_command_timeout'))
        self.assertEqual(240, len(redact('x' * 400)))

    def test_cli_error_payload_has_no_absolute_path(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        core = WSC(Store(root / 's.db', session_id='s', workspace=str(root)),
                   access=lambda *a: True)
        core.ingest([])
        output, error = io.StringIO(), io.StringIO()
        with patch.object(WSC, 'status', side_effect=WSCError(f'broken {root / "secret"}')), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(['--db', str(core.store.path), '--session', 's', '--workspace',
                           str(root), 'status'])
        self.assertEqual(2, status)
        payload = json.loads(error.getvalue())
        self.assertNotIn(str(root), payload['error'])
        self.assertIn('<workspace>', payload['error'])

if __name__ == '__main__':
    main()
