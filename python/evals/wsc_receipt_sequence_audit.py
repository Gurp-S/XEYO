"""Read-only identity/sequence audit of explicitly inventoried real sessions."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def inspect(items):
    from session.late_result_guard import call_counts, displaced_calls, conflicts
    from session.result_identity import result_ids
    from session.late_result_projection import supported
    from session.recovery_result_chain import supersessions
    calls = call_counts(items)
    receipts = Counter(uid for item in items for uid in result_ids(item) if uid)
    displaced = displaced_calls(items)
    supplemental_ids = sorted({uid for _index, uid in supersessions(items)})
    return {'messages': len(items), 'call_blocks': sum(calls.values()), 'result_blocks': sum(receipts.values()),
            'multi_result_rows': sum(len(result_ids(item)) > 1 for item in items),
            'duplicate_call_ids': sorted(uid for uid, count in calls.items() if count > 1),
            'duplicate_result_ids': sorted(uid for uid, count in receipts.items() if count > 1),
            'unknown_result_ids': sorted(uid for uid in receipts if uid not in calls),
            'invalid_source_ids': [item.id for item in items if '' in result_ids(item)],
            'unique_late_result_ids': conflicts(items), 'displaced_ids': displaced,
            'recovery_supplement_ids': supplemental_ids,
            'candidate_supported': supported(items),
            'default_guard_would_stop': bool(displaced or supplemental_ids)}


def projection_probe(items, folder, native):
    from evals.wsc_unfolded_source_ab import environment
    from memory.runtime import force_compact, project_for_model
    from memory.working import WorkingSnapshot, flush, hydrate
    from memory import wsc_projection
    from session.message_store import MessageStore
    from session.compression_source import compression_messages
    from session.late_result_guard import request_conflict
    import os
    folder.mkdir(parents=True, exist_ok=False)
    with environment(folder):
        os.environ['XEYO_WSC'] = str(int(native))
        os.environ['XEYO_LATE_RESULT_PROJECTION'] = '0'
        sid = 'receipt-audit-' + folder.name
        working = WorkingSnapshot(session_id=sid)
        source = compression_messages(MessageStore(items), working)
        wsc_projection._STATE.pop(sid, None)
        emitted = force_compact(source, working, cwd=folder)
        flush(sid, working)
        restored = hydrate(sid)
        wsc_projection._STATE.pop(sid, None)
        resumed = project_for_model(source, restored, context_limit=1000000,
                                    capacity_managed=True, include_memory_index=False, cwd=folder)
        return {'native_requested': native, 'compact_cursor': working.compact_cursor,
                'request_rows': len(emitted), 'request_conflict': request_conflict(emitted),
                'restored_request_conflict': request_conflict(resumed),
                'restored_head_equal': bool(emitted and resumed and emitted[0] == resumed[0]),
                'scope': 'Private new-generation deterministic fold and restore, not live migration or model semantics'}


def run(inventory, sessions_root, output, project_dir=None):
    from session.record_transcript import load_transcript, transcript_read_paths
    from session.transcript_blobs import resolve_transcript_rows
    from session.surface import fold_surface_rows
    from session.hydrate import message_from_row, messages_from_rows
    source_inventory = inventory.read_bytes()
    reports = []
    for entry in json.loads(source_inventory)['sessions']:
        sid = entry['session_id']
        path = sessions_root / (sid + '.jsonl')
        paths = transcript_read_paths(path)
        before = {str(file): hashlib.sha256(file.read_bytes()).hexdigest() for file in paths}
        rows = []
        for file in paths:
            rows.extend(load_transcript(file))
        surface = resolve_transcript_rows(fold_surface_rows(rows), path)
        items = [message for row in surface if (message := message_from_row(row)) is not None]
        raw = inspect(items)
        restored = messages_from_rows(surface)
        probes = []
        if project_dir is not None:
            probes = [projection_probe(restored, project_dir / (sid + '-' + str(native)), native)
                      for native in [False, True]]
        reports.append({'session_id': sid, 'source_files_sha256': before, 'surface': raw,
                        'hydrated': inspect(restored),
                        'projection_probes': probes,
                        'hydration_preserves_source_rows': restored == items,
                        'source_unchanged': all(hashlib.sha256(Path(file).read_bytes()).hexdigest() == digest for file, digest in before.items())})
    result = {'scope': __doc__, 'api_calls': 0, 'inventory_sha256': hashlib.sha256(source_inventory).hexdigest(),
              'inventory_unchanged': inventory.read_bytes() == source_inventory, 'sessions': reports}
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError('audit_output_exists')
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--sessions-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--project-dir', type=Path)
    args = parser.parse_args()
    report = run(args.inventory, args.sessions_root, args.output, args.project_dir)
    print(json.dumps([{'session_id': entry['session_id'], 'messages': entry['surface']['messages'],
                       'displaced': len(entry['surface']['displaced_ids']),
                       'late': len(entry['surface']['unique_late_result_ids']),
                       'supported': entry['surface']['candidate_supported'],
                       'source_unchanged': entry['source_unchanged']} for entry in report['sessions']]))
