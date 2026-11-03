/**
 * Checkpoint payload policy.
 *
 * The builders used to hard-code how much of a shadowed region a checkpoint may
 * carry: quotes longer than 1200 characters and facts longer than 320 were
 * dropped outright, every rendered item was capped, and a prior checkpoint was
 * re-inlined verbatim together with its own prior section, so the echo grew
 * while the payload shrank.
 *
 * Measured on the trial sessions (`experiments/report/COST-ATTRIBUTION.md`) a
 * shipped checkpoint carried ~1k characters of new information per compaction
 * against ~13.7k for the native summary, and the agent answered that by
 * re-reading files (92 repeat reads in `b-fix-3` versus 17 in `a-1`), which is
 * what made the run six times as long.
 *
 * Every field defaults to the shipped value, so a caller that passes nothing
 * gets byte-identical output and existing callers keep their behaviour.
 */

/** Shipped payload policy. Changing a default changes every existing caller. */
export const PAYLOAD_DEFAULTS = Object.freeze({
  /** Checkpoint budget as a share of the shadowed region, in bytes. */
  sourceFraction: 0.35,
  /** Absolute ceiling on the checkpoint budget, in bytes. */
  maxChars: 24000,
  /** Longest verbatim quote accepted from a selection, in characters. */
  quoteMaxChars: 1200,
  /** Per-item render cap for the selected-excerpts section. */
  selectedItemCap: 1200,
  /** Longest judgment accepted from a selection, in characters. */
  factMaxChars: 320,
  /**
   * Per-item render cap for the tool-results section, in characters.
   *
   * This is the hard ceiling on how much tool output a deterministic checkpoint
   * can carry: `outputsItems * outputsItemCap` (240 × 6 in the shipped policy)
   * against a region that can be tens of thousands of bytes. Quoting more of it
   * is the lever that the budget knobs turned out not to be.
   */
  outputsItemCap: 240,
  /** Tool results carried into the checkpoint, counted from the newest. */
  outputsItems: 6,
  /**
   * Share of the checkpoint budget the tool-results section may claim.
   *
   * Weights are normalised across the present sections, so the shipped `0.2`
   * gives tool output about 10% of a budget that is itself 35% of the region:
   * roughly 3.5% of the region, whatever the per-item caps allow.
   */
  outputsWeight: 0.2,
  /** Per-item render cap for the judgments section. */
  judgmentItemCap: 320,
  /** Per-item render cap for the verification section. */
  verificationItemCap: 220,
  /**
   * Per-item render cap for the working-set section, in characters.
   *
   * One item is one file: its last known content plus the line saying which
   * message produced that snapshot. This is the only section that carries
   * state the model can act on without re-reading, so its cap is the largest.
   */
  workingsetItemCap: 1200,
  /** Per-item render cap for the prior-checkpoint section. */
  priorItemCap: 1200,
  /**
   * Prior-checkpoint nesting kept verbatim. `0` keeps the shipped behaviour
   * (the prior text is re-inlined as-is, including its own prior section);
   * `1` keeps only the outermost level and drops the nested echo.
   */
  priorEchoDepth: 0,
  /**
   * Whether the selection transcript shows tool results. `0` keeps the shipped
   * behaviour (only `text` blocks are projected, so tool output is invisible to
   * the selection model); `1` projects `tool-result` blocks into the transcript.
   */
  toolText: 0,
})

const NUMBER_FIELDS = Object.keys(PAYLOAD_DEFAULTS).filter(
  (key) => key !== 'priorEchoDepth' && key !== 'outputsItems' && key !== 'toolText',
)
/** Integer fields that may legitimately be 0 (an explicitly empty section). */
const COUNT_FIELDS = ['priorEchoDepth', 'outputsItems', 'toolText']

/** A prior-checkpoint heading, plain or rendered as a bullet by the payload. */
const PRIOR_HEADING = /^\s*(?:-\s*)?#{1,6}\s+Prior checkpoint\b/i
/** Any section heading at column 0. */
const SECTION_HEADING = /^#{1,6}\s+\S/

const positive = (value, fallback) =>
  typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : fallback

const nonNegativeInteger = (value, fallback) =>
  Number.isInteger(value) && value >= 0 ? value : fallback

/**
 * Resolve a payload policy from partial settings.
 *
 * Accepts either a `payload`-shaped object or the flat `wscConfig` settings
 * object the engine holds (`payloadQuoteMaxChars`, `payloadPriorEchoDepth`, …).
 * Unknown or invalid values keep the shipped default, never `undefined`.
 *
 * @param {object | undefined} source partial policy or settings.
 * @returns {typeof PAYLOAD_DEFAULTS} resolved policy.
 */
export function resolvePayloadPolicy(source) {
  const input = source ?? {}
  const read = (key) => (input[key] === undefined ? input[`payload${key[0].toUpperCase()}${key.slice(1)}`] : input[key])
  const policy = {}
  for (const key of NUMBER_FIELDS) policy[key] = positive(read(key), PAYLOAD_DEFAULTS[key])
  for (const key of COUNT_FIELDS) policy[key] = nonNegativeInteger(read(key), PAYLOAD_DEFAULTS[key])
  return Object.freeze(policy)
}

/**
 * Remove the prior-checkpoint block a previous checkpoint inlined into itself.
 *
 * A checkpoint is re-inlined whole, so its own `## Prior checkpoint` section
 * comes along, and that text re-inlines the one before it. Because the section
 * is rendered first, every truncation keeps the echo chain and cuts the content
 * after it, so after a few compactions the checkpoint is a column of headings
 * with nothing under them — measured: 2,130 characters of nothing but nested
 * `## Prior checkpoint` lines.
 *
 * The nested block is dropped structurally rather than by depth policy: it is a
 * stale copy of a copy, and the control section that follows it in the same
 * checkpoint carries the same original request verbatim.
 *
 * @param {string} text previous checkpoint text.
 * @returns {string} text without its nested prior-checkpoint block.
 */
export function stripPriorEcho(text) {
  const lines = String(text ?? '').split('\n')
  const kept = []
  let inside = false
  for (const line of lines) {
    if (PRIOR_HEADING.test(line)) {
      inside = true
      continue
    }
    // A column-0 heading opens the next section; the echo's own lines are
    // bullets, so they never end the block.
    if (inside && SECTION_HEADING.test(line)) inside = false
    if (inside) continue
    if (/^\s*-\s+#{1,6}\s/.test(line)) continue
    kept.push(line)
  }
  return kept.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}

/**
 * Drop nested prior-checkpoint echoes beyond the configured depth.
 *
 * A checkpoint re-inlines the previous checkpoint under its own heading, and
 * that text re-inlines the one before it, so the section grows one indent level
 * per compaction while the payload stays the same size. Depth `1` keeps only
 * the outermost level; `0` is a no-op.
 *
 * Two structural markers identify the echo, because the renderer turns every
 * line of the previous checkpoint into a bullet: the echo's heading arrives as a
 * bulleted heading (`- ## Prior checkpoint …`) and its children arrive one
 * indent level deeper. Both are dropped at depth `1`.
 *
 * @param {string} text prior-checkpoint text.
 * @param {number} depth nesting levels kept.
 * @returns {string} text without the deeper echo.
 */
export function collapsePriorEcho(text, depth) {
  const source = String(text ?? '')
  if (!Number.isInteger(depth) || depth <= 0) return source
  const keepIndent = (depth - 1) * 2
  const kept = []
  for (const line of source.split('\n')) {
    if (line.trim().length === 0) {
      kept.push(line)
      continue
    }
    if (/^\s*-\s+#{1,6}\s/.test(line)) continue
    const indent = line.length - line.trimStart().length
    if (indent > keepIndent) continue
    kept.push(line)
  }
  return kept.join('\n').replace(/\n{3,}/g, '\n\n')
}

/**
 * Section weight under a policy.
 *
 * @param {string} key section key.
 * @param {typeof PAYLOAD_DEFAULTS} policy resolved policy.
 * @param {Record<string, number>} shipped shipped weight table.
 * @returns {number} weight.
 */
export function sectionWeight(key, policy, shipped) {
  if (key === 'outputs') return policy.outputsWeight
  return shipped[key]
}

/**
 * Per-item render cap for a section under a policy.
 *
 * Sections the policy does not name fall back to the shipped table, so a new
 * section can never render unbounded.
 *
 * @param {string} key section key.
 * @param {typeof PAYLOAD_DEFAULTS} policy resolved policy.
 * @param {Record<string, number>} shipped shipped per-section caps.
 * @returns {number | undefined} cap in bytes/characters.
 */
export function payloadItemCap(key, policy, shipped) {
  if (key === 'prior') return policy.priorItemCap
  if (key === 'selected') return policy.selectedItemCap
  if (key === 'judgments') return policy.judgmentItemCap
  if (key === 'verification') return policy.verificationItemCap
  if (key === 'outputs') return policy.outputsItemCap
  return shipped[key]
}
