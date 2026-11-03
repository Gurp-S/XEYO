/**
 * Durable understanding records, ported from XENYON `wsc/understanding.py`
 * and `wsc/understanding_identity.py`.
 *
 * A record is model-authored: text, kind, optional scope, and the sources that
 * support it. Identity is either supplied by the writer or a fresh uuid; every
 * write appends a revision row to a per-session journal, and a revision is only
 * accepted when it names the revision it replaces (compare-and-swap). The
 * journal is append-only, so replay never depends on the checkpoint text.
 */
import { appendFileSync, mkdirSync, readFileSync } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { dirname } from 'node:path'

const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9_.:@-]*$/

/** @param {string} code @returns {never} */
const fail = (code) => {
  throw new Error(code)
}

/** @param {unknown} value @returns {boolean} */
const isPlainObject = (value) =>
  value !== null && typeof value === 'object' && !Array.isArray(value)

/** @param {string} value @param {string} code */
const identifier = (value, code) => {
  if (typeof value !== 'string' || !IDENTIFIER.test(value)) fail(code)
}

export class UnderstandingStore {
  /** @param {{ file: string }} options journal path. */
  constructor({ file }) {
    if (typeof file !== 'string' || file.length === 0) fail('understanding_store_path_invalid')
    this.file = file
    this.cache = null
  }

  /** @returns {Map<string, object[]>} id → revision rows, oldest first. */
  rows() {
    if (this.cache !== null) return this.cache
    const rows = new Map()
    let text
    try {
      text = readFileSync(this.file, 'utf8')
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error
      text = ''
    }
    for (const line of text.split('\n')) {
      if (line.trim() === '') continue
      const record = JSON.parse(line)
      const list = rows.get(record.id) ?? []
      list.push(record)
      rows.set(record.id, list)
    }
    for (const list of rows.values()) list.sort((a, b) => a.revision - b.revision)
    this.cache = rows
    return rows
  }

  /** @returns {object[]} the newest revision of every record, ordered by id. */
  all() {
    return [...this.rows().entries()]
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([, list]) => list[list.length - 1])
  }

  /**
   * Resolve an exact `id@revision` reference. References are identities, never
   * parsed as paths.
   *
   * @param {string} ref
   * @returns {object} the record.
   */
  resolve(ref) {
    if (typeof ref !== 'string' || !ref.includes('@')) fail('understanding_reference_missing')
    const at = ref.lastIndexOf('@')
    const list = this.rows().get(ref.slice(0, at))
    const revision = Number(ref.slice(at + 1))
    const record = list?.find((row) => row.revision === revision)
    if (record === undefined) fail('understanding_reference_missing')
    return record
  }

  /** @returns {number} how many writes the journal holds. */
  epoch() {
    let total = 0
    for (const list of this.rows().values()) total += list.length
    return total
  }

  /**
   * Append one revision.
   *
   * @param {{ text: string, kind: string, sources?: string[], scope?: object|null, id?: string|null, expectedRevision?: number|null }} value
   * @param {{ producer: string, allowedSources?: Iterable<string>|null }} options
   * @returns {object} the stored record.
   */
  write(value, options) {
    const producer = options?.producer
    identifier(producer, 'understanding_producer_invalid')
    if (typeof value?.text !== 'string' || value.text.trim() === '') fail('understanding_text_empty')
    identifier(value.kind, 'understanding_kind_invalid')
    if (value.scope !== undefined && value.scope !== null && !isPlainObject(value.scope)) {
      fail('invalid_understanding_scope')
    }
    const sources = value.sources ?? []
    if (!Array.isArray(sources) || sources.some((source) => typeof source !== 'string')) {
      fail('understanding_source_invalid')
    }
    if (options?.allowedSources !== undefined && options.allowedSources !== null) {
      const known = new Set(options.allowedSources)
      if (sources.some((source) => !known.has(source))) fail('understanding_source_missing')
    }
    const expectedRevision = value.expectedRevision ?? null
    if (expectedRevision !== null && (!Number.isInteger(expectedRevision) || expectedRevision <= 0)) {
      fail('understanding_revision_invalid')
    }
    const id = value.id ?? randomUUID().replaceAll('-', '')
    identifier(id, 'understanding_id_invalid')
    const previousList = this.rows().get(id) ?? []
    const previous = previousList.length === 0 ? null : previousList[previousList.length - 1].revision
    const ok = (previous === null && expectedRevision === null) || (previous !== null && expectedRevision === previous)
    if (!ok) fail('understanding_revision_conflict')
    const revision = (previous ?? 0) + 1
    const record = {
      text: value.text,
      kind: value.kind,
      sources: [...sources],
      scope: value.scope ?? null,
      id,
      revision,
      ref: `${id}@${revision}`,
      producer,
      previous: previous === null ? null : `${id}@${previous}`,
    }
    mkdirSync(dirname(this.file), { recursive: true })
    appendFileSync(this.file, `${JSON.stringify(record)}\n`)
    const list = previousList.concat(record)
    this.rows().set(id, list)
    return record
  }
}
