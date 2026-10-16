"""Owned real TCP processes and isolated data for GUI/TUI/soak validation."""
import json
import os
from pathlib import Path
import socket
import signal
import subprocess
import sys
import time

import httpx

PYTHON = Path(__file__).resolve().parents[2]
REPO = PYTHON.parent


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class Lab:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.workspace = self.directory / 'workspace'
        self.workspace.mkdir(exist_ok=True)
        self.backend_port, self.model_port = port(), port()
        self.base = f'http://127.0.0.1:{self.backend_port}'
        self.model_base = f'http://127.0.0.1:{self.model_port}/v1'
        self.children, self.logs = [], []
        self.owned_pids = set()
        self.env = dict(os.environ)
        from engine.env_switches import isolation_pins
        for name, value in isolation_pins():
            if value is None:
                self.env.pop(name, None)
            else:
                self.env[name] = value
        self.env.update(PYTHONIOENCODING='utf-8', XEYO_ALLOW_LOCAL_MODEL='1', XEYO_ALLOW_FAKE_MODEL='1',
                        XEYO_AGENT_RUNTIME_V2='1', XEYO_GOAL_AUTO_CREATE='0', XEYO_NO_PREWARM='1',
                        XEYO_CWD=str(self.workspace), XEYO_HTTP_HOST='127.0.0.1', XEYO_HTTP_PORT=str(self.backend_port),
                        XEYO_PORT_FILE=str(self.directory/'backend-port.json'))
        self.env['XEYO_TEST_UPSTREAM'] = self.model_base
        for name, folder in [('HOME','home'),('SESSIONS_DIR','sessions'),('USAGE_DIR','usage'),('SPILL_DIR','spill'),
                             ('METRICS_DIR','metrics'),('JOURNAL_DIR','journal'),('SNAPSHOTS_DIR','snapshots')]:
            self.env['XEYO_'+name] = str(self.directory/folder)
        # Allow this explicit local endpoint for browser requests.
        home = self.directory/'home'
        home.mkdir(exist_ok=True)
        (home/'settings.json').write_text(json.dumps({'providers': {'local': {'base_url': self.model_base}}}), encoding='utf-8')
        if not (self.workspace/'.git').exists():
            self.git('init')
            self.git('config', 'user.name', 'XEYO Network Test')
            self.git('config', 'user.email', 'test@local')
            (self.workspace/'.gitignore').write_text('.xeyo/\n.xy-shadow-git/\n.tmp/\n')
            (self.workspace/'f.txt').write_text('fixture base\n')
            self.git('add', '.')
            self.git('commit', '-m', 'test fixture')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.workspace, capture_output=True, check=True).stdout

    def launch(self, args, log):
        stream = (self.directory/log).open('ab')
        self.logs.append(stream)
        child = subprocess.Popen(args, cwd=PYTHON, env=self.env, stdin=subprocess.DEVNULL,
            stdout=stream, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.children.append(child)
        return child

    def start(self):
        self.model = self.launch([sys.executable, '-m', 'tests.soak_support.upstream', '--port', str(self.model_port), '--directory', str(self.directory)], 'upstream.log')
        self.ready(f'http://127.0.0.1:{self.model_port}/health', self.model)
        self.model_pid = httpx.get(f'http://127.0.0.1:{self.model_port}/health').json()['pid']
        self.owned_pids.add(self.model_pid)
        self.restart()
        return self

    def restart(self):
        self.backend = self.launch([sys.executable, '-m', 'tests.soak_support.server'], 'backend.log')
        self.ready(self.base+'/health', self.backend)
        self.backend_pid = json.loads(Path(self.env['XEYO_PORT_FILE']).read_text())['pid']
        self.owned_pids.add(self.backend_pid)
        self.save()

    def save(self):
        (self.directory/'lab.json').write_text(json.dumps({'base': self.base, 'model_base': self.model_base,
            'workspace': str(self.workspace), 'backend_pid': self.backend_pid, 'upstream_pid': self.model_pid,
            'port_file': self.env['XEYO_PORT_FILE']}, indent=2), encoding='utf-8')

    @staticmethod
    def ready(url, child):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError(f'fixture exited {child.returncode}: {url}')
            try:
                if httpx.get(url, timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(.1)
        raise TimeoutError(url)

    def crash(self):
        os.kill(self.backend_pid, signal.SIGTERM)
        self.owned_pids.discard(self.backend_pid)
        self.backend.wait(timeout=10)

    def close(self):
        for pid in self.owned_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        for child in reversed(self.children):
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=15)
        for stream in self.logs:
            stream.close()
