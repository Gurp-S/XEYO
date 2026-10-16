"""Recovery attribution excludes produced answers and full-source controls."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals import wsc_minimal_recovery_trial as trial


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['relative', 'forward_slashes', 'dot_path', 'artifact_directory', 'cold', 'full'])
async def test_native_branch_attributes_only_cold_evidence(tmp_path, monkeypatch, mode):
    work=tmp_path/'work'
    output=work/'artifacts'/'result.json'
    source=work/'cold'/'original.txt'
    source.parent.mkdir(parents=True)
    source.write_text('KNOWN_SOURCE',encoding='utf-8')
    monkeypatch.setattr(trial,'ROOT',tmp_path)
    monkeypatch.setattr(trial.e,'CLIENT',trial.d.CountedClient(api_key='not-sent',model='deepseek-flash',thinking='disabled'))
    monkeypatch.setattr(trial.e,'tokens',lambda *args:1)
    requested={
        'relative':'artifacts/result.json',
        'forward_slashes':output.as_posix(),
        'dot_path':'artifacts/../artifacts/result.json',
        'artifact_directory':'artifacts',
        'cold':'cold/original.txt',
        'full':'cold/original.txt',
    }[mode]
    async def actor(model,state,schemas,sink,cold,**kwargs):
        # No model or tool transport: only the existing branch's accounting is under test.
        output.write_text(json.dumps({'value':'KNOWN_SOURCE'}),encoding='utf-8')
        sink.attempts.append({'file_path':str(output)})
        tool='Grep' if mode=='artifact_directory' else 'Read'
        state.update(completed=True,phase='completed',requests_attempted=1,activity=[
            {'tool':tool,'input':{'path' if tool=='Grep' else 'file_path':requested},
             'result':{'content':'KNOWN_SOURCE'},'is_error':False}])
    monkeypatch.setattr(trial,'actor_run',actor)
    calls=SimpleNamespace(report={'branches':[]},save=lambda:None)
    hot=[{'role':'user','content':'KNOWN_SOURCE'}]
    prepared=dict(system='Facts only.',source=hot,hot={'direct':hot,'full':hot},
        workspace=str(work),output=str(output),public_root=str(source.parent),paths=[str(source)],
        objects={str(source):trial.sha(source.read_bytes())})
    spec=dict(name=mode,query='Produce the result.',cold=True,
        expected={'value':'KNOWN_SOURCE'},markers=['KNOWN_SOURCE'])
    await trial.branch(calls,prepared,spec,'full' if mode=='full' else 'direct',0)
    result=calls.report['branches'][0]
    assert result['task_success'] is True
    if mode=='full':
        assert result['cold_required'] is False
        assert result['target_evidence_delivered'] is None
        assert result['effective_recovery'] is None
    else:
        assert result['evidence_calls']==(1 if mode=='cold' else 0)
        assert result['effective_recovery'] is (mode=='cold')
