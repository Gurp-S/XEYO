/**
 * Install handshake for one checkpoint, ported from XENYON `wsc/publication.py`.
 *
 * A checkpoint is published to the host as an operation with a lifecycle:
 * `ready` (the package is built and bound) → `installing` → `confirmed` or
 * `rejected`. A reply is only accepted when it is bound to the exact package
 * this side issued, so a reply for another session, another package or another
 * compaction id is refused instead of applied.
 *
 * DSH commits a summary as one atomic event append, so there is no window in
 * which a reply is lost; `reconcile` exists for the case where the journal says
 * an operation started and the log is the only witness of how it ended.
 */
import { appendFileSync, mkdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const JOURNAL_FILE = 'operations.jsonl'

export const TERMINAL = new Set(['confirmed', 'rejected'])

/** States from which a reconcile may still resolve an outcome. */
const RECONCILABLE = new Set(['installing', 'unknown', 'recovery_required'])

/** States of an operation that was definitely never submitted to the host. */
const DISCARDABLE = new Set(['preparing', 'ready', 'failed', 'cancelled', 'rejected'])

/** @param {string} code @returns {never} */
const fail = (code) => {
  throw new Error(code)
}

/**
 * Refuse a reply that is not bound to the package this side issued.
 *
 * @param {{ id: string, package: object }} operation
 * @param {object} receipt host reply.
 */
export function checkBinding(operation, receipt) {
  const pkg = operation.package ?? {}
  const bound =
    receipt !== null &&
    typeof receipt === 'object' &&
    receipt.operationId === operation.id &&
    receipt.packageDigest === pkg.packageDigest &&
    receipt.sessionId === pkg.sessionId &&
    receipt.provider === pkg.provider &&
    receipt.model === pkg.model &&
    receipt.installedThrough === pkg.throughSeq &&
    typeof receipt.receiver === 'string' &&
    receipt.receiver.trim().length > 0 &&
    receipt.evidenceAccessible === true
  if (!bound) fail('host_receipt_binding_mismatch')
}

/**
 * Apply a host reply. A confirmed or rejected operation is idempotent only for
 * the identical reply.
 *
 * @param {{ id: string, state: string, package: object, receipt?: object }} operation
 * @param {object} receipt host reply.
 * @returns {{ id: string, state: string, package: object, receipt: object }}
 */
export function confirm(operation, receipt) {
  if (TERMINAL.has(operation.state)) {
    if (JSON.stringify(operation.receipt) !== JSON.stringify(receipt)) fail('host_receipt_conflict')
    return operation
  }
  if (!RECONCILABLE.has(operation.state) && operation.state !== 'ready') {
    fail('installation_not_started')
  }
  checkBinding(operation, receipt)
  return { ...operation, state: 'confirmed', receipt }
}

/**
 * Publish a package. The host call is the only step that can leave the
 * operation in `installing`, and only that state is reconciled later.
 *
 * @param {{ id: string, state: string, package: object, receipt?: object }} operation
 * @param {{ install: (pkg: object) => object }} host
 * @returns {{ operation: object, receipt?: object }}
 */
export function install(operation, host) {
  if (TERMINAL.has(operation.state)) return { operation, receipt: operation.receipt }
  if (operation.state !== 'ready') fail('installation_outcome_requires_reconciliation')
  const installing = { ...operation, state: 'installing' }
  let receipt
  try {
    receipt = host.install(operation.package)
  } catch (error) {
    return { operation: { ...installing, state: 'unknown' }, error }
  }
  try {
    return { operation: confirm(installing, receipt), receipt }
  } catch (error) {
    return { operation: { ...installing, state: 'recovery_required', receipt }, error }
  }
}

/**
 * Ask the host what became of an operation whose reply never arrived.
 *
 * @param {{ id: string, state: string, package: object, receipt?: object }} operation
 * @param {{ lookup: (id: string) => object|undefined|null }} host
 * @returns {{ id: string, state: string, package: object, receipt: object }}
 */
export function reconcile(operation, host) {
  if (TERMINAL.has(operation.state)) return operation
  if (!RECONCILABLE.has(operation.state)) fail('installation_not_started')
  const receipt = host.lookup(operation.id)
  if (receipt === undefined || receipt === null) fail('host_outcome_unknown')
  return confirm(operation, receipt)
}

/**
 * Abandon an operation that was definitely never submitted.
 *
 * @param {{ id: string, state: string, package: object }} operation
 * @returns {{ id: string, state: string, package: object }}
 */
export function discard(operation) {
  if (!DISCARDABLE.has(operation.state)) fail('publication_outcome_unknown')
  return { ...operation, state: 'cancelled' }
}

const safeSessionId = (sessionId) => String(sessionId ?? 'session').replace(/[^A-Za-z0-9._-]/g, '_')

const journalPath = (home, sessionId) => join(home, 'wsc', 'operations', `${safeSessionId(sessionId)}.jsonl`)

/**
 * Append one operation row. Rows are append-only; the newest row for an id wins.
 *
 * @param {string} home DSH home directory.
 * @param {string} sessionId session id.
 * @param {object} row operation row.
 */
export function recordOperation(home, sessionId, row) {
  if (typeof home !== 'string' || home === '') return
  const dir = join(home, 'wsc', 'operations')
  mkdirSync(dir, { recursive: true })
  appendFileSync(journalPath(home, sessionId), `${JSON.stringify(row)}\n`, 'utf8')
}

/**
 * Load the operation journal of a session.
 *
 * @param {string} home DSH home directory.
 * @param {string} sessionId session id.
 * @returns {Map<string, object>} newest row per operation id.
 */
export function loadOperations(home, sessionId) {
  const operations = new Map()
  if (typeof home !== 'string' || home === '') return operations
  let raw
  try {
    raw = readFileSync(journalPath(home, sessionId), 'utf8')
  } catch {
    return operations
  }
  for (const line of raw.split('\n')) {
    if (line.trim().length === 0) continue
    try {
      const row = JSON.parse(line)
      if (typeof row?.id === 'string') operations.set(row.id, row)
    } catch {
      // A corrupt row is not an operation; skip it rather than fail the journal.
    }
  }
  return operations
}
