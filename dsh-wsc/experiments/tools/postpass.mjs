// Add the labour metrics from the plan to every raw trial record: repeated
// reads of the same file, repeated identical commands, tool errors, and the
// estimated context peak.
//
//   node tools/postpass.mjs
//
// Reads experiments/report/raw/<name>.json and rewrites it with the extra
// fields; the session is located by the run directory it was launched from.
import { readdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { homedir } from 'node:os'
import { fileURLToPath } from 'node:url'
import { readSessionEvents } from './read-session.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const raw = join(here, '..', 'report', 'raw')
const sessions = join(homedir(), '.dsh', 'sessions')

const findSession = (name) => {
  if (!existsSync(sessions)) return null
  const dir = readdirSync(sessions).find((entry) => entry.includes(`runs-${name}--`))
  if (dir === undefined) return null
  const files = readdirSync(join(sessions, dir), { recursive: true })
    .filter((entry) => String(entry).endsWith('session.jsonl.zstd'))
  return files.length === 0 ? null : join(sessions, dir, files[0])
}

const argsOf = (data) => {
  const value = data.arguments ?? data.input ?? data.args
  if (typeof value === 'string') {
    try { return JSON.parse(value) } catch { return value }
  }
  return value ?? {}
}

for (const file of readdirSync(raw)) {
  if (!file.endsWith('.json') || file.endsWith('.types.json') || file.endsWith('.score.json')) continue
  const path = join(raw, file)
  const record = JSON.parse(readFileSync(path, 'utf8'))
  const session = findSession(record.name)
  if (session === null) {
    console.log(`${record.name}: no session`)
    continue
  }
  const events = readSessionEvents(session)
  const readCounts = new Map()
  const commandCounts = new Map()
  let reads = 0
  let commands = 0
  let toolErrors = 0
  for (const event of events) {
    const data = event.data ?? {}
    if (event.type === 'tool/call') {
      const args = argsOf(data)
      if (data.name === 'read') {
        reads += 1
        const key = args.path ?? args.file_path ?? JSON.stringify(args)
        readCounts.set(key, (readCounts.get(key) ?? 0) + 1)
      } else if (data.name === 'pwsh' || data.name === 'bash') {
        commands += 1
        const key = String(args.command ?? '').trim()
        commandCounts.set(key, (commandCounts.get(key) ?? 0) + 1)
      }
    } else if (event.type === 'tool/result') {
      const result = data.result ?? data.message?.content?.[0]?.output ?? ''
      if (data.isError === true || /^error:/i.test(String(result).trim())) toolErrors += 1
    }
  }
  const duplicateReads = [...readCounts.values()].reduce((sum, n) => sum + Math.max(0, n - 1), 0)
  const duplicateCommands = [...commandCounts.values()].reduce((sum, n) => sum + Math.max(0, n - 1), 0)
  record.labor = { reads, duplicateReads, commands, duplicateCommands, toolErrors }
  writeFileSync(path, JSON.stringify(record, null, 2))
  console.log(`${record.name}: reads=${reads} dupReads=${duplicateReads} cmds=${commands} dupCmds=${duplicateCommands} errors=${toolErrors}`)
}
