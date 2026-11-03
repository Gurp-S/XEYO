/**
 * UTF-8 byte accounting.
 *
 * WSC budgets every view in UTF-8 bytes of canonical JSON
 * (`len(encode(x).encode("utf-8"))`), never in characters. The port keeps the
 * same unit so a CJK region is not measured as if it were ASCII.
 */

/**
 * UTF-8 byte length of a string.
 *
 * @param {string} text measured text.
 * @returns {number} byte length.
 */
export function byteLength(text) {
  return Buffer.byteLength(String(text ?? ''), 'utf8')
}

/**
 * UTF-8 byte length of a value's JSON form.
 *
 * @param {unknown} value measured value.
 * @returns {number} byte length, or 0 when the value cannot be serialized.
 */
export function jsonBytes(value) {
  try {
    return byteLength(JSON.stringify(value))
  } catch {
    return 0
  }
}

/**
 * Cut a string to at most `limit` UTF-8 bytes without splitting a code point.
 *
 * @param {string} text source text.
 * @param {number} limit byte budget.
 * @returns {string} a prefix within the budget.
 */
export function truncateBytes(text, limit) {
  const value = String(text ?? '')
  if (!(limit > 0)) return ''
  if (byteLength(value) <= limit) return value
  let out = ''
  let used = 0
  for (const char of value) {
    const size = byteLength(char)
    if (used + size > limit) break
    out += char
    used += size
  }
  return out
}
