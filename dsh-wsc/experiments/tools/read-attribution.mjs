// Counterfactual: how many post-compaction reads would the working set answer?
//
// A live trial costs an hour. This reads a recorded session instead and asks the
// question the trial is meant to answer, without a model call: for every
// compaction, rebuild the working set from the shadowed region, then look at the
// `read` calls the model actually made before the next compaction. A read whose
// path is in the working set with a current snapshot is a read the checkpoint
// could have answered; a read whose snapshot is stale is one it could not.
//
//   node tools/read-attribution.mjs <session.jsonl.zstd>
import { createWorkingSet } from '../../lib/workingset.js'
import { readSessionEvents } from './read-session.mjs'
import { regionMessages, toAgentMessage } from './region.mjs'

const [file] = process.argv.slice(2)
if (file === undefined) {
  console.error('usage: node tools/read-attribution.mjs <session.jsonl.zstd>')
  process.exit(2)
}

const events = readSessionEvents(file).sort((left, right) => left.seq - right.seq)
const compactions = events.filter((event) => event.type === 'compaction/summary')
if (compactions.length === 0) {
  console.error('no compaction/summary events in this session')
  process.exit(1)
}

const pathOfArgs = (args) => {
  const value = args?.path ?? args?.file_path
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

const readCallsOf = (messages) => {
  const calls = []
  for (const message of messages) {
    if (message.role !== 'assistant') continue
    for (const block of message.content ?? []) {
      if (block?.type !== 'tool-call' || block.name !== 'read') continue
      let args = block.arguments
      if (typeof args === 'string') {
        try {
          args = JSON.parse(args)
        } catch {
          args = {}
        }
      }
      const path = pathOfArgs(args)
      if (path !== undefined) calls.push(path)
    }
  }
  return calls
}

const rows = []
// One tracker for the whole run: a checkpoint carries its predecessor's set
// forward, so the counterfactual has to accumulate too.
const tracker = createWorkingSet()
for (const [index, compaction] of compactions.entries()) {
  const region = regionMessages(events, compaction.data.shadowedSeqs ?? [])
  if (region.length === 0) continue
  tracker.apply(region)
  const items = tracker.items()
  const current = new Set()
  const stale = new Set()
  for (const item of items) {
    const path = item.slice(0, item.indexOf(' — '))
    if (item.includes('unchanged since')) current.add(path)
    else stale.add(path)
  }

  const next = compactions[index + 1]
  const window = events
    .filter((event) => event.seq > compaction.seq && (next === undefined || event.seq < next.seq))
    .map((event) => toAgentMessage(event))
    .filter((message) => message !== undefined)
  const reads = readCallsOf(window)

  let answered = 0
  let staleRead = 0
  const missed = []
  for (const path of reads) {
    if (current.has(path)) answered += 1
    else {
      if (stale.has(path)) staleRead += 1
      missed.push(path)
    }
  }
  rows.push({
    compaction: index + 1,
    region: region.length,
    items: items.length,
    sectionBytes: items.reduce((total, item) => total + Buffer.byteLength(item), 0),
    reads: reads.length,
    distinct: new Set(reads).size,
    answered,
    staleRead,
    missedDistinct: new Set(missed).size,
  })
}

const total = (key) => rows.reduce((sum, row) => sum + row[key], 0)
console.log(
  ['#', 'region', 'items', 'bytes', 'reads', 'distinct', 'answered', 'stale', 'missed'].join('\t'),
)
for (const row of rows) {
  console.log(
    [
      row.compaction,
      row.region,
      row.items,
      row.sectionBytes,
      row.reads,
      row.distinct,
      row.answered,
      row.staleRead,
      row.missedDistinct,
    ].join('\t'),
  )
}
const reads = total('reads')
console.log(
  `\nTOTAL reads=${reads} answered=${total('answered')} ` +
    `(${reads === 0 ? 0 : Math.round((total('answered') / reads) * 100)}%) ` +
    `stale=${total('staleRead')} compactions=${rows.length}`,
)
