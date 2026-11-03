/**
 * Pressure decision, ported from XENYON `memory/wsc_timing.py::decide`.
 *
 * Integer cross multiplication keeps floor rounding from admitting a request
 * below the real threshold on small or non-round capacities.
 *
 * @param {number} inputTokens current complete-request estimate.
 * @param {number} capacity declared context capacity.
 * @param {{ modelRequested?: boolean, notified?: boolean, warnPercent?: number, forcePercent?: number }} options
 * @returns {{ tokens: number, capacity: number, action: 'capacity'|'model'|'keep', notify: boolean }}
 */
export function decide(inputTokens, capacity, options = {}) {
  const tokens = Math.max(0, Math.trunc(inputTokens || 0))
  const limit = Math.max(0, Math.trunc(capacity || 0))
  const warnPercent = Math.trunc(options.warnPercent ?? 80)
  const forcePercent = Math.trunc(options.forcePercent ?? 85)
  const forced = limit > 0 && tokens * 100 >= limit * forcePercent
  const notify = limit > 0 && tokens * 100 >= limit * warnPercent && options.notified !== true
  const action = forced ? 'capacity' : options.modelRequested === true ? 'model' : 'keep'
  return { tokens, capacity: limit, action, notify }
}

/**
 * Cooperative override, ported from `memory/wsc_cooperative_compaction.py::adjust`.
 *
 * Below the hard boundary an early pressure action becomes a soft request, so
 * the model owns ordinary compaction and the declared capacity owns the hard
 * boundary.
 *
 * @param {{ action: string, tokens: number, capacity: number, notify: boolean }} timing
 * @param {number} forcePercent hard boundary percentage.
 * @returns the same timing, or one with `action: 'keep'`.
 */
export function adjust(timing, forcePercent = 85) {
  if (
    timing.capacity > 0 &&
    timing.action === 'capacity' &&
    timing.tokens * 100 < timing.capacity * Math.trunc(forcePercent)
  ) {
    return { ...timing, action: 'keep' }
  }
  return timing
}

/**
 * Percentage of capacity currently used, truncated to one decimal.
 *
 * @param {number} tokens measured tokens.
 * @param {number} capacity declared capacity.
 * @returns {number} percentage, or 0 without capacity.
 */
export function usedPercent(tokens, capacity) {
  if (!(capacity > 0)) return 0
  return Math.round((tokens * 1000) / capacity) / 10
}
