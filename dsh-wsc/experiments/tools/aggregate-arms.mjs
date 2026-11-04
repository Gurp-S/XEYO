// Aggregate every recorded trial into one representative table, grouped by arm.
//
// Reads experiments/report/raw/<name>.json (the per-run record written by
// trial.ps1) and groups by profile family: ab-native* is the shipped
// compaction-basic backend, ab-echo* is WSC.
//
// Usage: node experiments/tools/aggregate-arms.mjs

import { readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'

const RAW = path.resolve('D:/lea/XenYon code/dsh-wsc/experiments/report/raw')
const SKIP = /\.(score|types)\.json$|\.log$/
// Only current-configuration runs: k2 (the adopted WSC config) and its matched
// native baselines. Pre-fix arms (a,b,c,d,e,g,h,i,j,l) and the rejected L/gen2
// experiments are excluded on purpose - mixing them is apples to oranges.
const INCLUDE = [/^k2-\d+$/, /^gen-.+-(wsc|native)$/, /^hard-(wsc|native)-\d+$/, /^mega-(wsc|native)-\d+$/, /^hard-(v2|con)-(wsc|native)-1$/, /^native-\d+$/]

const median = (values) => {
  if (values.length === 0) return 0
  const sorted = [...values].sort((left, right) => left - right)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0 ? Math.round((sorted[middle - 1] + sorted[middle]) / 2) : sorted[middle]
}

const rows = []
for (const file of readdirSync(RAW)) {
  if (!file.endsWith('.json') || SKIP.test(file)) continue
  let record
  try { record = JSON.parse(readFileSync(path.join(RAW, file), 'utf8')) } catch { continue }
  if (typeof record.score !== 'number' || typeof record.profile !== 'string') continue
  const runName = record.name ?? file.replace('.json', '')
  if (!INCLUDE.some((pattern) => pattern.test(runName))) continue
  const family = record.profile.startsWith('ab-native') ? 'native' : record.profile.startsWith('ab-echo') ? 'wsc' : 'other'
  rows.push({
    name: record.name ?? file.replace('.json', ''),
    family,
    score: record.score,
    seconds: record.seconds ?? 0,
    requests: record.requests ?? 0,
    inputTokens: record.inputTokens ?? 0,
  })
}

const groups = new Map()
for (const row of rows) {
  const key = row.family
  if (!groups.has(key)) groups.set(key, [])
  groups.get(key).push(row)
}

console.log('arm     n   mean    min     max    median wall   median req   median input')
for (const [family, entries] of [...groups.entries()].sort()) {
  const scores = entries.map((entry) => entry.score)
  const mean = (scores.reduce((sum, value) => sum + value, 0) / scores.length).toFixed(3)
  console.log(
    family.padEnd(7),
    String(entries.length).padStart(3),
    String(mean).padStart(6),
    String(Math.min(...scores)).padStart(6),
    String(Math.max(...scores)).padStart(6),
    String(median(entries.map((entry) => entry.seconds))).padStart(12) + 's',
    String(median(entries.map((entry) => entry.requests))).padStart(12),
    String(median(entries.map((entry) => entry.inputTokens))).padStart(12),
  )
}

const perfect = rows.filter((row) => row.score >= 0.999).length
console.log(`\nruns=${rows.length} perfect=${perfect} (${Math.round((perfect / rows.length) * 100)}%)`)

// Per-task-shape breakdown, so a single hard task cannot hide behind the mean.
console.log('\nshape            native            wsc')
const shapes = new Map()
for (const row of rows) {
  const shape = row.name.replace(/-\d+$/, '').replace(/^(gen2|gen|hard|mega|echo|fast|pay|pilot)-/, '')
  if (!shapes.has(shape)) shapes.set(shape, { native: [], wsc: [] })
  shapes.get(shape)[row.family]?.push(row.score)
}
for (const [shape, bucket] of [...shapes.entries()].sort()) {
  const show = (list) => (list.length === 0 ? '—' : `${(list.reduce((sum, value) => sum + value, 0) / list.length).toFixed(2)} (n=${list.length})`)
  console.log(shape.padEnd(16), show(bucket.native).padEnd(17), show(bucket.wsc))
}

