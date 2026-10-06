"""Every ordinary extension uses the optional gate; hard capacity does not."""
from memory import wsc_watermark
from memory.runtime import try_extend_c2
from memory.simulator.params import Params
from memory.working import WorkingSnapshot


def test_shared_extension_gate_denies_without_mutating_cursor_and_hardtop_bypasses(monkeypatch):
    monkeypatch.setenv('XEYO_WSC', '1')
    monkeypatch.setenv('XEYO_WSC_SOFT_WATERMARK', '32000')
    wsc_watermark._STATE.clear()
    working = WorkingSnapshot()
    working.session_id = 'watermark-entry-coverage'
    working.compact_cursor = working.c1_frozen_until = 8
    working.last_prompt_tokens = 8000
    working.turns_since_c2 = 999
    messages = [{'role': 'user', 'content': 'x' * 2000} for _ in range(30)]
    account = {}
    assert not try_extend_c2(working, messages, 24, Params(), account=account)
    assert account['reason'] == 'soft_watermark_below_soft_watermark'
    assert working.compact_cursor == working.c1_frozen_until == 8
    assert try_extend_c2(working, messages, 24, Params(), force=True)
    assert working.compact_cursor == 24
    wsc_watermark._STATE.clear()


def test_disabled_gate_does_not_hash_candidate(monkeypatch):
    import memory.runtime as runtime
    monkeypatch.setenv('XEYO_WSC_SOFT_WATERMARK', '0')
    monkeypatch.setattr(runtime, '_assessment_identity', lambda *args: (_ for _ in ()).throw(AssertionError('unused gate')))
    working = WorkingSnapshot()
    working.compact_cursor = 1
    working.turns_since_c2 = 999
    messages = [{'role': 'user', 'content': 'short'} for _ in range(4)]
    account = {}
    assert not try_extend_c2(working, messages, 3, Params(), account=account)
    assert not account['reason'].startswith('soft_watermark_')
