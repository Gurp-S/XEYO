/**
 * Exact evidence access, ported from XENYON `wsc/evidence.py`.
 *
 * Evidence is a shadowed observation, not a live view: a read is authorized
 * against a recorded grant, re-hashed against the digest recorded when the
 * observation was shadowed, and returned as exact bytes with explicit chunk
 * bounds. Nothing here writes session events.
 */
import { createHash } from 'node:crypto'
import {
  appendFileSync,
  closeSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  readSync,
  realpathSync,
  writeSync,
} from 'node:fs'
import { join } from 'node:path'

import { sha256Hex } from './excerpts.js'
import { eventAt } from './session.js'

const REPARSE_POINT = 0x400
const COMPARE_CHUNK_BYTES = 65_536

/** @param {string} code @returns {never} */
const fail = (code) => {
  throw new Error(code)
}

/**
 * Canonical JSON, matching `contracts.encode` in the reference implementation:
 * sorted keys, no insignificant whitespace, non-ASCII preserved.
 *
 * @param {unknown} value JSON value.
 * @returns {string} canonical text.
 */
export function canonicalJson(value) {
  if (value === null) return 'null'
  if (typeof value === 'string') return JSON.stringify(value)
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) fail('invalid_json_value')
    return Number.isInteger(value) ? String(value) : JSON.stringify(value)
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(',')}]`
  if (typeof value === 'object') {
    const keys = Object.keys(value)
      .filter((key) => value[key] !== undefined)
      .sort()
    return `{${keys.map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`
  }
  fail('invalid_json_value')
}

/** @param {unknown} value JSON value @returns {string} lowercase hex sha256 of its canonical bytes. */
export const digest = (value) => sha256Hex(canonicalJson(value))

/** @param {Buffer|Uint8Array} bytes @returns {string} lowercase hex sha256. */
export const sha256Bytes = (bytes) => createHash('sha256').update(bytes).digest('hex')

/**
 * Refuse a read that the access policy does not grant.
 *
 * @param {object} store evidence store.
 * @param {(sessionId: string, sourceId: string, action: string) => boolean} access policy.
 * @param {string|number} sourceId addressed source.
 * @param {string} [action]
 */
export function authorize(store, access, sourceId, action = 'read') {
  if (access(store.sessionId, sourceId, action) !== true) fail('Permission denied: source')
}

/**
 * Read exact bytes of one source.
 *
 * Offsets and limits are bytes, and the digest of the whole object is compared
 * with the digest recorded when the observation was shadowed, so a read can
 * never return bytes that differ from the evidence it claims.
 *
 * @param {{ sessionId: string, sourceRow: (id: string|number) => object|undefined }} store
 * @param {(sessionId: string, sourceId: string, action: string) => boolean} access
 * @param {string|number} sourceId
 * @param {{ offset?: number, limit?: number|null }} [options]
 * @returns {{ source_id: string|number, content: string, offset: number, length: number, total_bytes: number, complete: boolean, read_sha256: string, object_sha256: string, representation: string, observed_at: string|undefined }}
 */
export function read(store, access, sourceId, options = {}) {
  const offset = options.offset ?? 0
  const limit = options.limit ?? null
  authorize(store, access, sourceId)
  if (!Number.isInteger(offset) || offset < 0) fail('invalid_offset')
  if (limit !== null && (!Number.isInteger(limit) || limit < 0)) fail('invalid_limit')

  const record = store.sourceRow(sourceId)
  if (record === undefined || record === null) fail('source_unavailable')
  if (digest(record.payload) !== record.digest) fail('source_integrity_mismatch')
  if (record.kind === 'opaque') fail('opaque_source_public_read_unavailable')

  // Native wire values, not claimed original transport bytes.
  const payload = Buffer.from(canonicalJson(record.payload), 'utf8')
  const chunk = limit === null ? payload.subarray(offset) : payload.subarray(offset, offset + limit)
  authorize(store, access, sourceId)
  return {
    source_id: sourceId,
    content: chunk.toString('utf8'),
    offset,
    length: chunk.length,
    total_bytes: payload.length,
    complete: offset === 0 && chunk.length === payload.length,
    read_sha256: sha256Bytes(chunk),
    object_sha256: sha256Bytes(payload),
    representation: 'canonical_native_json_value',
    observed_at: record.observedAt,
  }
}

/**
 * Whether a path is a symlink or a Windows reparse point. An absent path is not
 * a link.
 *
 * @param {string} path
 * @returns {boolean}
 */
export function linkLike(path) {
  try {
    const info = lstatSync(path)
    if (info.isSymbolicLink()) return true
    if (process.platform !== 'win32') return false
    if ((info.mode & REPARSE_POINT) !== 0) return true
    return realpathSync(path) !== path
  } catch {
    return false
  }
}

/**
 * Compare a file with bytes in bounded chunks; the object is never read whole.
 *
 * @param {string} path
 * @param {Buffer} payload
 * @returns {boolean}
 */
export function sameBytes(path, payload) {
  const info = lstatSync(path)
  if (info.size !== payload.length) return false
  const fd = openSync(path, 'r')
  try {
    const buffer = Buffer.alloc(COMPARE_CHUNK_BYTES)
    let offset = 0
    for (;;) {
      const readBytes = readSync(fd, buffer, 0, COMPARE_CHUNK_BYTES, offset)
      if (readBytes === 0) return offset === payload.length
      if (!buffer.subarray(0, readBytes).equals(payload.subarray(offset, offset + readBytes))) return false
      offset += readBytes
    }
  } finally {
    closeSync(fd)
  }
}

/**
 * Write an evidence object once. An existing object is never replaced and a
 * link leaf is never followed.
 *
 * @param {string} path
 * @param {Buffer} payload
 * @param {{ sync?: boolean }} [options]
 */
export function writeOnce(path, payload, options = {}) {
  const sync = options.sync ?? true
  let fd
  try {
    fd = openSync(path, 'wx')
  } catch (error) {
    if (error?.code !== 'EEXIST') throw error
    if (linkLike(path)) fail('evidence_path_symlink')
    if (!sameBytes(path, payload)) fail('evidence_object_conflict')
    return
  }
  try {
    writeSync(fd, payload)
    if (sync) fsyncSync(fd)
  } finally {
    closeSync(fd)
  }
}

/**
 * Export sources into a content-addressed directory.
 * @param {(sessionId: string, sourceId: string, action: string) => boolean} access
 * @param {readonly (string|number)[]} sourceIds
 * @param {string} directory
 * @param {{ writeObject?: (path: string, payload: Buffer) => void }} [options]
 * @returns {Record<string, object>} locators keyed by source id.
 */
export function exportSources(store, access, sourceIds, directory, options = {}) {
  const writeObject = options.writeObject ?? writeOnce
  mkdirSync(directory, { recursive: true })
  const target = realpathSync(directory)
  const locators = {}
  for (const sourceId of sourceIds) {
    authorize(store, access, sourceId, 'export')
    const record = store.sourceRow(sourceId)
    if (record === undefined || record === null) fail('source_unavailable')
    if (digest(record.payload) !== record.digest) fail('source_integrity_mismatch')
    const raw = Buffer.from(canonicalJson(record.payload), 'utf8')
    const hash = sha256Bytes(raw)
    const filePath = join(target, `${hash}.json`)
    writeObject(filePath, raw)
    const locator = {
      source_id: sourceId,
      file_path: filePath,
      sha256: hash,
      representation: 'canonical_native_json_value',
      observed_at: record.observedAt,
    }
    if (record.text !== null && record.text !== undefined) {
      const text = Buffer.from(String(record.text), 'utf8')
      const textHash = sha256Bytes(text)
      const readablePath = join(target, `${textHash}.txt`)
      writeObject(readablePath, text)
      locator.readable_path = readablePath
      locator.readable_sha256 = textHash
    }
    locators[sourceId] = locator
  }
  return locators
}

const EVIDENCE_INDEX_DIR = 'evidence'

const safeSessionId = (sessionId) => String(sessionId ?? 'session').replace(/[^A-Za-z0-9._-]/g, '_')

/**
 * Evidence store and access policy over a DSH session and its recorded index.
 *
 * Only seqs the ledger recorded are evidence, and only for the session that
 * recorded them, so an unrecorded seq is refused before its bytes are touched.
 *
 * @param {{ id: string, eventAt: (seq: number) => object|undefined, deriveEventMessage: (event: object) => object|null|undefined }} session
 * @param {Map<number, { seq: number, digest: string }>} index rows loaded by `loadEvidence`.
 * @param {(message: object) => string} textOf message text projection.
 * @returns {{ store: object, access: (sessionId: string, sourceId: string|number, action: string) => boolean }}
 */
export function sessionStore(session, index, textOf) {
  const store = {
    sessionId: session.id,
    sourceRow: (sourceId) => {
      const recorded = index.get(Number(sourceId))
      if (recorded === undefined) return undefined
      const event = eventAt(session, recorded.seq)
      if (event === undefined) return undefined
      const message = session.deriveEventMessage(event)
      if (message === null || message === undefined) return undefined
      return {
        seq: recorded.seq,
        kind: 'message',
        payload: message,
        text: textOf(message),
        digest: recorded.digest,
      }
    },
  }
  const access = (sessionId, sourceId) => sessionId === session.id && index.has(Number(sourceId))
  return { store, access }
}

/**
 * Append the shadowed-observation index for a session.
 *
 * A row records the digest of the observation at the moment it was shadowed, so
 * a later read can prove the bytes it returns are the bytes that were hidden.
 * Re-recording a seq is allowed; the newest row wins on load.
 *
 * @param {string} home DSH home directory.
 * @param {string} sessionId session id.
 * @param {readonly { seq: number, digest: string, bytes?: number, observedAt?: string }[]} entries rows.
 * @returns {number} rows written.
 */
export function recordEvidence(home, sessionId, entries) {
  if (typeof home !== 'string' || home === '') fail('evidence_home_unavailable')
  const rows = entries
    .filter((entry) => Number.isInteger(entry?.seq) && typeof entry.digest === 'string')
    .map((entry) =>
      JSON.stringify({
        seq: entry.seq,
        digest: entry.digest,
        bytes: entry.bytes ?? 0,
        ...(entry.observedAt === undefined ? {} : { observedAt: entry.observedAt }),
      }),
    )
  if (rows.length === 0) return 0
  const dir = join(home, 'wsc', EVIDENCE_INDEX_DIR)
  mkdirSync(dir, { recursive: true })
  appendFileSync(join(dir, `${safeSessionId(sessionId)}.jsonl`), `${rows.join('\n')}\n`, 'utf8')
  return rows.length
}

/**
 * Load the shadowed-observation index for a session.
 *
 * @param {string} home DSH home directory.
 * @param {string} sessionId session id.
 * @returns {Map<number, { seq: number, digest: string, bytes: number, observedAt?: string }>} rows by seq.
 */
export function loadEvidence(home, sessionId) {
  const index = new Map()
  if (typeof home !== 'string' || home === '') return index
  let raw
  try {
    raw = readFileSync(join(home, 'wsc', EVIDENCE_INDEX_DIR, `${safeSessionId(sessionId)}.jsonl`), 'utf8')
  } catch {
    return index
  }
  for (const line of raw.split('\n')) {
    if (line.trim().length === 0) continue
    try {
      const row = JSON.parse(line)
      if (Number.isInteger(row?.seq) && typeof row.digest === 'string') index.set(row.seq, row)
    } catch {
      // A corrupt row is not evidence; skip it rather than fail the whole index.
    }
  }
  return index
}
