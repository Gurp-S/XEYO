# Direct ten-round correctness review

Base: `Gurp-S/XEYO@bb1af831ac707e0b2ad0e7f1dedccad0da4706b0`.
All changes in this branch are authored in the main conversation's isolated Linux worktree. The Windows worktree's earlier two delegated rounds are excluded. Concurrent uncommitted WSC and other work on the user's computer is not included, changed, or validated here. No paid model calls or production data used. This report records scoped regressions, not a claim that all project bugs are fixed.

Environment: Python 3.12, isolated `/tmp/xeyo-review-venv`; commands below run from `python/` with that environment's Python. Each fix is developed in an isolated branch with a failing regression before implementation, followed by targeted validation. Design-review items remain pending.

## Round 1 — Transcript archive preservation
- Root cause: archive paths are oldest-first, but promotion copied in the opposite direction, replacing old1 with the next transcript and losing history.
- Invariant: archive promotion moves newer slots toward older empty slots before publishing the current transcript; a full archive does not authorize history deletion.
- Before: `pytest tests/test_transcript_rotation.py -k never_overwrites -q`: 1 failed.
- Fix: correct promotion direction. Strengthen existing multi-generation test from lossy subsequence to complete ordered conservation, consistent with the existing documented retention policy.
- After: `pytest tests/test_transcript_rotation.py tests/test_record_transcript.py tests/test_record_transcript_g107.py -q`: 11 passed.

## Round 2 — Notebook creation / cell-type validity
Root causes: insertion into a new notebook used uninitialized `nb_encoding`; code-to-Markdown replacement retained code-only fields. Defined UTF-8 for creation and enforce resulting cell-type fields (including removing Markdown attachments on conversion to code).
- Before: `pytest tests/test_notebook_input_regressions.py -q`: 2 failed.
- After: same plus `test_notebook_edit_tool.py` and `test_notebook_edit_reader_paths.py`: 18 passed.

## Round 3 — LSP protocol / transport error isolation
Root causes: response-ID coercion aliased unrelated IDs or raised; send errors leaked pending entries; reader dispatch failure bypassed waiter cleanup. Require exact integer response identity, clean failed sends, always wake waiters on reader exit.
- Before: `pytest tests/test_lsp_client_regressions.py -q`: 8 failed.
- After: same plus `test_lsp_tool.py`: 22 passed.

## Round 4 — Cancellation remains terminal
Inherited cancellation only notified children, leaving them dependent on the parent's mutable flag. Latch descendant cancellation so parent reset cannot revive already-cancelled work, preserving local cancellation reasons.
- Before: `pytest tests/test_abort_parent_reset.py -q`: 1 failed, 1 passed.
- After: same plus `test_abort.py`: 3 passed; `test_cancellation.py` also passed in the combined checks.

## Round 5 — LSP document freshness
Already-open files were never resynchronized after disk edits. `lsp/documents.py` owns serialized snapshot/version publication; unchanged text sends nothing, changed text sends didChange, failed publication cannot advance state.
- Before: `pytest tests/test_lsp_document_sync.py -q`: 1 failed, 1 passed.
- After: same plus `test_lsp_client_regressions.py`, `test_lsp_tool.py`, `test_cancellation.py`: 30 passed.
- Limit: query-time disk snapshots, not filesystem watching or editor-buffer synchronization.

## Round 6 — Audit secrets
Credential values leaked unless matching a regex; case variants bypassed matching; depth limits returned unsanitized subtrees; GitHub underscore prefixes were missed. Credential-key identity now masks complete values, deep containers fail closed, ordinary metadata stays intact. Small classifier isolated in `audit/secret_fields.py`.
- Before: `pytest tests/test_audit_secret_boundaries.py -q`: 9 failed, 1 passed.
- After: same plus `test_redact_g76.py`: 17 passed.
- Limit: not universal secret detection in arbitrary text.

## Round 7 — LSP async boundary
Async tool execute performed blocking startup/request/cleanup directly on the event loop. Offload those operations and check observed cancellation after awaited work.
- Before: `pytest tests/test_lsp_async_boundary.py -q`: 1 failed.
- After: same plus other LSP tests then present: 25 passed.
- Limit: cancelling the async waiter does not forcibly terminate a shared server or worker thread; underlying timeouts still apply.

## Round 8 — LSP cache lifecycle
Concurrent startups overwrote cached clients and leaked losers; a startup could republish after shutdown. Publication now rechecks owner and shutdown generation, stops discarded clients outside the cache lock.
- Before: `pytest tests/test_lsp_cache_lifecycle.py -q`: 2 failed (barrier/event-controlled races).
- After: all five LSP test files: 27 passed.
- Limit: temporary duplicate startups remain possible; cache eviction can still interrupt a caller, which gets the existing fail-open result.

## Round 9 — MCP source-owned trust metadata
Project JSON could supply `_requires_trust: false`; malformed sibling declarations crashed collection. Derive trust requirement from loader scope, never project content; skip malformed declarations with a warning.
- Before: `pytest tests/test_mcp_scope_trust_origin.py -q`: 2 failed.
- After: same plus `test_mcp_policy.py`, `test_mcp_fingerprint_v2.py`: 32 passed.
- Limit: broader project trust-file placement and invalid enterprise-policy fallback remain separate unresolved issues.

## Round 10 — Nonfinite usage counts
Integer normalization omitted OverflowError, so infinity could crash ledger/pricing/report paths. Extend existing invalid-count fallback without changing rates, valid counts or unknown-price semantics.
- Before: `pytest tests/test_usage_nonfinite_counts.py -q`: 7 failed, 7 passed.
- After: same plus `test_usage_combine.py`, `test_usage_ledger.py`, `test_pricing_honesty.py`: 38 passed.

## Combined verification
All listed regression modules plus `test_audit_log.py` in one invocation: **161 passed in 3.23s**. Counts from individual rounds overlap and must not be added together. `git diff --check` passed.

These are ten scoped correctness passes, not full repository coverage. Concurrent WSC and other Windows work is not included or validated. Browser IndexedDB, actual language servers and Windows execution are not covered. No automatic merge to main. Existing local Windows patches are separate and not part of this branch.

### Final hardening checks
Added regression coverage for Markdown-to-code attachment cleanup, failed didChange retry without advancing version, cancellation suppressing a late successful query, and an actual subprocess/stdio round trip against a deterministic local fake LSP server. The latter checks framing/startup/changed document/hover/shutdown without network or external language servers.

Final combined result: **165 passed**. Syntax compilation of all changed Python files and `git diff --check` passed. No changed path contains `wsc`; no dependencies or generated lockfiles changed. No original user worktree files were copied into this branch.

Reproduce from `python/`:
```sh
python -m pytest tests/test_transcript_rotation.py tests/test_record_transcript.py tests/test_record_transcript_g107.py tests/test_notebook_input_regressions.py tests/test_notebook_edit_tool.py tests/test_notebook_edit_reader_paths.py tests/test_lsp_client_regressions.py tests/test_lsp_tool.py tests/test_lsp_document_sync.py tests/test_lsp_async_boundary.py tests/test_lsp_cache_lifecycle.py tests/test_lsp_stdio_integration.py tests/test_abort_parent_reset.py tests/test_abort.py tests/test_cancellation.py tests/test_audit_secret_boundaries.py tests/test_redact_g76.py tests/test_audit_log.py tests/test_mcp_scope_trust_origin.py tests/test_mcp_policy.py tests/test_mcp_fingerprint_v2.py tests/test_usage_nonfinite_counts.py tests/test_usage_combine.py tests/test_usage_ledger.py tests/test_pricing_honesty.py -q
```
