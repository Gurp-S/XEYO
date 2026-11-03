# dsh-wsc — pending work

Tracked so the remaining WSC semantics are not lost between sessions.

## Done

- Version/verification relation section (`## Verification state`), so a check
  that ran before a file change is not read as verifying the current file.
- Evidence retrieval tool `read_history` (seq read + literal query over the
  whole session log), registered per agent.
- Control vs model layering: control messages are their own section, assistant
  quotes carry a role prefix, prior checkpoints are labelled historical.
- Prior-checkpoint drift control: only the newest one is kept, its framing is
  stripped, and it is labelled historical.
- Cost ledger: `$DSH_HOME/wsc/compactions.jsonl`, one row per durable
  `compaction/summary`.
- Understanding layer, text-embedded version: selective selection may return
  `facts: [{ text, sources }]`; each fact is kept only when it cites at least
  one kept quote, rendered as `## Recorded judgments` with `[sN]` references.
  No CAS; the next checkpoint supersedes the previous set.
- Control-cap and selection-budget defects: `controlItemCap` (default 4000,
  UTF-8 bytes) and `selectionMaxTokens` (default 16384) are configuration, and
  every compaction row now carries `control` / `selection` telemetry. Verified
  by offline replay of the recorded B runs; see
  `experiments/report/FIX-AB.md`.

## Understanding layer — durable store

Records now live in `lib/understanding.js` (append-only journal, CAS revisions,
exact `id@revision` refs). What is still deferred is the engine consuming them:
`facts` are rendered inline from the checkpoint text today, and item 6 in the
parity plan tracks the remaining wiring.

## Original WSC record model (reference)

WSC stores a model's explicit judgments as records with:

- sources (source ids that support the judgment),
- category,
- scope (where it applies),
- version / CAS revision,
- no upgrade of a source-less assumption into a fact.

DSH has no equivalent. Design questions before implementing:

1. Where do records live? A new session event type is forbidden (readers reject
   unknown types unless `ignorable: true`, which live append cannot set).
   Options: a storage-domain record keyed by session, or encode them inside the
   checkpoint text with durable ids.
2. How are they revised without breaking replay?
3. How does selective selection reference them (quote ids, record ids)?

## Parity plan (ordered; implement, then test each item)

Reference implementation: `D:\lea\XenYon code\wsc` (python). Every item is
"same mechanism, DSH-shaped wiring only".

1. **Byte budget** — DONE. `lib/bytes.js` (`byteLength`, `jsonBytes`,
   `truncateBytes`); `lib/checkpoint.js` now measures source, budget, section
   allocations and the final cut in UTF-8 bytes (`sourceBytes`, `mandatoryBytes`);
   `engine.js` compares and logs bytes. Tests: `checkpoint: a CJK region is
   budgeted in UTF-8 bytes, not characters`.
2. **Span / exact-fragment selection** — DONE. `lib/excerpts.js` ports
   `excerpts.py` (`textAt`, `resolveExcerpt`, code-point offsets, digest check)
   and `span_boundaries.py` (`ranges`); `lib/selection.js` owns the selection
   surface. The request shows a numbered transcript (`[m<n> <role>]`) built from
   the same numbering the engine resolves against, so the model can address a
   span or an exact fragment as well as a verbatim quote; quotes are still
   verified against the original bytes, and the labels exist only inside the
   request. An oversized region is not projected, and addressed selections are
   then refused rather than resolved against a transcript the model never saw.
   `buildSelectiveCheckpoint` takes `spans`/`fragments` and reports
   `droppedExcerpts`. Tests: `selective:` and `selection:` cases.
3. **Evidence read API** — DONE. `lib/evidence.js` ports `evidence.py`:
   `canonicalJson`/`digest`, `read` (authorize → integrity re-hash against the
   digest recorded at shadowing → exact byte slice → re-authorize, returning
   `read_sha256`/`object_sha256`/`total_bytes`/`complete`), plus `writeOnce`,
   `sameBytes`, `linkLike` and `exportSources` for the lease/export work.
   Shadowed observations are recorded in `$DSH_HOME/wsc/evidence/<session>.jsonl`
   by the ledger; `read_evidence` is registered beside `read_history` and reads
   only seqs that index grants, so an unrecorded seq is refused without
   revealing bytes. Tests: `evidence:` cases.
4. **`reconcile` / unknown-install** — DONE, narrowed by evidence. DSH has no
   bracket transaction or orphan lock: the plugin contract is `eventAt(seq)` plus
   one atomic `compaction/summary` append, so there is no lost-reply window to
   reconcile. What transfers is the binding half of `publication.py`, and it is
   real: `lib/publication.js` ports the operation lifecycle
   (`ready → installing → confirmed`/`rejected`, `unknown`,
   `recovery_required`), `checkBinding` (session, provider, model, package
   digest, `installedThrough`, non-empty receiver, `evidenceAccessible`),
   `confirm`, `install`, `reconcile`, `discard` and a per-session journal at
   `$DSH_HOME/wsc/operations/<session>.jsonl`. `summarize` records the package
   it is about to publish; the ledger confirms only a digest this engine issued
   and reports `unknown_install` otherwise, recording evidence only for a
   confirmed install. Tests: `publication:` cases.
5. **Resource leases + install-time evidence re-check** — DONE, with a stated
   limit. `lib/resources.js` ports `resource_io.py`: `ResourceIO` with a chunk
   budget, `withOpened` (refuses a link leaf, re-checks identity/size/mtime_ns
   after the body), `equal`, `digest` (byte budget + deadline), `readBounded`,
   `capabilities`, `writeOnce` (pending file → fsync → `link`, so an existing
   object is never replaced), `publicationWriter` (memoized while handles pin
   the object), `lease` (every named object plus every parent directory, with a
   handle budget and `installation_resource_unavailable` /
   `installation_resource_budget_exhausted`), `collectPaths` and
   `checkEvidence` (`exported_source_changed` / `exported_readable_changed` /
   `exported_index_changed` / `exported_projection_index_changed` /
   `exported_source_unavailable`). Limit: JavaScript cannot set a Windows share
   mode, so a lease is an identity lease — it records volume/file index, size
   and mtime, holds file handles open, and `verify()` fails closed on drift;
   `capabilities().installation_path_leases` reports `identity`, not `true`.
   Engine producer: the compaction ledger exports every shadowed observation
   with `writeOnce` to `$DSH_HOME/wsc/evidence/<session>/<seq>.json`, records
   `{file_path, sha256: digest(message)}` locators, re-checks them with
   `checkEvidence` before confirming the install, and stores the locators on the
   confirmed operation row (a failed export is reported and leaves no
   locators). Tests: `resources:` cases plus the export/lease step of
   `tests/integration.test.mjs`.

6. **Durable understanding store** — DONE (store + engine write path).
   `lib/understanding.js` ports `understanding.py` + `understanding_identity.py`:
   `UnderstandingStore` over an append-only per-session journal
   (`all`, `resolve` by exact `id@revision`, `epoch`, `write`), with
   compare-and-swap on the stored revision (`understanding_revision_conflict`),
   an optional allowed-source set (`understanding_source_missing`), identifier
   and scope validation, and replay from the journal after a restart. Tests:
   `understanding:` cases.
   Engine wiring: `buildSelectiveCheckpoint` now returns `keptFacts`
   (`{text, sources: ['sN']}`) alongside the rendered section;
   `#summarizeSelective` passes them up; `#recordReady` stores them in the
   operation package; the compaction ledger hook writes one record per kept
   fact (`kind: 'judgment'`, `producer: 'selection'`, `sources` = cited refs,
   `scope = { session, shadowedSeqs }`) after a confirmed install, and skips a
   fact whose text and scope already exist so a replayed hook adds no revision.
   `tests/integration.test.mjs` walks the whole chain (checkpoint → package
   digest → confirm → evidence → record → lease → tamper).
   Still open: the checkpoint still renders the inline list; the next step is to
   render current records (`store.epoch()`) instead. Provenance is checkpoint
   refs, not seqs: the builder resolves a quote to `sN`, so seq provenance needs
   the quote → seq map surfaced from the builder.



## Verification still owed

- 80% notice and 85% forced compaction on a real long session.
- Selective compaction against a real model (quote match rate, fallback rate).
- Runtime denoise on a real tool result (spill pointer present, original readable).
- A/B: `selection: basic` vs `selective` vs `deterministic` on the same session.
- Settings page after a DSH restart (client roster is built at boot).
- Understanding records on a live install: the desktop profile runs
  `mode: shadow`, which never installs, so the write path needs one session in
  `mode: live` (then check `<DSH_HOME>/wsc/understanding/<session>.jsonl`).

## Composition gaps

- `standard` preset is not overridden; only `cordis` uses the WSC engine.
