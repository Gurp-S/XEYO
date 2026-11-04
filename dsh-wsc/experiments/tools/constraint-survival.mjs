// How many of the twelve operating constraints survive each checkpoint?
//
// Reads the recorded compaction summaries of the hard-fixture runs and looks
// for a marker of every constraint. This is the "constraint survival" measure
// from 2610.31778 (Benchmarks Are Surprisingly Compaction-Friendly), which
// reports that the first summary already drops about a third of a task's rules.
//
// Usage: node experiments/tools/constraint-survival.mjs

import { readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { readSessionEvents } from './read-session.mjs'

const SESSIONS = 'C:/Users/48522/.dsh/sessions'
const PREFIXES = process.argv.slice(2).length > 0 ? process.argv.slice(2) : ['runs-hard-']

const MARKERS = [
  ['C1 deps', /no runtime dependenc|zero-dependenc|dependencies/i],
  ['C2 tests', /tests\/? (is )?read-only|read-only|do not modify.*tests|tests.*untouched/i],
  ['C3 exports', /parseCsv.*createLedger|createLedger.*parseCsv|exports/i],
  ['C4 keys', /version.*total.*categories.*count|four top-level keys/i],
  ['C5 cents', /integer (number of )?cents|cents/i],
  ['C6 sorted', /sorted|alphabetical/i],
  ['C7 dry-run', /dry-run|dry run/i],
  ['C8 exit 2', /exit (code )?2|usage/i],
  ['C9 cjs', /commonjs|require\(|module\.exports/i],
  ['C10 log', /console\.log|never log|no logging/i],
  ['C11 readme', /readme/i],
  ['C12 version', /package\.json.*version|version.*package\.json/i],
]

const walk = (dir) => readdirSync(dir).flatMap((name) => {
  const full = path.join(dir, name)
  return statSync(full).isDirectory() ? walk(full) : [full]
})

const rows = []
for (const name of readdirSync(SESSIONS)) {
  if (!PREFIXES.some((prefix) => name.includes(prefix))) continue
  const file = walk(path.join(SESSIONS, name)).find((entry) => entry.endsWith('.jsonl.zstd'))
  if (!file) continue
  const events = readSessionEvents(file)
  const summaries = events.filter((event) => event.type === 'compaction/summary')
  if (summaries.length === 0) continue
  const counts = summaries.map((event) => {
    const text = (event.data.summary ?? []).map((part) => part.text ?? '').join('\n')
    return MARKERS.filter(([, pattern]) => pattern.test(text)).length
  })
  rows.push({
    name: name.replace(/^--D-lea-XenYon~0020code-dsh-wsc-experiments-runs-/, '').replace(/--$/, ''),
    checkpoints: summaries.length,
    first: counts[0],
    last: counts.at(-1),
    min: Math.min(...counts),
    mean: (counts.reduce((sum, value) => sum + value, 0) / counts.length).toFixed(1),
  })
}

rows.sort((left, right) => left.name.localeCompare(right.name))
console.log('run'.padEnd(16), 'checkpoints', 'first', 'last', 'min', 'mean', '  (of 12)')
for (const row of rows) {
  console.log(row.name.padEnd(16), String(row.checkpoints).padStart(11), String(row.first).padStart(5), String(row.last).padStart(4), String(row.min).padStart(3), String(row.mean).padStart(4))
}
