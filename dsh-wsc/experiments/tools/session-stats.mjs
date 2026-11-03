/**
 * Session statistics for one experiment run.
 *
 * dsh appends one zstd frame per event, and Node's zstdDecompressSync only
 * decodes the first frame, so the file is split on the zstd magic number and
 * each frame is decoded on its own.
 *
 * Usage: node session-stats.mjs echo-g-1 [echo-a-1 ...]
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import zlib from 'node:zlib'

const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])

function frames(buffer) {
  const starts = []
  for (let i = 0; i + 4 <= buffer.length; i += 1) {
    if (buffer.compare(MAGIC, 0, 4, i, i + 4) === 0) starts.push(i)
  }
  const out = []
  for (let k = 0; k < starts.length; k += 1) {
    const end = k + 1 < starts.length ? starts[k + 1] : buffer.length
    try {
      out.push(zlib.zstdDecompressSync(buffer.subarray(starts[k], end)).toString('utf8'))
    } catch {
      // A truncated trailing frame is expected when a run was killed.
    }
  }
  return out
}

function sessionFile(name) {
  const base = path.join(os.homedir(), '.dsh', 'sessions')
  const dir = fs.readdirSync(base).find((d) => d.includes(`runs-${name}--`))
  if (!dir) return null
  const full = path.join(base, dir)
  const walk = (p) => {
    for (const entry of fs.readdirSync(p, { withFileTypes: true })) {
      const q = path.join(p, entry.name)
      if (entry.isDirectory()) {
        const hit = walk(q)
        if (hit) return hit
      } else if (entry.name.endsWith('.zstd')) return q
    }
    return null
  }
  return walk(full)
}

function stats(name) {
  const file = sessionFile(name)
  if (!file) return { name, missing: true }
  const events = frames(fs.readFileSync(file))
    .join('')
    .split(/\r?\n/)
    .filter((l) => l.trim())
    .map((l) => {
      try {
        return JSON.parse(l)
      } catch {
        return null
      }
    })
    .filter(Boolean)

  const types = {}
  const tools = {}
  let usage = { input: 0, output: 0, requests: 0 }
  let compactions = 0
  for (const e of events) {
    types[e.type] = (types[e.type] || 0) + 1
    const name2 = e.type === 'tool_call' ? e.name ?? e.tool : undefined
    if (name2) tools[name2] = (tools[name2] || 0) + 1
    if (e.type === 'usage' || e.usage) {
      const u = e.usage ?? e
      usage.input += u.input ?? u.inputTokens ?? 0
      usage.output += u.output ?? u.outputTokens ?? 0
      usage.requests += 1
    }
    if (/compact/i.test(e.type ?? '')) compactions += 1
  }
  return { name, events: events.length, types, tools, usage, compactions }
}

for (const name of process.argv.slice(2)) {
  const s = stats(name)
  if (s.missing) {
    console.log(name, 'no session')
    continue
  }
  const steps = s.types['step/start'] ?? 0
  const toolCalls = s.types['tool/call'] ?? 0
  const compactions = s.types['compaction/start'] ?? 0
  console.log(
    name.padEnd(10),
    'steps=' + String(steps).padStart(4),
    'tools=' + String(toolCalls).padStart(4),
    'compactions=' + String(compactions).padStart(3),
  )
  console.log(
    '  types:',
    Object.entries(s.types)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${k}=${v}`)
      .join(' '),
  )
  console.log('  tools:', JSON.stringify(s.tools))
}
