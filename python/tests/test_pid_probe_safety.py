"""判活不能杀掉仍在运行的对象；尤其不能在 Windows 发零信号。"""

import os
import subprocess
import sys

import pytest

from engine.process_ledger import _pid_alive as ledger_alive
from memory.nightshift import _pid_alive as memory_alive


@pytest.mark.parametrize("probe", [ledger_alive, memory_alive])
def test_process_probe_keeps_live_child_running(probe):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert probe(os.getpid())
        assert probe(child.pid)
        assert probe(child.pid)
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=5)
    assert not probe(child.pid)
