from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments'))
sys.path.insert(0, str(ROOT / 'src'))
from native_incremental_candidate import prepare, frontier, admit_rendered, compile_draft
from wsc import WSC, Store
from wsc.contracts import Event, Usage, encode
from wsc.quote_selection import SelectionDraft
from wsc.adapters.recorded_codex import RecordedCodexCheckpointAdapter


class IncrementalCandidateChecks(unittest.TestCase):
    def make(self, root):
        core = WSC(Store(root / 'state.db', session_id='lane-C', workspace=str(root)), access=lambda *args: True)
        core.ingest([Event('user-task', 'message', {'type': 'message', 'role': 'user',
            'content': [{'type': 'input_text', 'text': '费用未知与真实零分开显示。'}]},
            role='user', text='费用未知与真实零分开显示。', observed_at='t0')])
        return core

    def test_three_exports_reuse_exact_evidence_without_nested_messages(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core = self.make(root)
            previous = None
            sizes = []
            for index in range(3):
                content = '阶段' + str(index) + ' ' + ('archived-large-text ' * 8000)
                core.ingest([Event('result-' + str(index), 'observation', {'text': content}, text=content, observed_at=f't{index+1}')])

                def generate(offered):
                    new = [e for e in offered['events'] if e['text_in_frontier'] and e['kind'] == 'observation'][-1]
                    old_refs = [r['ref'] for r in offered['understandings']]
                    return SelectionDraft(dict(source_ids=[], understanding_refs=old_refs,
                        new_understandings=[dict(text='阶段事实' + str(index), kind='observation_interpretation', sources=[new['id']])],
                        clues=[], span_refs=[new['spans'][0]['ref']] if previous is None else [],
                        retained_excerpt_keys=[] if previous is None else [previous['excerpts'][0]['key']]), Usage(1, 0, 1))

                outcome = prepare(core, core.capture(), previous, root / 'cold', generate)
                if previous:
                    old = next(e for e in outcome['offered']['events'] if e['id'] == 's2')
                    self.assertFalse(old['text_in_frontier'])
                    self.assertEqual(old['spans'], [])
                    self.assertTrue(Path(old['cold_source']['path']).is_file())
                    self.assertEqual(outcome['continuation']['excerpts'], previous['excerpts'])
                operation = core.stage(outcome['view'], directory=root / f'export-{index}',
                    archive_directory=root / 'objects', adapter=RecordedCodexCheckpointAdapter())
                package = admit_rendered(core.package(operation))
                rendered = encode(package['items'])
                self.assertNotIn(content, rendered)
                self.assertEqual(sum(i.get('role') == 'user' for i in package['items']), 1)
                sizes.append(len(rendered.encode()))
                previous = outcome['continuation']
                # This is an export-only check, not a fabricated host installation.
                core.discard(operation)
            self.assertLess(max(sizes), 15000)

    def test_old_record_can_be_revised_without_relabeling_old_observation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core = self.make(root)
            core.ingest([Event('check-h1', 'observation', {'manifest': 'h1', 'passed': True},
                text='h1 检查通过', observed_at='original-check-time')])
            one = prepare(core, core.capture(), None, root / 'cold', lambda offered: SelectionDraft(dict(
                new_understandings=[dict(text='h1已通过', kind='hypothesis', sources=['s2'], scope={'manifest': 'h1'})],
                span_refs=[offered['events'][1]['spans'][0]['ref']]), Usage()))
            prior = core.capture().understandings[0]
            core.ingest([Event('check-h2', 'observation', {'manifest': 'h2', 'passed': False}, text='h2 检查失败', observed_at='later-time')])
            two = prepare(core, core.capture(), one['continuation'], root / 'cold', lambda offered: SelectionDraft(dict(
                new_understandings=[dict(id=prior['id'], expected_revision=1, text='h2失败，h1回执属于旧版',
                    kind='hypothesis', sources=['s2', 's3'], scope={'manifest': 'h2'})],
                retained_excerpt_keys=[one['continuation']['excerpts'][0]['key']]), Usage()))
            self.assertEqual(len(two['continuation']['understanding_refs']), 1)
            new = next(r for r in core.capture().understandings if r['ref'] == two['continuation']['understanding_refs'][0])
            self.assertEqual(new['revision'], 2)
            self.assertEqual(new['previous'], prior['ref'])
            material, offered = frontier(core, core.capture(), two['continuation'], root / 'cold')
            self.assertEqual(offered['previous_excerpts'][0]['observed_at'], 'original-check-time')
            self.assertEqual(offered['previous_excerpts'][0]['text'], 'h1 检查通过')

    def test_cross_lane_previous_state_is_rejected_before_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core = self.make(root)
            previous = dict(cut=1, session_id='other', workspace=str(root), source_digest='wrong')
            with self.assertRaisesRegex(ValueError, 'binding_changed'):
                frontier(core, core.capture(), previous, root / 'cold')

    def test_failed_selection_keeps_known_generation_usage_and_no_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core = self.make(root)
            calls = []
            def bad(offered):
                calls.append(1)
                return SelectionDraft(dict(retained_excerpt_keys=['missing']), Usage(7, 2, 3))
            with self.assertRaisesRegex(ValueError, 'excerpt_missing'):
                prepare(core, core.capture(), None, root / 'cold', bad)
            with self.assertRaises(ValueError):
                prepare(core, core.capture(), None, root / 'cold', bad)
            self.assertEqual(len(calls), 1)
            usage = core.status()['usage']['attempts']
            self.assertEqual(len(usage), 1)
            self.assertEqual(usage[0]['status'], 'failed')
            self.assertEqual(usage[0]['data']['input_uncached'], 7)

    def test_previous_excerpt_hash_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core = self.make(root)
            one = prepare(core, core.capture(), None, root / 'cold', lambda offered: SelectionDraft(dict(
                span_refs=[offered['events'][0]['spans'][0]['ref']]), Usage()))
            previous = json.loads(json.dumps(one['continuation']))
            previous['excerpts'][0]['text_sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'excerpt_text_changed'):
                frontier(core, core.capture(), previous, root / 'cold')

    def test_displayed_full_identity_and_short_alias_choose_identical_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core = self.make(root)
            material, offered = frontier(core, core.capture(), None, root / 'cold')
            one = compile_draft(material, dict(source_ids=['s1'], clues=[dict(text='same', sources=['s1'])]))
            two = compile_draft(material, dict(source_ids=['user-task'], clues=[dict(text='same', sources=['user-task'])]))
            self.assertEqual(one, two)
            with self.assertRaisesRegex(ValueError, 'not_offered'):
                compile_draft(material, dict(source_ids=['native:invented']))

    def test_ambiguous_displayed_identity_is_rejected_before_model_call(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core = self.make(root)
            core.ingest([Event('s1', 'observation', {'text': 'different source'}, text='different source')])
            calls = []
            with self.assertRaisesRegex(ValueError, 'identity_ambiguous'):
                prepare(core, core.capture(), None, root / 'cold', lambda offered: calls.append(offered))
            self.assertEqual(calls, [])

    def test_previous_clues_and_source_choices_are_visible_without_auto_carry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core = self.make(root)
            first = prepare(core, core.capture(), None, root / 'cold', lambda offered: SelectionDraft(dict(
                source_ids=['s1'], clues=[dict(text='此前解释', sources=['s1'])]), Usage()))
            core.ingest([Event('new', 'observation', {'text':'new'}, text='new')])
            seen = []
            def drop(offered):
                seen.append(offered['previous_selection'])
                return SelectionDraft(dict(clues=[]), Usage())
            second = prepare(core, core.capture(), first['continuation'], root / 'cold', drop)
            self.assertEqual(seen[0]['clues'][0]['text'], '此前解释')
            self.assertEqual(seen[0]['source_ids'], ['user-task'])
            with core.store.connect() as db:
                body = json.loads(db.execute('SELECT data FROM views WHERE id=?', (second['view'],)).fetchone()[0])['body']
            self.assertEqual(body['clues'], [])


if __name__ == '__main__':
    unittest.main()
