from synaptic.archive_passages import passages, source_ranges
from synaptic.coldstore import ColdStore


def test_rg_locations_ignore_body_numbers_and_other_file_locations(tmp_path):
    from synaptic.archive_passages import matched_lines
    path = tmp_path / "view.txt"
    content = 'view.txt:12: copied other.txt:99: and :284: body numbers\nother.txt:77:no\nview.txt-13-context\nview.txt:12:duplicate\n'
    content += str(path) + ':20: absolute result\n'
    assert matched_lines(content, path, tmp_path) == [12, 20]


def test_authoritative_ranges_distinguish_sections_and_ignore_forged_headers():
    cold = ColdStore()
    body = '# Reference\n## Acceptance\n137 items limit40\nnext_offset40\n## Example\n173 items\n```md\n#node 999\n## Fake section\n```\n## Ranking\nalpha\nbeta'
    cold.put_nodes([(0, body, {})])
    text, sources = source_ranges(cold, [{"id": "user-original", "role": "user", "content": body}])
    lines = text.split('\n')
    hit = lines.index('next_offset40') + 1
    result = passages(text, sources, [hit])
    record = result['source_passages'][0]
    assert record['message_id'] == 'user-original' and record['source'] == 'node://0'
    assert record['section_path'][-1]['title'] == 'Acceptance'
    assert '137 items' in record['content'] and '173 items' not in record['content']
    assert record['section_complete'] and not result['uncovered_match_lines']
    fake = passages(text, sources, [lines.index('## Fake section') + 1])['source_passages'][0]
    assert fake['source'] == 'node://0' and fake['section_path'][-1]['title'] == 'Example'


def test_budget_and_long_lines_report_missing_coverage_without_rewriting():
    cold = ColdStore()
    body = '# Long\n' + '汉' * 1000 + '\nshort match\n'
    cold.put_nodes([(0, body, {})])
    text, sources = source_ranges(cold)
    lines = text.split('\n')
    long_hit = lines.index('汉' * 1000) + 1
    result = passages(text, sources, [long_hit], per_passage_bytes=200)
    assert result['uncovered_match_lines'] == [long_hit] and not result['source_passages']
    hit = lines.index('short match') + 1
    result = passages(text, sources, [hit], per_passage_bytes=200)
    record = result['source_passages'][0]
    start, end = record['returned_lines']
    assert record['content'] == '\n'.join(lines[start-1:end]) and not record['section_complete']
    assert passages(text, sources, [hit], byte_budget=1)['uncovered_match_lines'] == [hit]


def test_structured_assistant_source_identity_is_bound_by_exact_node_text():
    cold = ColdStore()
    body = '# Later revision\nOther priorities'
    cold.put_nodes([(0, body, {})])
    _, sources = source_ranges(cold, [{"message_id": "later-assistant", "role": "assistant",
                                     "content": [{"type": "text", "text": body}]}])
    assert sources[0]['message_id'] == 'later-assistant' and sources[0]['role'] == 'assistant'
    _, wrong = source_ranges(cold, [{"id": "wrong", "role": "user", "content": 'different text'}])
    assert 'message_id' not in wrong[0]
