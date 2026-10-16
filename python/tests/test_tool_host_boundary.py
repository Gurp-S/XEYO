"""Tool hosts are explicit, instance-scoped and inherited through delegation."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.abort import AbortController
from tools.host_services import ToolHostServices
from tools.catalog import build_default_registry, build_subagent_registry
from tools.job_tools import JobListTool, JobOutputTool


def test_tools_and_engine_have_no_transport_imports():
    root = Path(__file__).resolve().parents[1]
    violations = []
    files = [*root.joinpath('tools').rglob('*.py'), *root.joinpath('engine').rglob('*.py'),
             root/'common/workspace_git.py', root/'common/workspace_paths.py']
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            names = ([node.module or ''] if isinstance(node, ast.ImportFrom) else
                     [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            if any(n.split('.')[0] in {'server','cli','fastapi','uvicorn'} for n in names):
                violations.append(f'{path.relative_to(root)}:{node.lineno}')
    assert not violations, violations


def test_registry_injects_late_tools_and_keeps_schema_identity(tmp_path):
    services = ToolHostServices()
    bound = build_default_registry(cwd=str(tmp_path), host_services=services)
    plain = build_default_registry(cwd=str(tmp_path))
    assert bound.schemas() == plain.schemas()
    for name in ('Git','Bash','job_list','job_output','job_kill','XeyoUI'):
        assert bound.get(name)._host_services is services
    replacement = JobListTool()
    bound.register(replacement)
    assert replacement._host_services is services
    assert bound.schemas() == plain.schemas()
    child = build_subagent_registry(cwd=str(tmp_path), tool_names=['Git','Bash','job_list'],
                                   agent_id='worker', host_services=services)
    assert child.get('Git')._host_services is services
    assert child.host_services is services
    assert child.get('job_kill') is None  # Existing child capability restrictions remain.


@pytest.mark.asyncio
async def test_concurrent_tool_instances_keep_distinct_hosts(monkeypatch):
    from tools import job_tools
    monkeypatch.setattr(job_tools, '_session_id', lambda: 'same-owner')
    class Jobs:
        def __init__(self, marker): self.marker = marker
        def snapshot_list(self, sid):
            assert sid == 'same-owner'
            return [{'job_id':self.marker,'kind':'bash','status':'running','label':self.marker}]
    left, right = Jobs('left'), Jobs('right')
    results = await asyncio.gather(*[
        JobListTool(host_services=ToolHostServices(jobs=lambda jobs=jobs: jobs)).execute({},AbortController())
        for jobs in (left,right)])
    assert 'left' in results[0].content and 'right' not in results[0].content
    assert 'right' in results[1].content and 'left' not in results[1].content


@pytest.mark.asyncio
async def test_job_source_resolves_once_during_wait(monkeypatch):
    from tools import job_tools
    monkeypatch.setattr(job_tools, '_session_id', lambda: 'owner')
    calls = []
    class Jobs:
        reads = 0
        def change_token(self, jid, sid): return 0
        def read(self, jid, sid):
            self.reads += 1
            return ('first\n' if self.reads == 1 else 'last\n', self.reads,
                    'running' if self.reads == 1 else 'succeeded', False)
        async def wait_for_change(self, *args, **kwargs):
            current[0] = object()  # Host reset while this operation is waiting.
            return 1
        def snapshot_list(self, sid): return []
    original = Jobs()
    current = [original]
    def acquire():
        calls.append(1)
        return current[0]
    result = await JobOutputTool(host_services=ToolHostServices(jobs=acquire)).execute(
        {'job_id':'job-1','wait':True,'timeout_ms':1000}, AbortController())
    assert not result.is_error and 'first\nlast\n[status: succeeded]' in result.content
    assert calls == [1] and original.reads == 2


@pytest.mark.asyncio
async def test_unconfigured_tools_preserve_empty_and_fallback_paths(tmp_path):
    from tools.bash_tool.jobs_bridge import start_registry_job, adopt_registry_job
    assert (await JobListTool().execute({},AbortController())).content == '(no background jobs)'
    args = dict(command='unused',cwd=str(tmp_path),description=None,session_id='owner')
    assert start_registry_job(**args) is None
    assert adopt_registry_job(handle=object(),**args) is None
    def unavailable(): raise OSError('host unavailable')
    assert start_registry_job(jobs=unavailable,**args) is None
    assert adopt_registry_job(handle=object(),jobs=unavailable,**args) is None


@pytest.mark.asyncio
async def test_git_service_injection_and_shared_path_fence(tmp_path):
    from common.workspace_paths import resolve_in_workspace
    from server.workspace_fs import resolve_in_workspace as legacy
    from tools.git_tool import GitTool
    seen = []
    class Git:
        def read_git_status(self, cwd):
            seen.append(cwd)
            return {'repo':True,'branch':'injected','cwd':cwd}
    result = await GitTool(cwd=str(tmp_path),host_services=ToolHostServices(git=Git())).execute(
        {'action':'status'},AbortController())
    assert 'branch: injected' in result.content and seen == [str(tmp_path)]
    assert legacy is resolve_in_workspace
    with pytest.raises(PermissionError, match='outside workspace'):
        resolve_in_workspace(str(tmp_path),'../outside')


@pytest.mark.asyncio
async def test_gui_busy_state_uses_own_pool(tmp_path, monkeypatch):
    from server.engine_services import product_runtime_services
    from tools.xeyo_ui_tool import XeyoUITool
    from permissions.policy import current_surface, set_surface
    before = current_surface()
    set_surface('gui')
    try:
        busy = product_runtime_services(pool=SimpleNamespace(is_busy=lambda sid: True)).tools
        idle = product_runtime_services(pool=SimpleNamespace(is_busy=lambda sid: False)).tools
        payload = {'action':'send_to_session','session_id':'target','text':'local test payload'}
        denied = await XeyoUITool(str(tmp_path),host_services=busy).execute(payload,AbortController())
        allowed = await XeyoUITool(str(tmp_path),host_services=idle).execute(payload,AbortController())
        assert denied.is_error and denied.ui is None and 'busy' in denied.content
        assert not allowed.is_error and allowed.ui['action'] == 'send_to_session'
    finally:
        set_surface(before)


@pytest.mark.parametrize('entry',['http','cli','embedded'])
def test_product_and_embedded_factories_propagate_host_services(tmp_path,entry):
    if entry == 'http':
        from server.session_pool import SessionPool, ModelConfig
        from engine.scheduler import Task
        pool = SessionPool(cwd=str(tmp_path))
        engine = pool.get_or_create('owner',ModelConfig('fake','','','fake'))
        assert engine.config['tools'].host_services.sessions._pool is pool
        assert pool.scheduler_for('owner').registry_for(Task(id='test',desc='test',scope=[])).host_services is not None
    elif entry == 'cli':
        from cli.chat_cmd import build_chat_engine
        engine,_ = build_chat_engine(cwd=str(tmp_path),session_id='owner',provider='fake',model='fake',api_key='',base_url='')
    else:
        from engine.query_engine import build_default_engine
        from engine.runtime_services import RuntimeServices
        services = RuntimeServices(tools=ToolHostServices())
        engine = build_default_engine(cwd=str(tmp_path),model_backend='fake',runtime_services=services)
    registry = engine.config['tools']
    assert registry.get('Bash')._host_services is registry.host_services
    assert registry.get('job_output')._host_services is registry.host_services
    assert registry.get('Agent')._runtime_provider().host_services is registry.host_services


@pytest.mark.asyncio
async def test_subagent_runner_delivers_host_to_real_child_registry(tmp_path,monkeypatch):
    from engine.subagent_runner import run_subagent
    import tools.catalog as catalog
    services = ToolHostServices()
    captured = []
    original = catalog.build_subagent_registry
    class Captured(Exception): pass
    def capture(**kwargs):
        registry = original(**kwargs)
        captured.append(registry.get('Git')._host_services)
        raise Captured
    monkeypatch.setattr(catalog,'build_subagent_registry',capture)
    with pytest.raises(Captured):
        await run_subagent(workspace_root=tmp_path,agent_id='worker',task_prompt='test',
                           tool_whitelist=['Git'],model_client=SimpleNamespace(model='fake',provider='fake'),
                           prompt_assembler=object(),write_store=None,main_session_id='parent',
                           host_services=services)
    assert captured == [services]


@pytest.mark.asyncio
async def test_scheduler_passes_host_to_child_execution(tmp_path,monkeypatch):
    from engine.scheduler import Scheduler, Task
    from engine.subagent_runner import SubagentRuntime, SubagentRunResult
    services = ToolHostServices()
    runtime = SubagentRuntime(object(),object(),str(tmp_path),host_services=services)
    captured = []
    async def run(**kwargs):
        captured.append(kwargs['host_services'])
        return SubagentRunResult(conclusion='done')
    monkeypatch.setattr('engine.subagent_runner.run_subagent',run)
    scheduler = Scheduler(tmp_path,runtime_provider=lambda:runtime,main_session_id='parent')
    task = Task(id='test',desc='test',scope=[])
    assert scheduler.registry_for(task).host_services is services
    # Invoke the normal built-in runner without creating a second task scheduler.
    result = await scheduler._run_task(task)
    assert result.ok and captured == [services]
