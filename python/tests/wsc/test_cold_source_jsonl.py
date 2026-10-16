"""The cold candidate reads LF-delimited records, not Unicode text lines."""
import hashlib
import json

import pytest

from memory.wsc_cold_source_candidate import ColdSources


def test_unicode_separators_stay_inside_sealed_record(tmp_path):
    rows = [{'id':'r','role':'user','content':'A\u2028B\u2029C\x85D\nE'},
            {'id':'s','role':'tool','content':[{'type':'tool_result','tool_use_id':'call',
                                              'content':'原文\n\t尾部\u2028仍属同一记录'}]}]
    raw = ''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows).encode('utf-8')
    path = tmp_path/'source.jsonl'
    path.write_bytes(raw)
    cold = ColdSources(path, hashlib.sha256(raw).hexdigest())
    assert cold.locator()['source_count'] == 2
    for reader in (cold, cold.reopen()):
        assert reader.source({'message_id':'r','offset':0,'limit':4096})['content'] == rows[0]['content']
        result = reader.source({'message_id':'s','call_id':'call','offset':0,'limit':4096})
        assert result['content'] == rows[1]['content'][0]['content']
        assert result['tool_call_id'] == 'call' and result['text_complete']
    assert path.read_bytes() == raw
    path.write_bytes(raw+b' ')
    with pytest.raises(ValueError,match='cold_source_seal_mismatch'):
        cold.reopen()
