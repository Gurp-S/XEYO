"""Isolated duck-typed source adapter for executing the real query loop.

API/export reads outside the evaluated loop continue using the original store.
Production must eventually wire a dedicated getter rather than replace its API.
"""
from evals.wsc_source_reader import SourceReader
from prompt.state_emission import select_rendered_state
class QuerySource:
    def __init__(self, store, layout):
        self.store = store
        self.layout = layout
        self.reader = SourceReader()
        self.reads = []

    def __getattr__(self, name):
        return getattr(self.store, name)

    def __len__(self):
        return len(self.store)

    def as_api_messages(self):
        previous = self.reader._cache.get(self.store)
        rows = self.reader.read(self.store, self.layout)
        self.reads.append(previous is not None and previous[1] is rows)
        return rows


class ConditionalQuerySource(QuerySource):
    """Eval-only one-time switch when native frozen source identity fails.

    Fresh fold matches the retained replay's transition policy. Graph selection
    and source seals are native per-call values, with no process-global hooks.
    """
    def __init__(self, store, working, cwd):
        from evals.wsc_source_contract import LEGACY, validate
        super().__init__(store, validate(getattr(working, "compression_source_layout", LEGACY)))
        self.working = working
        self.cwd = cwd
        self.transitions = 0
        self.source_checks = 0
        self._checked_api = None

    def close(self):
        pass  # Compatibility with the former adapter; no global hooks to undo.

    def as_api_messages(self):
        from evals.wsc_source_contract import APPEND, LEGACY
        from evals.wsc_source_transition import invalid_frozen_source, invalid_persisted_source, rebase_compression
        import importlib
        wp = importlib.import_module("memory.wsc_projection")
        if self.layout == LEGACY:
            rows = self.store.as_api_messages()
            key = wp._state_key(self.working.session_id, self.cwd)
            invalid = False
            if rows is not self._checked_api:
                # Source changes only at native store invalidation boundaries;
                # repeated getters must not re-read/re-hash a persisted head.
                self._checked_api = rows
                self.source_checks += 1
                cached = wp._STATE.get(key)
                invalid = (invalid_frozen_source(cached, rows) if cached is not None else
                           invalid_persisted_source(self.working, rows, self.cwd))
            if invalid:
                rebase_compression(self.working)
                self.layout = self.working.compression_source_layout = APPEND
                wp._STATE.pop(key, None)
                self.transitions += 1
                from memory.runtime import force_compact
                force_compact(self.reader.read(self.store, APPEND), self.working, cwd=self.cwd)
        return super().as_api_messages()
