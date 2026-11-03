// Replay a recorded compaction region through the checkpoint builder.
//
// The trial sessions record every message and every `compaction/summary`, so the
// exact input a compaction saw can be rebuilt offline. That makes the control-cap
// fix verifiable without spending a model call: same real region, two caps, and
// the only thing that changes is the cap.
//
//   node tools/replay-checkpoint.mjs <session.jsonl.zstd> [--marker <text>]
//
// Prints, per compaction: source bytes, the checkpoint size and control telemetry
// under the shipped cap and under 4000, and whether the marker survives each.
import { buildCheckpoint } from '../../lib/checkpoint.js'
import { readSessionEvents } from './read-session.mjs'
import { regionMessages } from './region.mjs'

const [file, ...rest] = process.argv.slice(2)
if (file === undefined) {
  console.error('usage: node tools/replay-checkpoint.mjs <session.jsonl.zstd> [--marker <text>]')
  process.exit(2)
}
const markerIndex = rest.indexOf('--marker')
const marker = markerIndex === -1 ? '--watch' : rest[markerIndex + 1]

const events = readSessionEvents(file)
const bySeq = new Map(events.map((event) => [event.seq, event]))

const rows = []
const summaries = events.filter((event) => event.type === 'compaction/summary')
for (const [index, summary] of summaries.entries()) {
  const seqs = summary.data.shadowedSeqs
  if (!Array.isArray(seqs) || seqs.length === 0) continue
  const messages = regionMessages(events, seqs)
  if (messages.length === 0) continue
  const shipped = buildCheckpoint({ messages })
  const raised = buildCheckpoint({ messages }, { controlItemCap: 4000 })
  rows.push({
    compaction: index + 1,
    provider: summary.data.provider,
    model: summary.data.model,
    sourceBytes: shipped.sourceBytes,
    shipped: {
      bytes: Buffer.byteLength(shipped.text, 'utf8'),
      controlKept: shipped.control.keptBytes,
      controlSource: shipped.control.sourceBytes,
      keepsMarker: shipped.text.includes(marker),
    },
    raised: {
      bytes: Buffer.byteLength(raised.text, 'utf8'),
      controlKept: raised.control.keptBytes,
      controlSource: raised.control.sourceBytes,
      keepsMarker: raised.text.includes(marker),
    },
  })
}

const table = rows.map((row) => ({
  ...row,
  controlSource: row.shipped.controlSource,
  controlSourceBytes: undefined,
}))
process.stdout.write(`${JSON.stringify({ marker, compactions: table.length, rows: table }, null, 2)}\n`)
