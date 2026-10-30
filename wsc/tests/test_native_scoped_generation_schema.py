from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_incremental_generation import output_schema


class ScopedSchemaChecks(unittest.TestCase):
    def test_scope_can_name_its_domain_without_changing_default_schema(self):
        offered = dict(events=[], previous_excerpts=[], understandings=[])
        default = output_schema(offered)
        scoped = output_schema(offered, scoped_manifest_bindings=True)
        old = default['properties']['new_understandings']['items']['properties']['scope']
        new = scoped['properties']['new_understandings']['items']['properties']['scope']
        self.assertEqual(set(old['properties']), {'source_manifest_sha256'})
        self.assertEqual(set(new['properties']), {'source_manifest_sha256', 'manifest_scope', 'delivery_stage'})
        self.assertEqual(new['type'], ['object', 'null'])
        # Stage and hash values are model output, not forced expected answers.
        self.assertNotIn('enum', new['properties']['delivery_stage'])
        self.assertEqual(default['$defs'], scoped['$defs'])
