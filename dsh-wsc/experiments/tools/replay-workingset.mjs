// Rebuild the working-set section from a recorded compaction region.
//
// The trial sessions record every message and every `compaction/summary`, so the
// exact input a compaction saw can be rebuilt offline. This prints the section
// the E arm would have added, using the same region and builder, without
// spending a model call.
//
//   node tools/replay-workingset.mjs <session.jsonl.zstd> [--limit 2]
import { buildCheckpoint } from '../../lib/checkpoint.js'
import { readSessionEvents } from './read-session.mjs'
import { regionMessages } from './region.mjs'

const [file, ...rest] = process.argv.slice(2)
if (file === undefined) {
  console.error('usage: node tools/replay-workingset.mjs <session.jsonl.zstd> [--limit n]')
  process.exit(2)
}
const limitIndex = rest.indexOf('--limit')
const limit = limitIndex === -1 ? 3 : Number(rest[limitIndex + 1])

const events = readSessionEvents(file)
const summaries = events.filter((event) => event.type === 'compaction/summary').slice(-limit)

for (const [index, summary] of summaries.entries()) {
  const seqs = summary.data.shadowedSeqs
  if (!Array.isArray(seqs) || seqs.length === 0) continue
  const messages = regionMessages(events, seqs)
  if (messages.length === 0) continue
  const off = buildCheckpoint({ messages })
  const on = buildCheckpoint({ messages }, { workingset: true })
  const at = on.text.indexOf('## Working set')
  const rest = at === -1 ? '' : on.text.slice(at)
  const next = rest.slice(2).search(/\n## /)
  const section = at === -1 ? '(absent)' : next === -1 ? rest : rest.slice(0, next + 2)
  console.log(
    `\n=== compaction ${index + 1} region=${messages.length} source=${off.sourceBytes}B ` +
      `off=${off.text.length}B on=${on.text.length}B delta=${on.text.length - off.text.length}B`,
  )
  console.log(section)
}
