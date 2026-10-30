from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from native_host_controls import bootstrap_items, settings, FEATURE_OVERRIDES


class HostControlTests(unittest.TestCase):
    def test_only_envelope_identity_is_ignored(self):
        items = [dict(type='additional_tools', id='at_old', tools=[dict(name='exec', id='schema-id', description='original')]),
                 dict(type='message', id='msg_old', role='developer', content=[dict(type='input_text',text='facts')])]
        other = deepcopy(items)
        other[0]['id'], other[1]['id'] = 'at_new', 'msg_new'
        self.assertEqual(bootstrap_items(items,'.'),bootstrap_items(other,'.'))
        other[0]['tools'][0]['id']='different-schema-id'
        self.assertNotEqual(bootstrap_items(items,'.'),bootstrap_items(other,'.'))

    def test_tool_definition_and_user_text_stay_exact(self):
        items=[dict(type='additional_tools',id='at',tools=[dict(name='exec',description='original')])]
        for field in ('name','description'):
            other=deepcopy(items)
            other[0]['tools'][0][field]='changed'
            self.assertNotEqual(bootstrap_items(items,'.'),bootstrap_items(other,'.'))
        items=[dict(type='message',role='user',content=[dict(type='input_text',text='id=at_original')])]
        self.assertEqual(bootstrap_items(items,'.'),items)

    def test_override_is_opt_in_and_exact(self):
        reg=dict(effort='max')
        self.assertEqual(settings(reg),['features.multi_agent=false','model_reasoning_effort="max"'])
        actual=settings(dict(**reg,host_feature_overrides=FEATURE_OVERRIDES))
        self.assertEqual(actual[-2:],['features.recommended_plugins=false','features.tool_suggest=false'])
        with self.assertRaisesRegex(ValueError,'unregistered'):
            settings(dict(**reg,host_feature_overrides={'plugins':False}))


if __name__=='__main__':
    unittest.main()
