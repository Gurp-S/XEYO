// Where does the wall clock go? For one recorded session, split total time into
// time spent inside compaction (compaction/start -> compaction/end) and the rest,
// and add up the tokens each side spends.
//
// Usage: node experiments/tools/why-slow.mjs <run-name>...

import { readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { readSessionEvents } from './read-session.mjs'

const SESSIONS = 'C:/Users/48522/.dsh/sessions'
const walk = (dir) => readdirSync(dir).flatMap((name) => {
  const full = path.join(dir, name)
  return statSync(full).isDirectory() ? walk(full) : [full]
})

const names = process.argv.slice(2)
console.log('run'.padEnd(16), 'wall', '  cmp', 'cmpTime', 'cmpOut', 'stepOut', 'req', 'steps')

for (const run of names) {
  const dir = readdirSync(SESSIONS).find((entry) => entry.includes(`runs-${run}--`))
  if (!dir) { console.log(run, 'no session'); continue }
  const file = walk(path.join(SESSIONS, dir)).find((entry) => entry.endsWith('.jsonl.zstd'))
  const events = readSessionEvents(file)

  const time = (event) => new Date(event.createdAt).getTime()
  const start = time(events[0])
  const end = time(events.at(-1))
  const wall = Math.round((end - start) / 1000)

  // Pair each compaction/start with the next compaction/end.
  let open = null
  let compactionMs = 0
  let compactionOut = 0
  let compactions = 0
  for (const event of events) {
    if (event.type === 'compaction/start') open = time(event)
    if (event.type === 'compaction/end' && open !== null) {
      compactionMs += time(event) - open
      open = null
    }
    if (event.type === 'compaction/summary') {
      compactions += 1
      compactionOut += event.data.usage?.outputTokens ?? 0
    }
  }

  let stepOut = 0
  for (const event of events) {
    if (event.type === 'assistant/message') stepOut += event.data.usage?.outputTokens ?? 0
  }

  const requests = events.filter((event) => event.type === 'assistant/message').length
  const steps = events.filter((event) => event.type === 'step/end').length

  console.log(
    run.padEnd(16),
    `${String(wall).padStart(4)}s`,
    String(compactions).padStart(4),
    `${String(Math.round(compactionMs / 1000)).padStart(6)}s`,
    String(compactionOut).padStart(6),
    String(stepOut).padStart(7),
    String(requests).padStart(4),
    String(steps).padStart(5),
  )
}
