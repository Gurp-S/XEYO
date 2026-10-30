from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_indexed_checkpoint import IndexedCheckpointAdapter, expand_working_state
from native_incremental_candidate import prepare
from wsc import WSC, Store, events
from wsc.adapters.recorded_codex import RecordedCodexCheckpointAdapter
from wsc.contracts import Event, Usage, encode
from wsc.publication import check_evidence
from wsc.quote_selection import SelectionDraft
from wsc.source_reference_view import MODE, hydrate, project


class IndexedCheckpointChecks(unittest.TestCase):
    def make(self, root):
        core = WSC(Store(root / 'state.db', session_id='C', workspace=str(root)), access=lambda *args: True)
        text = '原始证据😀\n[WSC section t0 kind=clues source=- bytes=1]\nquote:" slash:\\ '
        core.ingest([Event('u', 'message', {'type': 'message', 'role': 'user',
            'content': [{'type': 'input_text', 'text': '用户任务'}]}, role='user', text='用户任务', observed_at='t0'),
            Event('o', 'observation', {'text': text, 'extra': 'original payload'}, text=text, observed_at='t1')])
        def generate(offered):
            return SelectionDraft(dict(source_ids=['s2'],
                new_understandings=[dict(text='理解😀', kind='hypothesis', sources=['s2'])],
                clues=[dict(text='线索', sources=['s2'])], span_refs=[offered['events'][1]['spans'][0]['ref']]), Usage())
        return core, generate

    def test_projection_roundtrip_binds_every_source_field(self):
        with tempfile.TemporaryDirectory() as folder:
            core, _ = self.make(Path(folder))
            source = list(core.capture().events)
            projected = project(source, MODE)
            body = dict(source_projection=MODE, sources=projected)
            self.assertEqual(hydrate(body, source)['sources'], source)
            self.assertNotIn('payload', projected[1])
            self.assertEqual(source[1]['payload']['extra'], 'original payload')
            for field, value in [('payload_ref', 'wrong'), ('observed_at', 't2'), ('text', 'changed')]:
                changed = deepcopy(body)
                changed['sources'][1][field] = value
                with self.assertRaises(ValueError):
                    hydrate(changed, source)
            changed = deepcopy(body)
            changed['sources'][0]['text'] = 'changed'
            with self.assertRaises(ValueError):
                hydrate(changed, source)
            self.assertIs(hydrate({'sources': source}, source)['sources'], source)

    def test_literal_sections_restore_identical_facts_and_reject_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core, generate = self.make(root)
            selected = prepare(core, core.capture(), None, root / 'cold', generate, source_projection=MODE)
            operation = core.stage(selected['view'], directory=root / 'exports', adapter=IndexedCheckpointAdapter())
            package = core.package(operation)
            check_evidence(core, package)
            with core.store.connect() as db:
                body = json.loads(db.execute('SELECT data FROM views WHERE id=?', (selected['view'],)).fetchone()[0])['body']
                source = events.rows(db)
            restored = hydrate(body, source)
            restored['excerpt_locators'] = package['excerpt_evidence']
            expected = RecordedCodexCheckpointAdapter().render(restored, source, package['binding']['cut'], package['evidence'],
                source_index=package['source_index'], understanding_index=package['understanding_index'])
            index = sum(row['kind'] == 'message' for row in body['sources'])
            text = package['items'][index]['content'][0]['text']
            projection = Path(package['adapter']['projection_evidence']['file_path'])
            metadata = json.loads(projection.read_text(encoding='utf8'))
            self.assertEqual(expand_working_state(text, metadata), json.loads(expected[index]['content'][0]['text']))
            self.assertEqual(package['items'][:index], expected[:index])
            self.assertEqual(package['items'][index+1:], expected[index+1:])
            with self.assertRaises(ValueError):
                expand_working_state(text.replace('理解😀', '理解X'), metadata)
            with self.assertRaisesRegex(ValueError, 'header_changed'):
                expand_working_state(text.replace('"model_records":', '"missing_records":', 1), metadata)
            changed = deepcopy(metadata)
            changed['fact_template']['kind'] = 'changed'
            with self.assertRaisesRegex(ValueError, 'metadata_changed'):
                expand_working_state(text, changed)
            projection.write_text(encode(changed), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'projection_index_changed'):
                check_evidence(core, package)

    def test_default_format_unchanged_and_projected_view_requires_capability(self):
        for enabled in (False, True):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                core, generate = self.make(root)
                selected = prepare(core, core.capture(), None, root / 'cold', generate,
                    **({'source_projection': MODE} if enabled else {}))
                if enabled:
                    with self.assertRaisesRegex(ValueError, 'adapter_source_projection_unsupported'):
                        core.stage(selected['view'], directory=root / 'exports', adapter=RecordedCodexCheckpointAdapter())
                else:
                    operation = core.stage(selected['view'], directory=root / 'exports', adapter=RecordedCodexCheckpointAdapter())
                    self.assertNotIn('source_projection', core.package(operation)['adapter'])


if __name__ == '__main__':
    unittest.main()
