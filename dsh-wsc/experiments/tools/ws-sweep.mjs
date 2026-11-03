// Offline parameter sweep for the working-set builder.
//
// Replays recorded sessions through the real buildWorkingSet() and asks: with a
// bigger working set, how many of the post-compaction re-reads would it cover?
// No API calls — this is the builder as a pure function over recorded messages.
//
// Usage: node experiments/tools/ws-sweep.mjs

import { readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { readSessionEvents } from './read-session.mjs'
import { buildWorkingSet } from '../../lib/workingset.js'

const ROOT = 'C:/Users/48522/.dsh/sessions'
const PREFIXES = process.argv.slice(2).length > 0 ? process.argv.slice(2) : ['runs-echo-k2']
const GRID = [
  { maxFiles: 6, capChars: 700 },
  { maxFiles: 12, capChars: 700 },
  { maxFiles: 24, capChars: 700 },
  { maxFiles: 12, capChars: 1400 },
  { maxFiles: 24, capChars: 1400 },
]
const cellKey = (cell) => `${cell.maxFiles}/${cell.capChars}`

const walk = (dir) => readdirSync(dir).flatMap((name) => {
  const full = path.join(dir, name)
  return statSync(full).isDirectory() ? walk(full) : [full]
})
const norm = (value) => String(value).replace(/\\/g, '/').toLowerCase()
const same = (a, b) => a === b || a.endsWith('/' + b.split('/').slice(-2).join('/')) || b.endsWith('/' + a.split('/').slice(-2).join('/'))

const sessions = []
for (const name of readdirSync(ROOT)) {
  if (!PREFIXES.some((prefix) => name.includes(prefix))) continue
  const file = walk(path.join(ROOT, name)).find((candidate) => candidate.includes('session.jsonl'))
  if (file) sessions.push({ name: name.replace(/^--D-lea-XenYon~0020code-dsh-wsc-experiments-runs-/, '').replace(/--$/, ''), file })
}

const totals = new Map(GRID.map((cell) => [cellKey(cell), { redundant: 0, covered: 0, listed: 0 }]))

for (const session of sessions) {
  const events = readSessionEvents(session.file)
  const messages = []
  const compactions = []
  const reads = []
  const seen = new Set()

  for (const event of events) {
    if (event.type === 'compaction/summary') {
      compactions.push({ messageIndex: messages.length, snapshot: new Set(seen) })
      continue
    }
    const message = event.data?.message
    if (!message) continue
    if (event.type === 'assistant/message') {
      for (const block of message.content ?? []) {
        if (block?.type !== 'tool-call' || block.name !== 'read') continue
        let args
        try { args = JSON.parse(block.arguments ?? '{}') } catch { continue }
        if (typeof args.file_path !== 'string') continue
        const target = norm(args.file_path)
        reads.push({ messageIndex: messages.length, path: target, window: compactions.length - 1 })
        seen.add(target)
      }
      messages.push(message)
    } else if (event.type === 'tool/result' || event.type === 'user/message') {
      messages.push(message)
    }
  }

  const cache = new Map()
  const wsFor = (window, cell) => {
    const key = `${window}|${cellKey(cell)}`
    let set = cache.get(key)
    if (set) return set
    const upto = messages.slice(0, compactions[window].messageIndex)
    set = new Set(buildWorkingSet(upto, { maxFiles: cell.maxFiles, capChars: cell.capChars }).map((line) => norm(line.split(' — ')[0])))
    cache.set(key, set)
    return set
  }

  for (const read of reads) {
    if (read.window < 0) continue
    const before = compactions[read.window].snapshot
    if (![...before].some((item) => same(item, read.path))) continue
    for (const cell of GRID) {
      const stats = totals.get(cellKey(cell))
      const set = wsFor(read.window, cell)
      stats.redundant += 1
      stats.listed += set.size
      if ([...set].some((item) => same(item, read.path))) stats.covered += 1
    }
  }
}

console.log('maxFiles/capChars  redundant  covered  cover%  avg listed')
for (const [key, stats] of totals) {
  const pct = stats.redundant === 0 ? 0 : Math.round((stats.covered / stats.redundant) * 100)
  console.log(key.padEnd(18), String(stats.redundant).padStart(9), String(stats.covered).padStart(8), String(pct).padStart(7) + '%', String(stats.redundant === 0 ? 0 : (stats.listed / stats.redundant).toFixed(1)).padStart(11))
}

