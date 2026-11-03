// Compare two payload-A/B trials: shipped tool-output quoting (A) vs wider (B).
//
//   node tools/pay-ab.mjs pay-a-1 pay-b-1
//
// Reads the trial record written by tools/trial.ps1, the session log, and the
// WSC ledger (`$DSH_HOME/wsc/compactions.jsonl`), filtered to the run window.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readSessionEvents } from './read-session.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const exp = join(here, '..')
const home = process.env.DSH_HOME ?? join(homedir(), '.dsh')

const median = (values) => {
  if (values.length === 0) return null
  const sorted = [...values].sort((left, right) => left - right)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid]
}
const mean = (values) => (values.length === 0 ? null : Math.round(values.reduce((a, b) => a + b, 0) / values.length))
const round = (value) => (value === null ? '—' : Math.round(value * 1000) / 1000)

/** The session log lives one level down, inside a `session-<id>` directory. */
const findSessionFile = (dir) => {
  if (!existsSync(dir)) return null
  const direct = join(dir, 'session.jsonl.zstd')
  if (existsSync(direct)) return direct
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (!statSync(path).isDirectory()) continue
    const found = join(path, 'session.jsonl.zstd')
    if (existsSync(found)) return found
  }
  return null
}

/** Signature of a tool call, used to spot repeats. */
const signature = (event) => {
  const name = event.data?.name ?? event.data?.call?.name ?? '?'
  const args = event.data?.arguments ?? event.data?.call?.arguments ?? {}
  const text = typeof args === 'string' ? args : JSON.stringify(args)
  return `${name}|${text}`
}

const loadRun = (name) => {
  const record = JSON.parse(readFileSync(join(exp, 'report', 'raw', `${name}.json`), 'utf8'))
  const started = new Date(record.started)
  const ended = new Date(started.getTime() + record.seconds * 1000)

  const sessionDir = record.session === null ? null : join(home, 'sessions', record.session)
  const file = sessionDir === null ? null : findSessionFile(sessionDir)
  const events = file !== null && existsSync(file) ? readSessionEvents(file) : []

  const ledgerFile = join(home, 'wsc', 'compactions.jsonl')
  const ledger = existsSync(ledgerFile)
    ? readFileSync(ledgerFile, 'utf8')
        .split('\n')
        .filter((line) => line.length > 0)
        .map((line) => JSON.parse(line))
        .filter((row) => {
          const at = new Date(row.at)
          return at >= started && at <= ended
        })
    : []

  const calls = events.filter((event) => event.type === 'tool/call')
  const firstCompactionSeq = events.find((event) => event.type === 'compaction/start')?.seq ?? null
  const seen = new Map()
  let repeats = 0
  let repeatsAfterCompaction = 0
  let callsAfterCompaction = 0
  calls.forEach((event) => {
    const afterCompaction = firstCompactionSeq !== null && event.seq > firstCompactionSeq
    if (afterCompaction) callsAfterCompaction += 1
    const key = signature(event)
    if (seen.has(key)) {
      repeats += 1
      if (afterCompaction) repeatsAfterCompaction += 1
    } else {
      seen.set(key, event.seq)
    }
  })

  const payloads = ledger.map((row) => row.payload).filter((payload) => payload !== null && payload !== undefined)
  return {
    name,
    profile: record.profile,
    score: record.score,
    passed: record.passed,
    total: record.total,
    failed: record.failed,
    steps: Array.isArray(record.steps) ? record.steps.length : record.steps,
    requests: record.requests,
    inputTokens: record.inputTokens,
    outputTokens: record.outputTokens,
    seconds: record.seconds,
    compactions: events.filter((event) => event.type === 'compaction/start').length,
    ledgerRows: ledger.length,
    ledgerKinds: ledger.reduce((counts, row) => ({ ...counts, [row.kind]: (counts[row.kind] ?? 0) + 1 }), {}),
    selective: ledger.filter((row) => row.selection !== null && row.selection !== undefined).length,
    checkpointBytes: payloads.map((payload) => payload.chars),
    checkpointBudget: payloads.map((payload) => payload.budget),
    sourceBytes: payloads.map((payload) => payload.sourceBytes),
    sections: payloads.map((payload) => payload.sections ?? null),
    echoDepth: payloads.map((payload) => payload.priorDepth ?? null),
    truncated: payloads.filter((payload) => payload.truncated === true).length,
    calls: calls.length,
    distinctCalls: seen.size,
    repeats,
    callsAfterCompaction,
    repeatsAfterCompaction,
  }
}

const names = process.argv.slice(2)
if (names.length !== 2) {
  console.error('usage: node tools/pay-ab.mjs <runA> <runB>')
  process.exit(1)
}
const [a, b] = names.map(loadRun)

const row = (label, left, right) => `| ${label} | ${left} | ${right} |`
const lines = [
  `| metric | ${a.name} (${a.profile}) | ${b.name} (${b.profile}) |`,
  '| --- | --- | --- |',
  row('score', `${a.passed}/${a.total}`, `${b.passed}/${b.total}`),
  row('failed', a.failed.join(', ') || '—', b.failed.join(', ') || '—'),
  row('steps', a.steps, b.steps),
  row('requests', a.requests, b.requests),
  row('input tokens', a.inputTokens, b.inputTokens),
  row('output tokens', a.outputTokens, b.outputTokens),
  row('wall s', a.seconds, b.seconds),
  row('compactions (session)', a.compactions, b.compactions),
  row('ledger rows', `${a.ledgerRows} ${JSON.stringify(a.ledgerKinds)}`, `${b.ledgerRows} ${JSON.stringify(b.ledgerKinds)}`),
  row('rows with selection telemetry', a.selective, b.selective),
  row('checkpoint bytes', `${a.checkpointBytes.join(' / ') || '—'}`, `${b.checkpointBytes.join(' / ') || '—'}`),
  row('checkpoint mean bytes', mean(a.checkpointBytes), mean(b.checkpointBytes)),
  row('budget', a.checkpointBudget.join(' / ') || '—', b.checkpointBudget.join(' / ') || '—'),
  row('checkpoint median chars', median(a.checkpointBytes) ?? '—', median(b.checkpointBytes) ?? '—'),
  row('checkpoints truncated at budget', a.truncated, b.truncated),
  row('echo depth', a.echoDepth.join(' / ') || '—', b.echoDepth.join(' / ') || '—'),
  row('tool calls', a.calls, b.calls),
  row('distinct tool calls', a.distinctCalls, b.distinctCalls),
  row('repeated calls', a.repeats, b.repeats),
  row('calls after first compaction', a.callsAfterCompaction, b.callsAfterCompaction),
  row('repeated calls after compaction', a.repeatsAfterCompaction, b.repeatsAfterCompaction),
]
console.log(lines.join('\n'))
for (const run of [a, b]) {
  const sections = run.sections.filter((section) => section !== null)
  if (sections.length === 0) continue
  console.log(`\n${run.name} sections (bytes):`)
  for (const section of sections) console.log(`  ${JSON.stringify(section)}`)
}
console.log(`\nmedian checkpoint bytes: ${round(median(a.checkpointBytes))} vs ${round(median(b.checkpointBytes))}`)
