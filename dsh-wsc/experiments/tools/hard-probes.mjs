// Summarise the hard-fixture runs: the twelve constraints, the six work
// checks, the provenance probe (did the run write under tests/), and the
// session shape (steps, compactions, reads).
//
// Usage: node experiments/tools/hard-probes.mjs

import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { readSessionEvents } from './read-session.mjs'

const EXP = path.resolve('D:/lea/XenYon code/dsh-wsc/experiments')
const RAW = path.join(EXP, 'report', 'raw')
const SESSIONS = 'C:/Users/48522/.dsh/sessions'

const walk = (dir) => readdirSync(dir).flatMap((name) => {
  const full = path.join(dir, name)
  return statSync(full).isDirectory() ? walk(full) : [full]
})

const rows = []
for (const file of readdirSync(RAW).filter((name) => /^hard-.*\.score\.json$/.test(name))) {
  const name = file.replace('.score.json', '')
  const report = JSON.parse(readFileSync(path.join(RAW, file), 'utf8'))
  const byName = new Map(report.tests.map((entry) => [entry.name.split(' ')[0], entry.ok]))
  const constraints = [...byName.entries()].filter(([key]) => key.startsWith('C')).map(([, ok]) => (ok ? 1 : 0))
  const work = [...byName.entries()].filter(([key]) => key.startsWith('W')).map(([, ok]) => (ok ? 1 : 0))

  let steps = 0
  let compactions = 0
  let reads = 0
  let writes = 0
  let testWrites = 0
  const sessionName = `--D-lea-XenYon~0020code-dsh-wsc-experiments-runs-${name}--`
  const sessionDir = path.join(SESSIONS, sessionName)
  try {
    const sessionFile = walk(sessionDir).find((entry) => entry.endsWith('.jsonl.zstd'))
    if (sessionFile) {
      const events = readSessionEvents(sessionFile)
      steps = events.filter((event) => event.type === 'step/end').length
      compactions = events.filter((event) => event.type === 'compaction/summary').length
      for (const event of events) {
        if (event.type !== 'tool/call') continue
        let args
        try { args = JSON.parse(event.data.arguments ?? '{}') } catch { continue }
        const target = String(args.file_path ?? '')
        if (event.data.name === 'read') reads += 1
        if (event.data.name === 'write' || event.data.name === 'edit') {
          writes += 1
          if (/[\\/]tests[\\/]/.test(target)) testWrites += 1
        }
      }
    }
  } catch { /* session missing */ }

  rows.push({
    name,
    score: report.score,
    constraints: `${constraints.reduce((sum, value) => sum + value, 0)}/${constraints.length}`,
    work: `${work.reduce((sum, value) => sum + value, 0)}/${work.length}`,
    drift: byName.get('C2') ? 'no' : 'YES',
    steps,
    compactions,
    reads,
    writes,
    testWrites,
  })
}

rows.sort((left, right) => left.name.localeCompare(right.name))
console.log('run'.padEnd(16), 'score', 'C'.padEnd(6), 'W'.padEnd(5), 'drift', 'steps', 'cmp', 'reads', 'writes', 'tests/')
for (const row of rows) {
  console.log(
    row.name.padEnd(16),
    String(row.score).padEnd(5),
    row.constraints.padEnd(6),
    row.work.padEnd(5),
    row.drift.padEnd(5),
    String(row.steps).padStart(5),
    String(row.compactions).padStart(3),
    String(row.reads).padStart(5),
    String(row.writes).padStart(6),
    String(row.testWrites).padStart(6),
  )
}
