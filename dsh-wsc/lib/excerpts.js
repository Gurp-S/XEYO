/**
 * Exact caller-selected observations, ported from XENYON `wsc/excerpts.py` and
 * `wsc/span_boundaries.py`.
 *
 * A selection is addressed, not quoted: the caller names a source, a path into
 * its payload, and either a character span or an exact fragment. The engine
 * recomputes the sha256 of the selected text, so a selection cannot drift from
 * the bytes it claims. All offsets are Unicode code points, matching Python's
 * `len`/slicing on the reference implementation.
 */
import { createHash } from 'node:crypto'

/** @param {string} text @returns {string} lowercase hex sha256. */
export const sha256Hex = (text) =>
  createHash('sha256').update(String(text ?? ''), 'utf8').digest('hex')

const fail = (code) => {
  throw new Error(code)
}

const isPlainObject = (value) =>
  value !== null && typeof value === 'object' && !Array.isArray(value)

/**
 * Resolve a payload path to the text it addresses.
 *
 * A `null` step decodes a JSON string; an integer step addresses an array
 * index; a string step addresses an object key.
 *
 * @param {unknown} payload source payload.
 * @param {readonly (string|number|null)[]} path address steps.
 * @returns {string} the addressed text.
 */
export function textAt(payload, path) {
  if (!Array.isArray(path)) fail('excerpt_path_invalid')
  let value = payload
  for (const step of path) {
    if (step === null) {
      if (typeof value !== 'string') fail('excerpt_json_value_not_text')
      try {
        value = JSON.parse(value)
      } catch {
        fail('excerpt_json_unavailable')
      }
    } else if (Number.isInteger(step)) {
      if (!Array.isArray(value) || step < 0 || step >= value.length) {
        fail('excerpt_index_unavailable')
      }
      value = value[step]
    } else {
      if (typeof step !== 'string' || !isPlainObject(value) || !(step in value)) {
        fail('excerpt_key_unavailable')
      }
      value = value[step]
    }
  }
  if (typeof value !== 'string') fail('excerpt_value_not_text')
  return value
}

/**
 * Slice by Unicode code point, so offsets mean the same thing as in Python.
 *
 * @param {string} text source text.
 * @param {number} start first code point.
 * @param {number} end exclusive last code point.
 * @returns {string} the selected text.
 */
export function sliceCodepoints(text, start, end) {
  const points = Array.from(String(text ?? ''))
  return points.slice(start, end).join('')
}

/** @param {string} text @returns {number} code point count. */
export const codepointLength = (text) => Array.from(String(text ?? '')).length

/**
 * All code-point offsets where `fragment` occurs exactly.
 *
 * @param {string} text searched text.
 * @param {string} fragment exact fragment.
 * @returns {number[]} start offsets, in ascending order.
 */
export function fragmentOffsets(text, fragment) {
  const haystack = String(text ?? '')
  const needle = String(fragment ?? '')
  if (needle === '') return []
  const starts = []
  let from = 0
  for (;;) {
    const index = haystack.indexOf(needle, from)
    if (index === -1) break
    starts.push(codepointLength(haystack.slice(0, index)))
    from = index + 1
  }
  return starts
}

/**
 * Resolve one addressed selection into exact text plus its digest.
 *
 * @param {Map<string, object>|Record<string, object>} known source id → source.
 * @param {{ source: string, path?: readonly (string|number|null)[], start?: number, end?: number, fragment?: string, basis?: string, sha256?: string }} item selection.
 * @returns {{ source: string, path: readonly unknown[], start: number, end: number, text: string, textSha256: string, basis: string, observedAt?: string, sourceKind?: string, callId?: string }}
 */
export function resolveExcerpt(known, item) {
  const source =
    known instanceof Map ? known.get(item?.source) : Object.prototype.hasOwnProperty.call(known ?? {}, item?.source ?? '') ? known[item.source] : undefined
  if (source === undefined || source === null) fail('excerpt_source_missing')
  if (source.kind === 'opaque') fail('opaque_excerpt_unavailable')

  const basis = item.basis ?? 'payload'
  if (basis !== 'payload' && basis !== 'public_text') fail('excerpt_basis_invalid')

  let text
  let path
  if (basis === 'public_text') {
    const requested = item.path ?? []
    if (requested.length !== 0) fail('public_text_excerpt_path_invalid')
    path = []
    text = textAt(source.text, [])
  } else if (item.path === undefined) {
    // No path: the source's own text is the addressed value, which is what a
    // numbered transcript projection shows the caller.
    path = []
    text = textAt(source.text, [])
  } else {
    path = item.path
    text = textAt(source.payload, path)
  }

  const total = codepointLength(text)
  let start
  let end
  if (item.fragment !== undefined) {
    const starts = fragmentOffsets(text, item.fragment)
    if (starts.length === 0) fail('excerpt_fragment_missing')
    if (starts.length > 1) fail('excerpt_fragment_ambiguous')
    start = starts[0]
    end = start + codepointLength(item.fragment)
  } else {
    start = item.start
    end = item.end
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || start >= end || end > total) {
      fail('excerpt_range_invalid')
    }
  }

  const selected = sliceCodepoints(text, start, end)
  const textSha256 = sha256Hex(selected)
  if (item.sha256 !== undefined && item.sha256 !== textSha256) fail('excerpt_content_mismatch')

  return {
    source: item.source,
    path,
    start,
    end,
    text: selected,
    textSha256,
    basis,
    ...(source.observedAt === undefined ? {} : { observedAt: source.observedAt }),
    ...(source.kind === undefined ? {} : { sourceKind: source.kind }),
    ...(source.callId === undefined ? {} : { callId: source.callId }),
  }
}

/**
 * Bounded lexical partitions, without ranking, omission or rewritten text.
 *
 * A `word` boundary moves an over-limit cut back to the start of the current
 * word, so a partition never splits an identifier; an uninterrupted run longer
 * than the bound still respects the bound and is never discarded or enlarged.
 *
 * @param {string} text source text.
 * @param {number} maxChars maximum partition size in code points.
 * @param {{ policy?: 'fixed'|'word' }} [options]
 * @returns {Array<{ start: number, end: number, text: string }>} partitions.
 */
export function ranges(text, maxChars, options = {}) {
  const policy = options.policy ?? 'fixed'
  if (!Number.isInteger(maxChars) || maxChars <= 0) fail('span_size_invalid')
  if (policy !== 'fixed' && policy !== 'word') fail('span_boundary_policy_invalid')

  const points = Array.from(String(text ?? ''))
  const wordCharacter = (char) => /[\p{L}\p{N}_\-./+@%=]/u.test(char)
  const out = []
  let start = 0
  while (start < points.length) {
    let end = Math.min(start + maxChars, points.length)
    if (policy === 'word' && end < points.length && wordCharacter(points[end - 1]) && wordCharacter(points[end])) {
      let boundary = end
      while (boundary > start && wordCharacter(points[boundary - 1])) boundary -= 1
      if (boundary > start) end = boundary
    }
    out.push({ start, end, text: points.slice(start, end).join('') })
    start = end
  }
  return out
}
