/**
 * Compaction admission: is this request worth a full selection round trip?
 *
 * A model-requested compaction is honoured at whatever pressure the model
 * happens to be at, and the range is chosen as "everything before the retained
 * tail". At low pressure that range is small: measured runs compacted at ~10k
 * tokens with a 24k budget and a 0.16 retain ratio, reclaiming ~6.5k tokens per
 * call, so the context regrew past the trigger within two steps and the run
 * spent 44% of its wall clock producing checkpoints.
 *
 * The floor is a ratio of the budget, not an absolute token count: the budget is
 * what the operator configured as "worth compacting down to", so a reclaim that
 * is a small share of it cannot pay for the call.
 *
 * @param {{ action: string, tokens: number, capacity: number }} timing pressure decision.
 * @param {{ budget: number, retainTokens: number, minReclaimRatio?: number }} options
 * @returns {{ admit: boolean, reclaimTokens: number, floor: number, reason: string }}
 */
export function admitCompaction(timing, options) {
  const budget = Math.max(0, Math.trunc(options?.budget ?? 0))
  const retainTokens = Math.max(0, Math.trunc(options?.retainTokens ?? 0))
  const ratio = Number(options?.minReclaimRatio ?? 0)
  const tokens = Math.max(0, Math.trunc(timing?.tokens ?? 0))
  const reclaimTokens = Math.max(0, tokens - retainTokens)
  const floor = Math.floor(budget * (Number.isFinite(ratio) && ratio > 0 ? ratio : 0))

  // The hard boundary is not negotiable: pressure at or above forceRatio must
  // compact even when the reclaim looks small, or the request overflows.
  if (timing?.action === 'capacity') {
    return { admit: true, reclaimTokens, floor, reason: 'forced' }
  }
  if (floor === 0) {
    return { admit: true, reclaimTokens, floor, reason: 'policy-off' }
  }
  if (reclaimTokens >= floor) {
    return { admit: true, reclaimTokens, floor, reason: 'reclaim-above-floor' }
  }
  return { admit: false, reclaimTokens, floor, reason: 'reclaim-below-floor' }
}
