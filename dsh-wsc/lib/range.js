/**
 * Surface range selection, ported from `dsh-compaction-basic` `selectCompactableRange`.
 *
 * The range starts at the first non-system surface node, retains a priced
 * recent tail, and never splits an assistant tool-call/result pair.
 *
 * @param {object} session session owning the surface.
 * @param {{ nodes: ReadonlyArray<{ seq: number, tokens: number }> }} measurement token-meter measurement.
 * @param {number} retainTokens minimum recent-tail budget kept verbatim.
 * @param {(session: object, seq: number) => boolean} balancedBefore tool-pairing boundary check.
 * @returns {{ start: number, end: number } | null} inclusive positional range, or null.
 */
import { eventAt } from './session.js'

export function selectCompactableRange(session, measurement, retainTokens, balancedBefore) {
  const priced = measurement.nodes
  if (priced.length === 0) return null

  const surface = session.surface.nodes
  if (surface.length !== priced.length) {
    throw new Error('wsc: token-meter surface does not match the current session surface')
  }
  for (let index = 0; index < surface.length; index += 1) {
    if (surface[index] !== priced[index].seq) {
      throw new Error('wsc: token-meter surface does not match the current session surface')
    }
  }

  const head = eventAt(session, surface[0])
  const firstIdx = head !== undefined && head.type === 'system/message' ? 1 : 0

  let accumulated = 0
  let keepFromIdx = priced.length
  for (let index = priced.length - 1; index >= 0; index -= 1) {
    accumulated += priced[index].tokens
    keepFromIdx = index
    if (accumulated >= retainTokens) break
  }

  if (keepFromIdx <= firstIdx) return null

  while (keepFromIdx > firstIdx) {
    if (balancedBefore(session, surface[keepFromIdx])) break
    keepFromIdx -= 1
  }
  if (keepFromIdx <= firstIdx) return null

  return { start: surface[firstIdx], end: surface[keepFromIdx - 1] }
}
