/**
 * Score policy for the fixture task.
 *
 * `--watch rebuilds after a source change` depends on filesystem watch events,
 * which fire late or not at all on Windows. It failed in three of the four echo
 * arms and passed in the one arm that happened to be idle, so it measures the
 * machine rather than the checkpoint. Unstable assertions are removed from the
 * score but kept in `excluded`, so a real regression there stays visible.
 */

export const UNSTABLE = [
  /--watch rebuilds after a source change/,
  /--concurrency and --watch are supported/,
]

/**
 * Recompute a score over the stable assertions.
 *
 * @param {{ score: number, passed: number, total: number, exitCode?: number, tests: ReadonlyArray<{ name: string, ok: boolean }> }} report
 * @returns the same report with `score`/`passed`/`total` recomputed, the raw
 *   numbers preserved as `rawScore`/`rawPassed`/`rawTotal`, and the excluded
 *   assertions listed.
 */
export function applyScorePolicy(report) {
  const excluded = []
  const stable = []
  for (const entry of report.tests ?? []) {
    if (UNSTABLE.some((pattern) => pattern.test(entry.name))) excluded.push(entry)
    else stable.push(entry)
  }
  const passed = stable.filter((entry) => entry.ok).length
  return {
    ...report,
    score: stable.length === 0 ? 0 : Number((passed / stable.length).toFixed(4)),
    passed,
    total: stable.length,
    rawScore: report.score,
    rawPassed: report.passed,
    rawTotal: report.total,
    excluded,
  }
}
