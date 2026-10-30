from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'benchmarks'))
from acceptance_matrix_v1.workspace_runtime import verify_runtime,provision_pair,environment_facts


class RuntimeBindingChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=self.root/'source';self.source.mkdir()
        payload={'python.exe':b'fixture-exe','python311.dll':b'fixture-dll','stdlib.zip':b'fixture-stdlib',
                 'python311._pth':b'stdlib.zip\nDLLs\n.\n'}
        self.files={}
        for name,value in payload.items():
            (self.source/name).write_bytes(value)
            self.files[name]=dict(bytes=len(value),sha256=sha256(value).hexdigest())
        self.manifest=dict(version='3.11.9',files=self.files,bytes=sum(v['bytes'] for v in self.files.values()))
        self.write_manifest()
    def write_manifest(self):
        (self.source/'runtime-manifest.json').write_text(json.dumps(self.manifest),encoding='utf-8')
    def tearDown(self):self.temp.cleanup()
    def test_identical_copies_and_neutral_facts(self):
        out=self.root/'pair'
        for name in ('Bprime','C'):(out/name).mkdir(parents=True)
        binding=provision_pair(self.source,out)
        self.assertEqual(verify_runtime(out/'Bprime/.runtime'),verify_runtime(out/'C/.runtime'))
        self.assertEqual('.runtime/python.exe',environment_facts(binding)['python']['executable'])
    def test_changed_executable_rejected(self):
        (self.source/'python.exe').write_bytes(b'tamper')
        with self.assertRaisesRegex(ValueError,'runtime_asset_changed'):verify_runtime(self.source)
    def test_extra_file_rejected(self):
        (self.source/'answer.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'runtime_inventory_changed'):verify_runtime(self.source)
    def test_path_escape_rejected(self):
        self.files['../outside']=dict(bytes=0,sha256=sha256(b'').hexdigest());self.write_manifest()
        with self.assertRaises(ValueError):verify_runtime(self.source)
    def test_external_search_path_rejected_even_when_rehashed(self):
        value=b'C:/outside\n';(self.source/'python311._pth').write_bytes(value)
        self.files['python311._pth']=dict(bytes=len(value),sha256=sha256(value).hexdigest())
        self.manifest['bytes']=sum(v['bytes'] for v in self.files.values());self.write_manifest()
        with self.assertRaisesRegex(ValueError,'runtime_search_path_changed'):verify_runtime(self.source)


if __name__=='__main__':unittest.main()
