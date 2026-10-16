"""Native commit/fold/projection and Read for scoped continuation evaluations.

No replacement summarizer, policy switch, task truth or paid transport lives
here. The caller owns isolated environment, input source and model budgets.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from engine.abort import AbortController
from memory.working import WorkingSnapshot, flush, hydrate
from session.compression_source import compression_messages
from session.hydrate import message_from_row
from session.message_store import MessageStore
from session.record_transcript import record_transcript_sync, load_transcript
from session.transcript_blobs import resolve_transcript_rows
from tools.file_read_tool.file_read_tool import FileReadTool
from tools.todo_write_tool.todo_write_tool import TodoWriteTool
from tools.tool_registry import ToolRegistry


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _store(rows):
    messages = []
    for row in deepcopy(rows):
        if not isinstance(row, dict):
            continue
        if row.get('id') and row.get('message_id') and row['id'] != row['message_id']:
            raise ValueError('evaluation_source_identity_conflict')
        if row.get('message_id'):
            row['id'] = row['message_id']
        item = message_from_row(row)
        if item is None:
            continue
        # Older evaluation fixtures use provider-style user/tool_result rows.
        # Adapt those after native parsing, so UI-only rows stay excluded.
        if item.role in ('user', 'tool') and isinstance(item.content, list):
            receipt = next((b for b in item.content if isinstance(b, dict)
                            and b.get('type') == 'tool_result'), None)
            if receipt is not None:
                item.role = 'tool'
                if not item.tool_call_id:
                    item.tool_call_id = receipt.get('tool_use_id')
        messages.append(item)
    return MessageStore(messages)


class ProductionTask:
    def __init__(self, root, rows, *, session='production-continuation', working=None, restored=False):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.working = working or WorkingSnapshot(session_id=session)
        self.store = _store(rows)
        self.path = self.root / 'native-transcript.jsonl'
        self.known = {item.id for item in self.store.items} if restored else set()
        self.registry = ToolRegistry(cwd=str(self.root))
        self.registry.register(TodoWriteTool(cwd=str(self.root)))
        self.registry.register(FileReadTool(cwd=str(self.root)))

    def source(self):
        return compression_messages(self.store, self.working)

    def persist(self):
        record_transcript_sync(self.store.items, session_id=self.working.session_id,
                               path=self.path, known_ids=self.known)

    async def commit(self, declaration):
        """declaration receives exactly the native captured source it commits."""
        from memory.wsc_handoff_transaction import commit
        self.persist()
        return await commit(source=self.source, generate=declaration, store=self.store,
            tools=self.registry, abort=AbortController(), persist=self.persist, require_phase=True)

    def fold(self):
        from memory.runtime import force_compact
        from memory.wsc_head_store import load, path_for
        rows = deepcopy(self.source())
        before = deepcopy(rows)
        first = force_compact(rows, self.working, cwd=self.root)
        frozen = load(self.working.session_id, cwd=str(self.root),
            cursor=self.working.compact_cursor, messages=rows,
            source_layout=self.working.compression_source_layout)
        if frozen is None:
            raise ValueError('evaluation_fold_not_published')
        rec = json.loads(path_for(self.working.session_id).read_text(encoding='utf-8'))
        if not rec.get('publication') or rec['region_end'] <= 0:
            raise ValueError('evaluation_fold_not_published')
        hot = self.project()
        if first != hot:
            raise ValueError('evaluation_initial_emission_not_stable')
        if rows != before or self.source() != before:
            raise ValueError('evaluation_projection_mutated_source')
        flush(self.working.session_id, self.working)
        return {'hot': hot, 'head': rec, 'source_sha256': hashlib.sha256(canonical(rows).encode('utf-8')).hexdigest(),
                'native_source': rows, 'compact_cursor': self.working.compact_cursor,
                'retired_region_end': rec['region_end']}

    def project(self):
        from memory.runtime import project_for_model
        return project_for_model(self.source(), self.working, cwd=self.root,
            capacity_managed=True, context_limit=1048576, include_memory_index=False)

    def restart(self):
        rows = resolve_transcript_rows(load_transcript(self.path), self.path)
        state = hydrate(self.working.session_id, source_layout=self.working.compression_source_layout)
        from memory import wsc_projection
        wsc_projection._STATE.pop(wsc_projection._state_key(self.working.session_id, self.root), None)
        return ProductionTask(self.root, rows, working=state, restored=True)


class PublishedRead:
    """Eval capability boundary excludes private oracles, prepared wire and keys."""
    def __init__(self, task, head):
        self.task = task
        self.allowed = {Path(path).resolve() for path in head['publication']['objects']}

    def schemas(self):
        return [self.task.registry.get('Read').schema()]

    async def execute(self, use, abort):
        from tools.base_tool import ToolResult
        if use.name != 'Read':
            return ToolResult('unknown_tool', is_error=True, error_kind='INVALID_ARGUMENT')
        name = use.input.get('file_path') if isinstance(use.input, dict) else None
        if not isinstance(name, str):
            return ToolResult('invalid file_path', is_error=True, error_kind='INVALID_ARGUMENT')
        requested = Path(name)
        resolved = (requested if requested.is_absolute() else self.task.root / requested).resolve()
        if resolved not in self.allowed:
            return ToolResult('Permission denied: outside published evidence', is_error=True, error_kind='PERMISSION_DENIED')
        return await self.task.registry.run(use, abort)
