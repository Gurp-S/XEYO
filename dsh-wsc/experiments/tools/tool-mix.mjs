#!/usr/bin/env node
/**
 * Tool-call mix for one or more runs, read from their session logs.
 *
 * The question this answers: when an arm takes five times as many steps for the
 * same task, is the extra work new work or the same work repeated? Repeats show
 * up as a high calls-per-distinct-target ratio for read/edit style tools.
 *
 * Usage: node tools/tool-mix.mjs <runName...>
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { readSessionEvents } from './read-session.mjs'

const repo = join(import.meta.dirname, '..')

/** The log sits either directly in the run directory or in a session-id subdirectory. */
function findLog(dir, depth = 0) {
  if (depth > 3) return null
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (entry.endsWith('.zstd')) return full
    if (statSync(full).isDirectory()) {
      const found = findLog(full, depth + 1)
      if (found !== null) return found
    }
  }
  return null
}
const names = process.argv.slice(2)
if (names.length === 0) {
  process.stderr.write('usage: node tool-mix.mjs <runName...>\n')
  process.exit(2)
}

/** Pull the tool name and a target key out of one `tool/call` event. */
function describe(event) {
  const data = event.data ?? event.call ?? event
  const name = data.name ?? data.toolName ?? 'unknown'
  let args = data.arguments ?? data.args ?? {}
  // Some builds carry the arguments as a JSON string rather than an object.
  if (typeof args === 'string') {
    try {
      args = JSON.parse(args)
    } catch {
      args = {}
    }
  }
  const target = args.path ?? args.file_path ?? args.filePath ?? args.pattern ?? args.command ?? ''
  return { name, target: typeof target === 'string' ? target : '' }
}

for (const name of names) {
  const run = JSON.parse(readFileSync(join(repo, 'report', 'raw', `${name}.json`), 'utf8'))
  const dir = join(homedir(), '.dsh', 'sessions', run.session)
  const file = findLog(dir)
  if (file === null) {
    console.log(`${name}: no session log`)
    continue
  }
  const events = readSessionEvents(file)
  const calls = events.filter((event) => event.type === 'tool/call').map(describe)
  const steps = events.filter((event) => event.type === 'step/start').length
  const byName = new Map()
  for (const call of calls) byName.set(call.name, (byName.get(call.name) ?? 0) + 1)
  const top = [...byName.entries()].sort((left, right) => right[1] - left[1])

  // Reads and edits repeat when the model has lost the content it read before.
  const reread = calls.filter((call) => call.name === 'read')
  const distinct = new Set(reread.map((call) => call.target)).size

  console.log(
    `${name}: steps=${steps} calls=${calls.length} perStep=${(calls.length / Math.max(1, steps)).toFixed(2)} ` +
      `read=${reread.length} distinctReadPaths=${distinct} rereadFactor=${(reread.length / Math.max(1, distinct)).toFixed(2)}`,
  )
  console.log(`  ${top.map(([tool, count]) => `${tool}:${count}`).join(' ')}`)
}
