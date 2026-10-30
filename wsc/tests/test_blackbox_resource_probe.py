from pathlib import Path
from types import SimpleNamespace
from hashlib import sha256
import sys,unittest,tempfile,shutil,subprocess,json
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'benchmarks/deterministic_v1'),str(Path(__file__).resolve().parents[1]/'experiments')]
from blackbox_resource_probe import verify_paths


class ResourceProbeTests(unittest.TestCase):
    def test_large_manifest_short_command_and_real_hash_failure(self):
        node=shutil.which('node')
        if not node:self.skipTest('Node unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'data';path.write_bytes('证据'.encode());commands=[]
            class Server:
                def call(self,method,params,timeout):
                    commands.append(params['command'])
                    done=subprocess.run(params['command'],capture_output=True,text=True,timeout=timeout)
                    return dict(exitCode=done.returncode,stdout=done.stdout,stderr=done.stderr)
            session=SimpleNamespace(server=Server(),registration=dict(workspace=str(root),node_executable=node))
            entries=[dict(path=str(path),sha256=sha256(path.read_bytes()).hexdigest())]*1000
            result=verify_paths(session,entries,root/'pass.json');output=json.loads(result['stdout'])
            self.assertEqual(1000,output['files']);self.assertEqual(0,output['failure_count'])
            self.assertLess(sum(map(len,commands[0])),6000)
            entries[0]={**entries[0],'sha256':'0'*64}
            with self.assertRaisesRegex(ValueError,'not_accessible'):verify_paths(session,entries,root/'failure.json')
            self.assertTrue((root/'failure.json').exists())


if __name__=='__main__':unittest.main()
