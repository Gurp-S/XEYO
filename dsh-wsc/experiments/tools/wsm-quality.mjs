// Does the working set prevent redundant re-reads after a compaction?
//
// For every checkpoint: a read that targets a file already read earlier in the
// session is redundant work — the model is re-learning state it once had. The
// working set is supposed to carry that state. This script counts those
// redundant reads and how many of them the listed working set covered.
//
// Usage: node experiments/tools/wsm-quality.mjs [session-prefix...]

import { readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { readSessionEvents } from './read-session.mjs'

const ROOT = 'C:/Users/48522/.dsh/sessions'
const PREFIXES = process.argv.slice(2)

const walk = (dir) => readdirSync(dir).flatMap((name) => {
  const full = path.join(dir, name)
  return statSync(full).isDirectory() ? walk(full) : [full]
})

const norm = (value) => String(value).replace(/\\/g, '/').replace(/^file:\/\//, '').toLowerCase()

function workingSetPaths(text) {
  const lines = String(text).split('\n')
  const start = lines.findIndex((line) => /^## Working set/.test(line))
  if (start < 0) return new Set()
  const found = new Set()
  for (const line of lines.slice(start + 1)) {
    if (/^## /.test(line)) break
    const match = /^\s*-\s+(.+?)\s+—/.exec(line) ?? /^\s*-\s+(\S+)/.exec(line)
    if (match) found.add(norm(match[1]))
  }
  return found
}

const same = (a, b) => a === b || a.endsWith('/' + b.split('/').slice(-2).join('/')) || b.endsWith('/' + a.split('/').slice(-2).join('/'))

const sessions = []
for (const name of readdirSync(ROOT)) {
  if (!PREFIXES.some((prefix) => name.includes(prefix))) continue
  const file = walk(path.join(ROOT, name)).find((candidate) => candidate.includes('session.jsonl'))
  if (file) sessions.push({ name, file })
}

const rows = []
for (const session of sessions) {
  const events = readSessionEvents(session.file)
  const seen = new Set()
  let ws = new Set()
  let compactions = 0
  let reads = 0
  let redundant = 0
  let covered = 0
  for (const event of events) {
    if (event.type === 'compaction/summary') {
      const text = (event.data.summary ?? []).map((part) => part.text ?? '').join('\n')
      ws = workingSetPaths(text)
      compactions += 1
      continue
    }
    if (event.type !== 'tool/call' || event.data.name !== 'read') continue
    let args
    try { args = JSON.parse(event.data.arguments ?? '{}') } catch { continue }
    if (typeof args.file_path !== 'string') continue
    const target = norm(args.file_path)
    reads += 1
    if (seen.has(target)) {
      redundant += 1
      if ([...ws].some((item) => same(item, target))) covered += 1
    }
    seen.add(target)
  }
  rows.push({ name: session.name.replace(/^--D-lea-XenYon~0020code-dsh-wsc-experiments-runs-/, '').replace(/--$/, ''), compactions, reads, redundant, covered, wsSize: ws.size })
}

console.log('session'.padEnd(14), 'cp', 'reads', 'rered', 'covered', 'red%')
let R = 0; let D = 0; let C = 0
for (const row of rows.sort((a, b) => a.name.localeCompare(b.name))) {
  console.log(row.name.padEnd(14), String(row.compactions).padStart(2), String(row.reads).padStart(5), String(row.redundant).padStart(5), String(row.covered).padStart(7), (row.reads === 0 ? '—' : `${Math.round((row.redundant / row.reads) * 100)}%`).padStart(4))
  R += row.reads; D += row.redundant; C += row.covered
}
console.log(`\nTOTAL reads=${R} redundant=${D} (${R === 0 ? 0 : Math.round((D / R) * 100)}%) covered=${C} (${D === 0 ? 0 : Math.round((C / D) * 100)}% of redundant)`)
