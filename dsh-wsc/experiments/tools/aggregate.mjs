// Summarise experiments/report/raw/*.json into a markdown table.
//
//   node tools/aggregate.mjs
//
// One JSON record per trial, written by tools/trial.ps1.
import { readdirSync, readFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const raw = join(here, '..', 'report', 'raw')

const median = (values) => {
  if (values.length === 0) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid]
}

const records = []
for (const name of readdirSync(raw)) {
  if (!name.endsWith('.json') || name.endsWith('.types.json') || name.endsWith('.score.json')) continue
  const record = JSON.parse(readFileSync(join(raw, name), 'utf8'))
  const typesFile = join(raw, `${record.name}.types.json`)
  record.compactions = 0
  if (existsSync(typesFile)) {
    const types = JSON.parse(readFileSync(typesFile, 'utf8')).types ?? {}
    record.compactions = types['compaction/start'] ?? 0
  }
  record.group = record.name.startsWith('pilot') ? 'pilot' : record.name[0]
  records.push(record)
}

records.sort((a, b) => a.name.localeCompare(b.name))

const header = '| run | score | steps | requests | input | output | compactions | wall s | failed |'
const rule = '| --- | --- | --- | --- | --- | --- | --- | --- | --- |'
console.log(header)
console.log(rule)
for (const record of records) {
  console.log(`| ${record.name} | ${record.score} | ${Array.isArray(record.steps) ? record.steps.length : '?'} | ${record.requests} | ${record.inputTokens} | ${record.outputTokens} | ${record.compactions} | ${record.seconds} | ${(record.failed ?? []).length} |`)
}

const groups = { a: [], b: [], pilot: [] }
for (const record of records) groups[record.group]?.push(record)
for (const [group, rows] of Object.entries(groups)) {
  if (rows.length === 0) continue
  const pick = (key) => median(rows.map((row) => row[key]).filter((value) => typeof value === 'number'))
  console.log(
    `\n${group}: n=${rows.length} score=${pick('score')} steps=${pick('steps')} requests=${pick('requests')}` +
    ` input=${pick('inputTokens')} output=${pick('outputTokens')} compactions=${pick('compactions')} wall=${pick('seconds')}s`,
  )
}
