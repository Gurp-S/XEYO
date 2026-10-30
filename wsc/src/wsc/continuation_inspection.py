"""Unwired mechanical continuation inspection; never generates or publishes.

This module is a review candidate, not an execution/installation authorization.
It keeps old model choices historical and does not resolve semantic changes.
"""
from copy import deepcopy
from dataclasses import fields
import json

from . import evidence, excerpts, understanding
from .contracts import encode, digest, require, WSCError
from .snapshots import validate_snapshot, view_record
from .source_reference_view import hydrate, project
from .store import getmeta
from .view_budget import mandatory_sources


def inspect(core, snapshot, previous_view_id, *, max_view_bytes,
            semantic_reselection_requested=False):
    """Read a consistent DB snapshot and return facts, never an action plan.

No source files are reopened. Current file references, rendered bytes, native
capacity, and recovery delivery remain explicitly unverified. Publication must
perform its normal fresh checks even if these observations are favorable.
    """
    require(type(max_view_bytes) is int and max_view_bytes > 0, 'continuation_budget_invalid')
    require(type(semantic_reselection_requested) is bool, 'continuation_request_invalid')
    with core.store.connect() as db:
        # Use the non-indexed read path: indexed safe_boundary can create a
        # presentation index. This inspector must not create schema or state.
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        try:
            prefix = validate_snapshot(db, core.store, snapshot, indexed=False)
            view = view_record(db, previous_view_id)
            previous = view['binding']
            require(previous['session_id'] == snapshot.session_id
                    and previous['workspace'] == snapshot.workspace,
                    'continuation_previous_identity_changed')
            cut = previous['cut']
            require(type(cut) is int and 0 < cut <= snapshot.cut,
                    'continuation_previous_cut_invalid')
            require(digest(prefix[:cut]) == previous['source_digest'],
                    'continuation_previous_source_changed')
            # Validate historical tool pairing/consumption without assuming the
            # old boundary must be >= the *current* installed cursor.
            pending = set()
            delivered = set()
            for row in db.execute('SELECT data FROM presentations'):
                delivered.update(json.loads(row[0])['source_ids'])
            for row in prefix[:cut]:
                if row['kind'] == 'call':
                    pending.add(row['call_id'])
                elif row['kind'] == 'result':
                    require(row['call_id'] in pending, 'unpaired_result')
                    pending.remove(row['call_id'])
                    require(row['id'] in delivered, 'result_presentation_unknown')
            require(not pending, 'pending_tool_results')
            known = {row['id']: row for row in prefix}
            old_body = hydrate(view['body'], prefix)
            old_sources = old_body['sources']
            ids = [row['id'] for row in old_sources]
            require(len(ids) == len(set(ids)), 'continuation_source_duplicate')
            for row in old_sources:
                require(row['id'] in known and known[row['id']]['seq'] <= cut
                        and encode(row) == encode(known[row['id']]),
                        'continuation_selected_source_changed')
            require({row['id'] for row in mandatory_sources(prefix[:cut])} <= set(ids),
                    'continuation_previous_control_missing')
            records = old_body['understandings']
            refs = [record['ref'] for record in records]
            require(len(refs) == len(set(refs)), 'continuation_record_duplicate')
            for record in records:
                require(encode(understanding.resolve(db, record['ref'])) == encode(record),
                        'continuation_selected_record_changed')
            related = set(ids)
            for record in records:
                related.update(record['sources'])
            for clue in old_body['clues']:
                require(set(clue) == {'text', 'sources'} and type(clue['text']) is str
                        and bool(clue['text'].strip()) and bool(clue['sources']),
                        'continuation_clue_invalid')
                related.update(clue['sources'])
            selected_excerpts = []
            excerpt_names = {field.name for field in fields(excerpts.Excerpt)}
            try:
                for entry in old_body.get('excerpts', []):
                    item = excerpts.Excerpt(**{k: v for k, v in entry.items() if k in excerpt_names})
                    require(item.source_id in known and known[item.source_id]['seq'] <= cut,
                            'continuation_excerpt_outside_previous')
                    selected_excerpts.append(item)
                    related.add(item.source_id)
            except (KeyError, TypeError):
                raise WSCError('continuation_excerpt_shape_invalid') from None
            require(related <= known.keys(), 'continuation_provenance_missing')
            require(all(known[key]['seq'] <= cut for key in related),
                    'continuation_provenance_outside_previous')
            tail = prefix[cut:]
            for row in tail:
                related.add(row['id'])
            for key in related:
                evidence.authorize(core.store, core.access, key)
            # Resolve immutable source slices only. Live resource matches are
            # not copied forward as if they had just been checked.
            historical_excerpts = excerpts.resolve(selected_excerpts, known, bind_live=False)
            resources = [dict(source_id=e.source_id, resource=e.current_resource,
                              expected_sha256=e.current_resource_sha256)
                         for e in selected_excerpts if e.current_resource is not None]
            opaque = [row['id'] for row in tail if row['kind'] == 'opaque']
            all_ids = set(ids) | {row['id'] for row in tail}
            all_ids.update(row['id'] for row in mandatory_sources(prefix))
            rows = [row for row in prefix if row['id'] in all_ids]
            body = dict(sources=rows, understandings=deepcopy(records),
                        clues=deepcopy(old_body['clues']))
            if selected_excerpts:
                body['excerpts'] = historical_excerpts
            mode = old_body.get('source_projection')
            if mode is not None:
                body['sources'] = project(rows, mode)
                body['source_projection'] = mode
            byte_count = len(encode(body).encode('utf-8'))
            pending_operations = [dict(row) for row in db.execute(
                "SELECT id,kind,state FROM operations WHERE state IN ('preparing','ready','installing','unknown','recovery_required')")]
            head_matches = getmeta(db, 'head') == previous_view_id
            previous_state = db.execute('SELECT state FROM views WHERE id=?',
                                        (previous_view_id,)).fetchone()[0]
            epoch_changed = previous['understanding_epoch'] != snapshot.understanding_epoch
            # This is metadata for a future ordered renderer. No flattened
            # body is returned: normal renderers put clues after all messages.
            result = dict(
                schema='wsc.continuation_inspection/1', executable=False,
                semantic_selection_origin=dict(view_id=previous_view_id, cut=cut,
                    body_digest=view['digest'], generation=previous['generation'],
                    control_epoch=previous['control_epoch'],
                    understanding_epoch=previous['understanding_epoch']),
                observed_snapshot=dict(session_id=snapshot.session_id, workspace=snapshot.workspace,
                    generation=snapshot.generation, cut=snapshot.cut,
                    source_digest=snapshot.source_digest, control_epoch=snapshot.control_epoch,
                    understanding_epoch=snapshot.understanding_epoch),
                previous_installed_head_matches=head_matches,
                previous_view_state=previous_state, installed_cursor=getmeta(db, 'cursor'),
                preserved_source_ids=ids, preserved_understanding_refs=refs,
                preserved_excerpt_keys=[e.key for e in selected_excerpts],
                raw_tail_source_ids=[row['id'] for row in tail], raw_tail_digest=digest(tail),
                selected_record_contents_unchanged=True,
                understanding_change_inventory_complete=not epoch_changed,
                semantic_reselection_requested=semantic_reselection_requested,
                pending_publications=pending_operations, opaque_tail_sources=opaque,
                live_reference_observation_required=resources,
                stored_body_bytes=byte_count,
                stored_body_measurement='diagnostic_flat_storage_shape_without_live_reference_results',
                stored_body_is_publishable=False,
                max_view_bytes=max_view_bytes,
                storage_budget_exceeded=byte_count > max_view_bytes,
                ordered_rendering_verified=False, rendered_bytes=None,
                host_context_capacity_verified=False, continuation_recovery_verified=False,
                observation_scope='Read-time facts only; no fresh generation, model selection, file freshness certification, or publication authorization.')
        finally:
            db.rollback()
    return result
