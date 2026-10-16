# XEYO remediation ledger — 2026-10-15

This ledger records the exact T01-T07 findings and their targeted fixes in the shared worktree. The task-provided findings and acceptance conditions are the scope of record.

## Worktree baseline and current state

- Baseline: branch `main`, HEAD `bb1af831ac707e0b2ad0e7f1dedccad0da4706b0`.
- Baseline dirty state at task start: 11 modified tracked files and 308 untracked paths. The 11 pre-existing tracked paths were preserved: three WSC docs, `python/engine/manual_compaction.py`, `python/engine/query_loop.py`, five WSC memory files, and `python/tests/wsc/test_head_store.py`.
- Current state before adding this ledger: 19 modified tracked files and 312 untracked paths. The seven task-edited tracked files are `python/session/record_transcript.py`, `python/tests/test_transcript_rotation.py`, `python/memory/memdir.py`, `python/memory/memindex.py`, `python/tests/test_memdir.py`, `python/rewind/blob_gc.py`, and `python/tests/test_blob_gc.py`.
- One additional concurrent tracked edit, `python/tests/wsc/test_handoff_failure_continuity.py`, and four additional untracked paths appeared after the baseline. They were not edited or removed. The ledger itself adds one untracked path.
- No reset, clean, stash, commit, push, publish, paid API call, or secret access was performed.

## Findings and status

| Scope | Status | Evidence / remaining work |
|---|---|---|
| T01 - persistent data | Repaired; targeted verification passed | Transcript rotation, memory publication, and journal append/GC serialization repairs are documented below. Existing WSC edits are outside this task. |
| T02 - rewind | Repaired; targeted verification passed | Restore provenance, retry/undo snapshots, workspace lease cleanup, byte-tail parsing, and route lease/restore locking received targeted regressions. |
| T03 - transcript and fork | Repaired; targeted verification passed | Transcript rotation and fork transcript/blob/workspace binding received targeted verification. |
| T04 - diagnostics | Repaired; targeted verification passed | Quota eviction now protects pins, baselines, experiments, and reservation state; capture-store regression passed. |
| T05 - frontend history | Partial; typecheck passed | Thought IDs, space removal, compound message keys, and retry-safe migration were changed. Vitest is blocked by Windows sandbox EPERM resolving the test file; IndexedDB migration has no runtime browser regression yet. |
| T06 - memory I/O | Repaired; targeted verification passed | Frontmatter parsing, identity-safe filenames, interrupted migration recovery, and SQLite cache selection are covered below. |
| T07 - GC/references | Repaired; targeted verification passed | Corrupt or changing reference inventories retain snapshot blobs; latest-wins checkpoint/turn references and recovery-job references are covered by targeted tests. |

Finding labels are mapped to the exact T scopes above. The detailed evidence below preserves the earlier transcript, memory, and blob-GC test records.

## Current batch: 2026-10-15

- A-017: compatibility restore conditionally recreates a checkpoint file when the current file is absent; added a deleted-since-checkpoint regression.
- A-025: path normalization strips repeated leading `./` only, preserving dotfiles. A-030 reads rewind JSONL in binary mode and replaces malformed UTF-8 per line.
- B13: memory journal append and GC share the cross-process path lock; GC holds it through replacement and index rebuild. Subprocess append-vs-GC regression passed.
- A-022/A-023/A-028/A-029: rewind records reliable post-checkpoint creates, preserves unknown files without preimages, durably records the pre-rewind index before writes, and retains retry/undo state. POSIX mode test is skipped on Windows.
- A-024: compatibility rollback releases its workspace lease when restore raises.
- A-026: latest reference rows win for duplicate turn/checkpoint IDs; recovery-job backup references remain reachable.
- C08: fork flushes and validates transcript blob references, copies current/archive blobs, and binds the fork to its cloned workspace.
- C23: quota cleanup protects pins, baselines, experiments, and reservation records; shortfall is reported when protected bytes exceed quota.
- C31: rewind mutation routes atomically acquire the SessionPool lease; restore/undo and Write/Edit/NotebookEdit/Bash share the engine WorkspaceLock. Targeted tests: workspace mutation, rewind hotpath, service, and direct route handlers: 31 passed, 1 skipped.
- D13/D18/D19/D20: thought message IDs include a per-send turn identity; space removal preserves local conversation records; IndexedDB messages use `[sessionId,id]`; source migration and completion marker commit in one transaction, and failed migration preserves the source for a later startup retry. Frontend `npm run typecheck -- --pretty false` passed.
- Verification limits: targeted Vitest invocation failed before collection with `EPERM` resolving `src/stores/chatStore.test.ts`. The earlier TestClient route test timed out while Windows asyncio initialized `socket.socketpair()`; direct handler regressions pass. No full repository suite was run.

## Repairs, causes, and invariants

### Transcript archive rotation

- Structural cause: archive paths are ordered newest-first, but rotation moved in the opposite direction. The writer also rotated once per queued batch, so a large batch could cross the threshold without another rotation check.
- Invariant: current rows move to `.old1`, prior `.old1` moves to `.old2`, and rotation preserves chronological order. A batch checks the threshold between chunks. Once both archive slots are occupied, the source contract stops replacing archives and keeps appending the current file, preserving rows.
- Before: the transcript regression suite failed on archive generation/order and on the previous eviction assertion. The old assertion expected rows to disappear even though `_maybe_rotate` deliberately stops when both archive slots are full; it was changed to assert exact ordered conservation.
- After: `python/tests/test_transcript_rotation.py` passed as part of the combined targeted run (5 tests).
- Remaining design limit: when both archives are occupied, the current transcript can grow beyond the configured threshold. The current source contract prioritizes history preservation over a hard total-size cap.

### Memory frontmatter and identity migration

- Structural causes: double-quoted scalars were sliced rather than JSON-decoded; a map placeholder `{}` was retained when list syntax followed; title-derived filenames collided for distinct IDs; and SQLite cache deduplication selected the lexically later legacy copy when canonical and legacy files coexisted.
- Invariant: note ID is the file identity; a canonical file must be validated before publication, legacy files and index references must remain usable across interrupted migration, and reads must prefer the canonical copy for the same ID.
- Before: focused regressions failed for list parsing, escaped frontmatter strings, same-title identity collision, and interrupted index migration (the cached body stayed `old body` rather than `new body`).
- After: `memdir.py` uses identity-addressed filenames and verified atomic publication; migration rewrites exact legacy index paths before removing same-ID legacy files; filesystem and SQLite reads prefer canonical identity paths. Seven focused memory tests passed in the combined run.
- Migration failure behavior: if index publication fails, the new canonical file and old legacy file both remain, the index stays on the old path, and reads select the canonical content. A later retry can complete cleanup.

### Rewind blob GC reference inventory

- Structural cause: `_iter_jsonl` skips malformed lines. GC treated that partial scan as complete, so a blob referenced only by a damaged record could be classified as unreachable and deleted.
- Invariant: deletion requires a readable, stable reference inventory. If a known reference journal is malformed, unreadable, or changes during the scan, every snapshot blob is treated as reachable for that GC pass.
- Before: `test_gc_keeps_all_blobs_when_reference_journal_is_corrupt` failed because one blob was deleted (`deleted == 1`).
- After: corrupt/incomplete inventory yields no deletable blobs; the full `python/tests/test_blob_gc.py` module passed in the combined run.

## Verification record

Environment: `python/.venv/Scripts/python.exe` (Python 3.11.9). Pytest basetemp was kept under the repository `.tmp` directory because the OS temporary directory produced a Windows `os.replace` permission failure.

Earlier targeted command completed with exit code 0:

```powershell
$target = Join-Path (Resolve-Path .tmp) 'remediation-tests-20261015-16'
.\python\.venv\Scripts\python.exe -m py_compile python\rewind\blob_gc.py python\tests\test_blob_gc.py python\memory\memindex.py python\memory\memdir.py python\tests\test_memdir.py python\session\record_transcript.py python\tests\test_transcript_rotation.py
.\python\.venv\Scripts\python.exe -m pytest -q --basetemp $target python\tests\test_blob_gc.py python\tests\test_transcript_rotation.py python\tests\test_rewind_discard_rotated.py python\tests\test_memdir.py::test_applies_to_roundtrips_as_a_nonempty_list python\tests\test_memdir.py::test_same_title_slug_keeps_distinct_note_ids python\tests\test_memdir.py::test_frontmatter_escaped_strings_roundtrip python\tests\test_memdir.py::test_legacy_title_migration_is_identity_scoped python\tests\test_memdir.py::test_legacy_file_survives_failed_identity_migration python\tests\test_memdir.py::test_legacy_file_survives_failed_index_migration python\tests\test_memdir.py::test_note_write_rejects_identity_collision_without_overwrite
```

Result: `26 passed in 1.73s`; `py_compile` also exited 0. The complete `test_memdir.py` module was not completed: an earlier attempt stalled in a pre-existing async test at Windows `socket.socketpair()` and was interrupted. No full repository suite was run.

## Remaining

- The task-provided finding text and acceptance conditions are mapped above; no clarification remains outstanding.
- IndexedDB migration has no browser-level runtime regression yet. The targeted Vitest run failed before collection with Windows sandbox `EPERM` resolving `src/stores/chatStore.test.ts`.
- POSIX file-mode coverage is skipped on Windows. No full repository test suite was run.
- Pytest basetemp paths created for this batch (`.tmp/remediation-tests-20261015-22` through `-29`) were verified under `.tmp` and removed after testing.
