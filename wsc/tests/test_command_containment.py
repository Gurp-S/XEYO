"""Real owned subprocesses: baseline leak vs suspended-root Job containment."""
from pathlib import Path
import ctypes
from ctypes import wintypes
import os
import sys
import tempfile
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wsc.generation import JsonCommandGenerator
from wsc.bounded_generation import BoundedJsonCommandGenerator
from wsc.contracts import WSCError


@unittest.skipUnless(os.name=='nt','Windows Job process-tree containment')
class CommandContainmentTests(unittest.TestCase):
    def handle(self,pid):
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
        kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT];kernel.TerminateProcess.restype=wintypes.BOOL
        kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
        return kernel,kernel.OpenProcess(0x100001,False,pid)

    def alive(self,pid,wait_ms=0):
        kernel,handle=self.handle(pid)
        if not handle:return False
        try:return kernel.WaitForSingleObject(handle,wait_ms)==258
        finally:kernel.CloseHandle(handle)

    def kill_owned_fixture(self,pid):
        kernel,handle=self.handle(pid)
        if handle:
            try:
                if kernel.WaitForSingleObject(handle,0)==258:
                    kernel.TerminateProcess(handle,137) # A terminating Job member can already reject another termination.
                    self.assertEqual(0,kernel.WaitForSingleObject(handle,5000))
            finally:kernel.CloseHandle(handle)

    def test_timeout_before_after_contains_descendant(self):
        observed=[]
        for constructor in (JsonCommandGenerator,BoundedJsonCommandGenerator):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);pidfile=root/'child.pid'
                child="from pathlib import Path; import os,time; Path("+repr(str(pidfile))+").write_text(str(os.getpid())); time.sleep(30)"
                program=root/'parent.py'
                program.write_text('import subprocess,sys,time\nsubprocess.Popen([sys.executable,"-c",'+repr(child)+'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\ntime.sleep(30)\n',encoding='utf-8')
                generator=constructor([sys.executable,str(program)],timeout=.5,**({'legacy':True} if constructor is JsonCommandGenerator else {}))
                pid=None
                try:
                    with self.assertRaisesRegex(WSCError,'generation_command_timeout'):generator({})
                    self.assertTrue(pidfile.exists(),'child did not reach the owned fixture')
                    pid=int(pidfile.read_text());observed.append(self.alive(pid,1000 if isinstance(generator,BoundedJsonCommandGenerator) else 0))
                    if isinstance(generator,BoundedJsonCommandGenerator):self.assertTrue(generator.cleanup['empty_confirmed'])
                finally:
                    if pid is None and pidfile.exists():pid=int(pidfile.read_text())
                    if pid is not None:self.kill_owned_fixture(pid)
        self.assertEqual([True,False],observed)

    def test_live_both_stream_budgets_and_valid_transport(self):
        for stream,code in (('stdout','generation_output_budget_exhausted'),('stderr','generation_stderr_budget_exhausted')):
            generator=BoundedJsonCommandGenerator([sys.executable,'-c',f'import sys,time; sys.{stream}.buffer.write(b"x"*100000); sys.{stream}.flush(); time.sleep(5)'],timeout=2,max_output_bytes=64,max_stderr_bytes=64)
            with self.assertRaisesRegex(WSCError,code):generator({})
            self.assertTrue(generator.cleanup['empty_confirmed'])
        generator=BoundedJsonCommandGenerator([sys.executable,'-c','print(\'{"selection":{},"usage":{"output":0}}\')'],timeout=2)
        self.assertEqual(0,generator({}).usage.output)
        self.assertTrue(generator.cleanup['empty_confirmed'])

    def test_inherited_input_handle_does_not_mask_timeout_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);pidfile=root/'child.pid'
            child="from pathlib import Path; import os,time; Path("+repr(str(pidfile))+").write_text(str(os.getpid())); time.sleep(30)"
            program=root/'parent.py'
            program.write_text('import subprocess,sys,time\nsubprocess.Popen([sys.executable,"-c",'+repr(child)+'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\ntime.sleep(30)\n',encoding='utf-8')
            generator=BoundedJsonCommandGenerator([sys.executable,str(program)],timeout=.5)
            try:
                with self.assertRaisesRegex(WSCError,'generation_command_timeout'):generator({})
                self.assertTrue(generator.cleanup['empty_confirmed'])
                if pidfile.exists():self.assertFalse(self.alive(int(pidfile.read_text()),1000))
            finally:
                if pidfile.exists():self.kill_owned_fixture(int(pidfile.read_text()))

    def test_windows_default_generator_uses_validated_containment(self):
        generator=JsonCommandGenerator([sys.executable,'-c','print(\'{"selection":{}}\')'])
        self.assertFalse(generator.legacy);generator({})
        self.assertTrue(generator.cleanup['empty_confirmed'])


if __name__=='__main__':unittest.main()
