from types import SimpleNamespace

from memory import runtime as rt
from memory.simulator.params import Params
from memory.working import WorkingSnapshot
from tests.wsc.test_receipt_truth import use, result


def test_project_mode_respects_an_existing_compaction(monkeypatch, mem_switch):
    mem_switch(XEYO_L5='project')
    working = WorkingSnapshot(session_id='project_receipt', compact_cursor=2)
    rows = [use('r', 'Read', file_path='a.py'), result('r', 'x=1'),
            {'role': 'user', 'content': 'continue'}]
    compacted = [{'role': 'assistant', 'content': 'frozen state'}, rows[-1]]
    monkeypatch.setattr(rt, 'apply_c2_messages', lambda *a, **k: compacted)
    assert rt.project_for_model(rows, working, include_memory_index=False) == compacted


def test_current_model_identity_reaches_decision(monkeypatch, mem_switch):
    mem_switch(XEYO_L5='v61')
    seen = []

    def decide(state, cache, **kwargs):
        seen.append((cache.provider, cache.model, kwargs['params'].window_tokens))
        return SimpleNamespace(a_star='keep', hardtop=False, branches={})

    monkeypatch.setattr('memory.simulator.decision.decide', decide)
    rt.project_for_model([{'role': 'user', 'content': 'hello'}],
                         WorkingSnapshot(session_id='model_identity'), provider='openai',
                         model_name='custom-model', context_limit=64000, include_memory_index=False)
    assert seen == [('openai', 'custom-model', 64000)]


def test_cadence_rejection_does_not_build_unused_summary(monkeypatch):
    monkeypatch.setenv('XEYO_WSC_FOLD_COOLDOWN_VETO', '1')
    working = WorkingSnapshot(session_id='cheap_veto', compact_cursor=2,
                              turns_since_c2=1, c2_gap_shots=20)
    monkeypatch.setattr(rt, 'c2_summary_extension', lambda *a, **k: (_ for _ in ()).throw(
        AssertionError('a vetoed fold must not generate a summary')))
    account = {}
    assert not rt.try_extend_c2(working, [{'role': 'user', 'content': 'x' * 16000}] * 12,
                               10, Params(), account=account)
    assert account['reason'] == 'cooldown_veto'
    assert account['economics_basis'] == 'not_measured_cadence_veto'
    assert 'head_tokens' not in account
