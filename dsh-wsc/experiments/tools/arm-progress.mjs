#!/usr/bin/env node
/**
 * Progress and compaction counts for one arm, read from the probe event log.
 *
 * The probe appends to a single `~/.dsh/probe/events.jsonl` across runs, so a
 * count over the whole file mixes arms. Passing the run's start time scopes the
 * count to that run.
 *
 * Usage: node tools/arm-progress.mjs <ISO-start-time>
 */
import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

const start = Date.parse(process.argv[2] ?? '')
if (Number.isNaN(start)) {
  process.stderr.write('usage: node arm-progress.mjs <ISO-start-time>\n')
  process.exit(2)
}

const file = join(homedir(), '.dsh', 'probe', 'events.jsonl')
const rows = readFileSync(file, 'utf8')
  .split('\n')
  .filter(Boolean)
  .map((line) => {
    try {
      return JSON.parse(line)
    } catch {
      return null
    }
  })
  .filter((row) => row !== null && typeof row.at === 'number' && row.at >= start)

const count = (predicate) => rows.filter(predicate).length
const steps = rows.filter((row) => row.kind === 'agent/pre-step')
const admitted = rows.filter((row) => typeof row.message === 'string' && row.message.startsWith('wsc compaction ('))
const skipped = count((row) => typeof row.message === 'string' && row.message.startsWith('wsc compaction skipped'))
const reclaims = admitted
  .map((row) => /reclaim ~(\d+)/.exec(row.message)?.[1])
  .filter((value) => value !== undefined)
  .map(Number)
const sum = reclaims.reduce((total, value) => total + value, 0)

process.stdout.write(
  [
    `events: ${rows.length}`,
    `steps: ${steps.length} (max step ${Math.max(0, ...steps.map((row) => row.step ?? 0))})`,
    `compactions admitted: ${admitted.length}`,
    `compactions skipped: ${skipped}`,
    `reclaim total: ${sum} tokens, mean ${reclaims.length === 0 ? 0 : Math.round(sum / reclaims.length)}`,
    `max tokens seen: ${Math.max(0, ...steps.map((row) => row.tokens ?? 0))}`,
  ].join('\n') + '\n',
)
