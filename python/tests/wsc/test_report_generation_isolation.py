import json


def test_new_offline_copy_never_reuses_other_folders_frozen_head(tmp_path):
    from evals.wsc_real_report_continuation import run
    from tests.wsc.test_card_surface import fixture
    source = tmp_path / 'original.jsonl'
    rows = [dict(row, id=row.get('id') or f'row-{i}') for i, row in enumerate(fixture())]
    source.write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows), encoding='utf-8')
    original = source.read_bytes()
    first, second = tmp_path / 'first', tmp_path / 'second'
    for folder, indexed in ((first, False), (second, True)):
        run([('same', source)], folder, tmp_path / 'unused-key', execute=False,
            channel='native', cards_index=indexed, search=True, source_passages=indexed)
    old = json.loads((first / 'same/input.json').read_text(encoding='utf-8'))
    new = json.loads((second / 'same/input.json').read_text(encoding='utf-8'))
    report = json.loads((second / 'same/report.json').read_text(encoding='utf-8'))
    assert report['source_passage_views'] == 1
    from pathlib import Path
    from memory.wsc_projection import _STATE
    view = Path(_STATE['report-same'].view_path).resolve()
    assert view.is_relative_to(second) and view.is_file()
    assert json.loads((first / 'same/input.json').read_text(encoding='utf-8')) == old
    assert str(first).replace('\\', '/') not in str(new[0]).replace('\\', '/')
    assert source.read_bytes() == original
