from copy import deepcopy
import pytest

from memory.wsc_handoff_recall import read


def test_literal_search_reaches_distant_tail_without_heating_whole_source():
    text = "billing-spec归档\n" + "资料abcdefgh\n" * 200000 + "billing-spec：标记RF-683917；DS-294806。\n验收EV-571308，归档AR-826451。"
    rows = [{"message_id": "spec", "role": "user", "content": text}]
    before = deepcopy(rows)
    result = read({"message_id": "spec", "query": "billing-spec", "limit": 4096}, rows)
    assert result["matches_total"] == 2 and not result["text_complete"]
    assert sum(len(p["content"]) for p in result["passages"]) <= 4096
    assert any("RF-683917" in p["content"] and "AR-826451" in p["content"] for p in result["passages"])
    for passage in result["passages"]:
        assert text[passage["offset"]:passage["end_offset"]] == passage["content"]
    assert rows == before


def test_query_is_literal_and_match_limit_reports_omissions():
    rows = [{"message_id": "spec", "role": "user", "content": "[a.*b]" * 100}]
    result = read({"message_id": "spec", "query": "a.*b", "limit": 16}, rows)
    assert result["matches_total"] == 100 and result["unreturned_match_count"] == 96
    assert sum(len(p["content"]) for p in result["passages"]) <= 16
    assert not result["text_complete"]


@pytest.mark.parametrize("fields", [{"query": ""}, {"query": []}, {"query": "abcdef", "limit": 1},
    {"query": "x", "offset": 0}, {"query": "x", "file_path": "secret"}])
def test_invalid_search_has_no_path_or_mixed_selector(fields):
    with pytest.raises(ValueError, match="handoff_source_invalid_arguments"):
        read({"message_id": "spec", "limit": 16, **fields}, [{"message_id": "spec", "role": "user", "content": "x"}])


def test_no_matches_is_explicit_empty_result_not_empty_source():
    result = read({"message_id": "spec", "query": "missing", "limit": 16},
                  [{"message_id": "spec", "role": "user", "content": "原始内容"}])
    assert result["matches_total"] == 0 and result["passages"] == [] and result["total_characters"] == 4


@pytest.mark.parametrize('text,query,limit', [
    ('aaaaa', 'a', 20), ('a' * 100, 'a', 40), ('a' * 41, 'aaa', 40),
    ('ababa' * 40, 'aba', 32), ('Ω匹配' * 80, '匹配', 120),
    ('hit' + 'x'*1000 + 'hit'*9, 'hit', 100),
])
def test_omissions_count_actual_fully_returned_matches(text, query, limit):
    import re
    result = read({'message_id':'r','query':query,'limit':limit},
                  [{'id':'r','role':'user','content':text}])
    matches = list(re.finditer(re.escape(query), text))
    returned = sum(any(p['offset'] <= m.start() and m.end() <= p['end_offset']
                       for p in result['passages']) for m in matches)
    assert result['matches_total'] == len(matches)
    assert result['unreturned_match_count'] == len(matches) - returned
    assert sum(len(p['content']) for p in result['passages']) <= limit
    assert all(p['content'] == text[p['offset']:p['end_offset']] for p in result['passages'])
    if result['text_complete']:
        assert result['unreturned_match_count'] == 0
