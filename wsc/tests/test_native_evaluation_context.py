from pathlib import Path
from tempfile import TemporaryDirectory
import os
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from native_evidence import save, manifest, file_hash
from native_evaluation_context import capture, match, from_bound_probe
from native_visual_source_observation import from_probe


class ExecutionContextChecks(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.gui = self.root / 'gui'
        (self.gui / 'src').mkdir(parents=True)
        (self.gui / 'src/panel.tsx').write_text('export const value=1;', encoding='utf8')
        for name in ('package.json', 'package-lock.json'):
            (self.gui / name).write_text('{}', encoding='utf8')
        self.fixture = self.root / 'fixture'
        (self.fixture / 'harness').mkdir(parents=True)
        self.main = self.fixture / 'harness/main.tsx'
        self.main.write_text("import {A3SnapshotPanel} from '@/components/A3SnapshotPanel';\n<A3SnapshotPanel active />", encoding='utf8')
        self.probe = self.root / 'probe.mjs'
        self.probe.write_text('// probe', encoding='utf8')
        self.context = self.capture()
        save(self.root / 'context.json', self.context)
        save(self.root / 'registration.json', dict(source_manifest=manifest(self.gui / 'src'),
            package_sha256=file_hash(self.gui / 'package.json'), lock_sha256=file_hash(self.gui / 'package-lock.json'),
            scenario='normal', viewport=dict(width=1440, height=1000)))
        save(self.root / 'result.json', dict(source_unchanged=True, check_executed=True, errors=[],
            clipping_observed=False, hasUserScrollableAncestor=True, hasClippingAncestor=True, changedScroll=True,
            initial=dict(reportHeight=1587, viewportHeight=1000), browser='fixture-browser'))

    def capture(self):
        return capture(self.gui, self.fixture, self.probe, entry='production_panel',
            scenario='normal', viewport=dict(width=1440, height=1000))

    def load(self):
        return from_bound_probe(self.gui, self.fixture, self.probe,
            self.root / 'context.json', self.root / 'registration.json', self.root / 'result.json')

    def test_same_source_different_host_is_not_same_execution(self):
        self.main.write_text("import {UsagePageBody} from '@/components/A3SnapshotPanel';\n<UsagePageBody active />", encoding='utf8')
        inner = capture(self.gui, self.fixture, self.probe, entry='inner_body', scenario='normal',
            viewport=dict(width=1440, height=1000))
        self.assertEqual(self.context['gui'], inner['gui'])
        self.assertFalse(match(self.context, inner)['equal'])
        with self.assertRaisesRegex(ValueError, 'entry_mismatch'):
            self.load()

    def test_unchanged_context_exports_facts_and_keeps_old_default(self):
        value = self.load()
        self.assertFalse(value['clipping_observed'])
        self.assertEqual(self.context, value['execution_context'])
        self.assertFalse(value['full_visual_qualification'])
        old = from_probe(self.gui, self.root / 'registration.json', self.root / 'result.json')
        self.assertEqual('source_bound_visual_observation_v1', old['kind'])
        self.assertNotIn('execution_context', old)

    def test_host_or_probe_byte_change_rejects_old_receipt(self):
        for path in (self.probe, self.main):
            original = path.read_bytes()
            path.write_bytes(original + b'\n// changed')
            with self.assertRaisesRegex(ValueError, 'execution_context_changed'):
                self.load()
            path.write_bytes(original)

    def test_source_change_rejects_old_receipt(self):
        (self.gui / 'src/panel.tsx').write_text('export const value=2;', encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'execution_context_changed'):
            self.load()

    def test_probe_scenario_mismatch_is_rejected(self):
        from native_evidence import read
        path = self.root / 'registration.json'
        value = read(path)
        value['viewport']['width'] = 390
        import json
        path.write_text(json.dumps(value), encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'probe_context_mismatch'):
            self.load()

    def test_after_the_fact_context_cannot_upgrade_old_receipt(self):
        ns = max((self.root / name).stat().st_mtime_ns for name in ('registration.json', 'result.json'))
        os.utime(self.root / 'context.json', ns=(ns + 1000000000, ns + 1000000000))
        with self.assertRaisesRegex(ValueError, 'registered_after_probe'):
            self.load()

    def test_private_provenance_path_is_not_executable_host_identity(self):
        # Metadata can differ after relocation; every executable byte still counts.
        (self.fixture / 'evaluation-host-binding.json').write_text('{"upstream_root":"B"}', encoding='utf8')
        self.assertTrue(match(self.context, self.capture())['equal'])
        (self.fixture / 'evaluation-host-binding.json').write_text('{"upstream_root":"C"}', encoding='utf8')
        self.assertTrue(match(self.context, self.capture())['equal'])
        (self.fixture / 'public-contract.json').write_text('{"changed":true}', encoding='utf8')
        self.assertFalse(match(self.context, self.capture())['equal'])


if __name__ == '__main__':
    unittest.main()
