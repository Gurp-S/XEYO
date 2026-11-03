// Aggregate the echo A/C matrix: one row per run, then arm medians.
//
//   node tools/echo-arms.mjs
//
// Reads experiments/report/raw/echo-*.json plus the session log of each run, so
// the echo share comes from the checkpoints the agent actually received.

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readSessionEvents } from './read-session.mjs'

const exp = fileURLToPath(new URL('..', import.meta.url))
const raw = join(exp, 'report', 'raw')
const home = join(homedir(), '.dsh')

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

const median = (values) => {
  const sorted = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b)
  if (sorted.length === 0) return null
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}
const round = (value) => (value === null ? null : Math.round(value * 10) / 10)

/** Echo share of one checkpoint: lines that only re-carry an earlier checkpoint. */
const echoOf = (text) => {
  const lines = text.split('\n').filter((line) => line.includes('## Prior checkpoint'))
  const chars = lines.reduce((total, line) => total + line.length + 1, 0)
  return { lines: lines.length, chars, share: text.length === 0 ? 0 : chars / text.length }
}

const runs = readdirSync(raw)
  .filter((file) => /^echo-[ac]-\d+\.json$/.test(file))
  .map((file) => file.replace(/\.json$/, ''))
  .sort()

const rows = []
for (const name of runs) {
  const record = JSON.parse(readFileSync(join(raw, `${name}.json`), 'utf8'))
  const file = record.session === null ? null : findSessionFile(join(home, 'sessions', record.session))
  let echoShare = null
  let echoLines = null
  let checkpoints = null
  let checkpointChars = null
  let lastShare = null
  if (file !== null) {
    const events = readSessionEvents(file)
    const summaries = events
      .filter((event) => event.type === 'compaction/summary')
      .map((event) => (event.data.summary ?? []).map((block) => block.text ?? '').join('\n'))
    if (summaries.length > 0) {
      const echoes = summaries.map(echoOf)
      checkpoints = summaries.length
      checkpointChars = round(median(summaries.map((text) => text.length)))
      echoShare = round((echoes.reduce((total, echo) => total + echo.share, 0) / echoes.length) * 100)
      echoLines = round(median(echoes.map((echo) => echo.lines)))
      lastShare = round(echoes[echoes.length - 1].share * 100)
    }
  }
  rows.push({
    name,
    arm: name.split('-')[1],
    score: record.score,
    steps: Array.isArray(record.steps) ? record.steps.length : record.steps,
    requests: record.requests,
    input: record.inputTokens,
    output: record.outputTokens,
    seconds: record.seconds,
    checkpoints,
    checkpointChars,
    echoShare,
    echoLines,
    lastShare,
  })
}

const columns = [
  ['name', 'run'],
  ['score', 'score'],
  ['steps', 'steps'],
  ['requests', 'req'],
  ['input', 'in tok'],
  ['output', 'out tok'],
  ['seconds', 'wall s'],
  ['checkpoints', 'ckpt'],
  ['checkpointChars', 'ckpt chars'],
  ['echoShare', 'echo %'],
  ['echoLines', 'echo lines'],
  ['lastShare', 'last echo %'],
]
const cell = (value) => (value === null || value === undefined ? '—' : String(value))
console.log(`| ${columns.map(([, label]) => label).join(' | ')} |`)
console.log(`| ${columns.map(() => '---').join(' | ')} |`)
for (const row of rows) console.log(`| ${columns.map(([key]) => cell(row[key])).join(' | ')} |`)

console.log('\narm medians')
for (const arm of ['a', 'c']) {
  const group = rows.filter((row) => row.arm === arm)
  if (group.length === 0) continue
  const pick = (key) => round(median(group.map((row) => row[key])))
  console.log(
    `- ${arm} (n=${group.length}): score ${group.map((row) => row.score).join('/')} · ` +
      `steps ${pick('steps')} · req ${pick('requests')} · in ${pick('input')} · ` +
      `wall ${pick('seconds')}s · ckpt ${pick('checkpoints')} · chars ${pick('checkpointChars')} · ` +
      `echo ${pick('echoShare')}% · last ${pick('lastShare')}%`,
  )
}
