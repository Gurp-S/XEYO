from pathlib import Path
import sys,unittest,copy,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks/deterministic_v1'))
from blackbox_group_runner import compare_histories,answer_schema,fork_registration,guard_trunk
from hashlib import sha256
from types import SimpleNamespace


class GroupRunnerTests(unittest.TestCase):
    def test_only_native_transport_changes_are_admitted(self):
        first=[dict(type='message',role='user',id='first',content=[dict(type='input_text',text='same original')])]
        second=copy.deepcopy(first);second[0]['id']='second';second[0]['internal_chat_message_metadata_passthrough']={'create_time':1}
        proof=compare_histories([first,second],str(Path.cwd()))
        self.assertNotEqual(*proof['raw_sha256'])
        for field,value in [('content',[dict(type='input_text',text='changed instruction')]),('role','assistant')]:
            altered=copy.deepcopy(second);altered[0][field]=value
            with self.assertRaisesRegex(ValueError,'histories_differ'):compare_histories([first,altered],str(Path.cwd()))
        altered=copy.deepcopy(second);altered.append(dict(type='additional_tools',tools=[{'name':'extra'}]))
        with self.assertRaisesRegex(ValueError,'histories_differ'):compare_histories([first,altered],str(Path.cwd()))
    def test_probe_guard_rejects_source_changes_and_ancestry_is_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trunk';path.write_bytes(b'original')
            parent=SimpleNamespace(opened=dict(thread=dict(id='parent',path=str(path))),registration=dict(parent_paths={'grandparent':'sealed-path'}))
            reg=fork_registration({'model':'fixed'},parent)
            self.assertEqual({'grandparent':'sealed-path','parent':str(path)},reg['parent_paths'])
            checksum=sha256(path.read_bytes()).hexdigest();guard_trunk(parent,checksum)
            path.write_bytes(b'probe injected')
            with self.assertRaisesRegex(ValueError,'mutated_source_trunk'):guard_trunk(parent,checksum)
    def test_output_schema_has_no_answer_or_enum_injection(self):
        import json
        schema=answer_schema();self.assertNotIn('enum',json.dumps(schema));self.assertNotIn('expected',json.dumps(schema))
        self.assertEqual(['answers'],schema['required'])


if __name__=='__main__':unittest.main()
