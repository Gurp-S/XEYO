from pathlib import Path
import json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from native_selector_runtime import configure,PROFILE,FACTS


class SelectorRuntimeTests(unittest.TestCase):
    def test_registered_profile_is_private_and_neutral(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'runtime';flags=configure(path,PROFILE)
            self.assertEqual(FACTS,json.loads((path/'selector-facts.json').read_text()))
            self.assertIn('memories.use_memories=false',flags)
            self.assertIn('features.shell_tool=false',flags)
            with self.assertRaises(FileExistsError):configure(path,PROFILE)
            unregistered=Path(root)/'other'
            with self.assertRaisesRegex(ValueError,'unregistered'):configure(unregistered,'unknown')
            self.assertFalse(unregistered.exists())


if __name__=='__main__':unittest.main()
