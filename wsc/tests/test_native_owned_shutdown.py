"""A completed parent can leave its stdout held by a live owned descendant."""
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'experiments'))
from native_rpc import NativeRPC
from native_owned_process import ProcessOwner,OwnedNativeRPC


@unittest.skipUnless(os.name=='nt','Windows Job ownership')
class ShutdownChecks(unittest.TestCase):
    def test_descendant_holding_stdout_cannot_block_owned_close(self):
        with tempfile.TemporaryDirectory() as d:
            rpc=NativeRPC.__new__(NativeRPC)
            rpc.stderr=(Path(d)/'stderr.txt').open('w',encoding='utf-8')
            code=('import subprocess,sys;sys.stdin.readline();'
                  'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"],'
                  'stdin=subprocess.DEVNULL,stdout=sys.stdout,stderr=sys.stderr);print(p.pid,flush=True)')
            rpc.proc=subprocess.Popen([sys.executable,'-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                stderr=rpc.stderr,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
            rpc.queue=queue.Queue();rpc.pending=[];rpc.counter=0
            owner=ProcessOwner();owner.attach(rpc.proc)
            threading.Thread(target=rpc._reader,daemon=True).start()
            rpc.proc.stdin.write('go\n');rpc.proc.stdin.flush()
            rpc.proc.wait(timeout=5)
            wrapper=OwnedNativeRPC.__new__(OwnedNativeRPC)
            wrapper.rpc=rpc;wrapper.owner=owner;wrapper.closed=False
            finished=threading.Event();errors=[]
            def close():
                try:wrapper.close()
                except BaseException as error:errors.append(error)
                finally:finished.set()
            worker=threading.Thread(target=close,daemon=True);worker.start()
            completed_without_external_cleanup=finished.wait(2)
            try:
                self.assertTrue(completed_without_external_cleanup,'owned close waited on stdout before terminating descendants')
                self.assertEqual([],errors)
                self.assertTrue(owner.receipt['empty_confirmed'])
                self.assertEqual([],owner.receipt['members_after_termination'])
            finally:
                owner.close();worker.join(timeout=5)


if __name__=='__main__':unittest.main()
