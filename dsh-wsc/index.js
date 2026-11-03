import { loadDshPackage } from './lib/resolve.js'
import { resolvePayloadPolicy } from './lib/payload.js'

const { default: z } = await loadDshPackage('@deepseek-ai/schemastery')
const { Service } = await loadDshPackage('@deepseek-ai/cordis')

const clamp = (value, min, max, fallback) =>
  typeof value === 'number' && Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : fallback

/**
 * Mark a field live-editable where the running schemastery supports it.
 *
 * Desktop builds ship a schemastery with `Schema#volatile`; the CLI build ships
 * 3.18.1, which has no such method. Falling back to the plain default keeps the
 * schema loadable there — the policy is still read at construction, only live
 * re-editing from the Settings form is unavailable on those builds.
 */
const live = (schema, fallback) => {
  const field = schema.default(fallback)
  return typeof field.volatile === 'function' ? field.volatile() : field
}

/**
 * Live compaction policy. Every field is volatile so the Settings form can
 * rewrite it without a restart; the engine reads this service on each step.
 */
export const Config = z.object({
  mode: live(z.string(), 'active'),
  capacityMode: live(z.string(), 'ratio'),
  // Share of the usable window the region may grow to before a compaction is
  // due. Measured on the real fixture: a 48k budget (≈75% of the window) used
  // 199k input tokens against 1.06M at 16k, for the same score — the budget
  // was the compaction-frequency knob, and a small one buys nothing.
  // 70 keeps the checkpoint region at ~85% of the window, so a real task
  // compacts a few dozen times instead of a few hundred. On the echo fixture
  // that is 3x less input and wall clock for the same score (48k arm 0.905 over
  // three valid runs vs native 0.963 over three; see
  // experiments/report/DIRECTION-1-2-FINDINGS.md).
  capacityPercent: live(z.number().min(1).max(100), 70),
  capacityTokens: live(z.number().step(1).min(1024), 100000),
  warnRatio: live(z.number().min(0.5).max(0.95), 0.8),
  forceRatio: live(z.number().min(0.5).max(0.99), 0.85),
  retainRatio: live(z.number().min(0).max(0.5), 0.16),
  // Share of the budget a compaction must reclaim before it is worth a full
  // selection round trip. 0 keeps every request (the shipped behaviour).
  minReclaimRatio: live(z.number().min(0).max(1), 0),
  selection: live(z.string(), 'selective'),
  // Byte cap per control item. 0 removes the per-item cap and leaves the
  // decision to the section budget. The 800 default is the shipped behaviour.
  controlItemCap: live(z.number().step(1).min(0), 800),
  // Output budget of one selection request. A reasoning model spends part of it
  // on reasoning, so this is not a JSON-size cap.
  selectionMaxTokens: live(z.number().step(1).min(1024), 4096),
  // Line addressing: the model names lines, the engine copies the bytes, so a
  // compaction spends a few hundred output tokens instead of a few thousand.
  selectionAddress: live(z.string(), 'quotes'),
  // Checkpoint payload policy (lib/payload.js). Every default below is the
  // shipped behaviour, so an unset profile is unchanged. The knobs exist to
  // test whether a bigger checkpoint stops the post-compaction re-read loop
  // measured in experiments/report/COST-ATTRIBUTION.md.
  payloadFraction: live(z.number().min(0.05).max(2), 0.35),
  payloadMaxChars: live(z.number().step(1).min(600), 24000),
  payloadQuoteMaxChars: live(z.number().step(1).min(1200), 1200),
  payloadSelectedItemCap: live(z.number().step(1).min(200), 1200),
  payloadFactMaxChars: live(z.number().step(1).min(320), 320),
  payloadJudgmentItemCap: live(z.number().step(1).min(80), 320),
  payloadVerificationItemCap: live(z.number().step(1).min(80), 220),
  payloadPriorItemCap: live(z.number().step(1).min(200), 1200),
  payloadPriorEchoDepth: live(z.number().step(1).min(0).max(8), 0),
  payloadOutputsItemCap: live(z.number().step(1).min(60), 240),
  // Project `tool-result` blocks into the selection transcript (0 = shipped).
  payloadToolText: live(z.number().step(1).min(0).max(1), 0),
  payloadOutputsItems: live(z.number().step(1).min(0).max(64), 6),
  payloadOutputsWeight: live(z.number().min(0.05).max(4), 0.2),
  // Carry the last known content of each read/written file through a compaction.
  // Off keeps the shipped behaviour: the checkpoint names files but not their
  // contents, so the model re-reads them after every compaction.
  payloadWorkingset: live(z.boolean(), false),
  payloadWorkingsetFiles: live(z.number().step(1).min(0).max(24), 6),
  payloadWorkingsetItemCap: live(z.number().step(1).min(200), 700),
  payloadWorkingsetVersion: live(z.number().step(1).min(1).max(2), 2),
  payloadWorkingsetSectionCap: live(z.number().step(1).min(400), 2500),
  // Engine-side backfill of recent tool output into the selective checkpoint:
  // selection alone left most of the budget unused, so the model re-ran
  // commands to recover output the checkpoint could have carried.
  payloadBackfill: live(z.boolean(), false),
  payloadBackfillItems: live(z.number().step(1).min(0).max(24), 10),
  payloadBackfillItemCap: live(z.number().step(1).min(200), 900),
  denoise: live(z.boolean(), false),
  evidenceTool: live(z.boolean(), true),
})

/**
 * Host-plane configuration owner. It lives at the profile level because the
 * Settings service projects profile entries only; the compaction engine runs
 * inside an agent preset and reads this service.
 */
export default class WscConfigService extends Service {
  static Config = Config

  constructor(ctx, config = {}) {
    super(ctx, 'wscConfig')

    const warnRatio = clamp(config.warnRatio, 0.5, 0.95, 0.8)
    const forceRatio = clamp(config.forceRatio, 0.5, 0.99, 0.85)

    this.value = Object.freeze({
      mode: config.mode === 'shadow' || config.mode === 'off' ? config.mode : 'active',
      capacityMode: config.capacityMode === 'tokens' ? 'tokens' : 'ratio',
      capacityPercent: clamp(config.capacityPercent, 1, 100, 70),
      capacityTokens:
        Number.isInteger(config.capacityTokens) && config.capacityTokens >= 1024
          ? config.capacityTokens
          : 100000,
      warnRatio,
      forceRatio: Math.max(warnRatio, forceRatio),
      retainRatio: clamp(config.retainRatio, 0, 0.5, 0.16),
      minReclaimRatio: clamp(config.minReclaimRatio, 0, 1, 0),
      selection: config.selection === 'basic' || config.selection === 'deterministic' ? config.selection : 'selective',
      // How the selection request addresses the region: 'quotes' copies the
      // text back (shipped), 'lines' names line ranges and the engine copies.
      selectionAddress: config.selectionAddress === 'lines' ? 'lines' : 'quotes',
      controlItemCap:
        Number.isInteger(config.controlItemCap) && config.controlItemCap >= 0
          ? config.controlItemCap
          : 800,
      selectionMaxTokens:
        Number.isInteger(config.selectionMaxTokens) && config.selectionMaxTokens >= 1024
          ? config.selectionMaxTokens
          : 4096,
      payload: resolvePayloadPolicy(config),
      workingset:
        config.payloadWorkingset === true
          ? {
              maxFiles: Number.isInteger(config.payloadWorkingsetFiles)
                ? Math.max(0, config.payloadWorkingsetFiles)
                : 8,
              capChars: Number.isInteger(config.payloadWorkingsetItemCap)
                ? Math.max(200, config.payloadWorkingsetItemCap)
                : 1200,
              version: Number.isInteger(config.payloadWorkingsetVersion)
                ? config.payloadWorkingsetVersion
                : 1,
              sectionCap: Number.isInteger(config.payloadWorkingsetSectionCap)
                ? Math.max(400, config.payloadWorkingsetSectionCap)
                : 1500,
            }
          : undefined,
      outputs:
        config.payloadBackfill === true
          ? {
              items: Number.isInteger(config.payloadBackfillItems)
                ? Math.max(0, config.payloadBackfillItems)
                : 10,
              cap: Number.isInteger(config.payloadBackfillItemCap)
                ? Math.max(200, config.payloadBackfillItemCap)
                : 900,
            }
          : undefined,
      denoise: config.denoise === true,
      evidenceTool: config.evidenceTool !== false,
    })

    // The bundle ships its own Settings page; keep the schema-derived page off
    // so the two never render the same fields twice.
    ctx.inject(['settings'], (child) => {
      child.effect(() => child.settings.configure({ auto: false }, ctx.fiber))
    })
  }
}
