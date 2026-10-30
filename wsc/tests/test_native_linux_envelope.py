from pathlib import Path
from unittest import TestCase,main
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from native_linux_envelope import command

RUNTIME='/mnt/host/d/tools/codex-0.165.0-alpha.1.2-linux-x64'
ACTOR='/mnt/host/d/run/actor-root'


class EnvelopeChecks(TestCase):
    def test_host_roots_cannot_replace_owned_actor_tree(self):
        for root in ('/','/mnt','/mnt/host','/mnt/host/d','/usr'):
            with self.assertRaises(ValueError):command(RUNTIME,root)

    def test_relative_or_parent_traversal_cannot_add_an_ambient_root(self):
        for root in ('actor-root','/mnt/host/d/run/../actor-root'):
            with self.assertRaisesRegex(ValueError,'path_invalid'):command(RUNTIME,root)

    def test_native_runtime_cannot_enclose_writable_actor(self):
        with self.assertRaisesRegex(ValueError,'mount_overlap'):
            command(RUNTIME,RUNTIME+'/actor-root')

    def test_only_actor_tree_is_writable_bind_and_native_runtime_is_readonly(self):
        args=command(RUNTIME,ACTOR)
        binds=[args[i+1:i+3] for i,v in enumerate(args) if v=='--bind']
        readonly=[args[i+1:i+3] for i,v in enumerate(args) if v=='--ro-bind']
        self.assertEqual([[ACTOR,'/work']],binds)
        self.assertIn([RUNTIME,'/opt/codex'],readonly)
        self.assertNotIn(['/mnt/host','/mnt/host'],readonly)


if __name__=='__main__':main()
