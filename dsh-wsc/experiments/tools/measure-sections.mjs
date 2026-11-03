/**
 * Measure what the working set and the flat file list each cost and carry.
 *
 * Replays real session logs through the same builder the engine calls, with the
 * production working-set settings, then compares the two sections byte for byte
 * and path for path. Read-only: nothing is written outside stdout.
 *
 * Usage: node experiments/tools/measure-sections.mjs <session.jsonl.zstd>...
 */
import { readSessionEvents } from './read-session.mjs'
import { buildCheckpoint } from '../../lib/checkpoint.js'
import { byteLength } from '../../lib/bytes.js'

const WORKING_SET = '## Working set (file state the model last saw)'
const FILES = '## Files touched'
const TAIL = 30

/** Body of one rendered section, up to the next heading. */
const sectionOf = (text, heading) => {
  const at = text.indexOf(`${heading}\n`)
  if (at === -1) return ''
  const lines = text.slice(at + heading.length + 1).split('\n')
  const body = []
  for (const line of lines) {
    if (line.startsWith('## ')) break
    body.push(line)
  }
  return body.join('\n').trim()
}

/** Item paths in one section: the leading token of each bullet. */
const pathsOf = (body, separator) => {
  const paths = new Set()
  for (const line of body.split('\n')) {
    if (!line.startsWith('- ')) continue
    const item = line.slice(2)
    const cut = separator === ' (' ? item.indexOf(' (') : item.indexOf(' — ')
    const path = cut === -1 ? item : item.slice(0, cut)
    if (path.length > 0) paths.add(path)
  }
  return paths
}

const messagesOf = (events) => {
  const messages = []
  for (const event of events) {
    const message =
      event.data?.message ??
      event.message ??
      (event.data?.role !== undefined && event.data?.content !== undefined ? event.data : undefined)
    if (message?.role !== undefined && message.content !== undefined) messages.push(message)
  }
  return messages
}

const options = {
  isCheckpointSource: (source) => source?.kind === 'checkpoint',
  workingset: { version: 2, maxFiles: 6, capChars: 700, sectionCap: 2500 },
}

/** Paths any file tool was called on, whatever the working set kept. */
const touchedPathsOf = (messages) => {
  const paths = new Set()
  for (const message of messages) {
    const blocks = Array.isArray(message.content) ? message.content : []
    for (const block of blocks) {
      if (block?.type !== 'tool-call') continue
      if (!['read', 'write', 'edit'].includes(block.name)) continue
      try {
        const args = JSON.parse(block.arguments)
        if (typeof args?.path === 'string') paths.add(args.path)
        else if (typeof args?.file_path === 'string') paths.add(args.file_path)
      } catch {
        // unparsable arguments contribute no path
      }
    }
  }
  return paths
}

const rows = []
for (const file of process.argv.slice(2)) {
  let messages
  try {
    messages = messagesOf(readSessionEvents(file))
  } catch (error) {
    console.error(`skip ${file}: ${error.message}`)
    continue
  }
  if (messages.length === 0) continue
  const region = messages.slice(-TAIL)
  const touched = touchedPathsOf(region)
  const built = buildCheckpoint({ messages: region }, options)
  const workingset = sectionOf(built.text, WORKING_SET)
  const files = sectionOf(built.text, FILES)
  const workingPaths = pathsOf(workingset, ' — ')
  const filePaths = pathsOf(files, ' (')
  const shared = [...filePaths].filter((path) => workingPaths.has(path))
  const onlyFiles = [...filePaths].filter((path) => !workingPaths.has(path))
  rows.push({
    name: file.split('\\').slice(-2)[0],
    total: byteLength(built.text),
    workingset: byteLength(workingset),
    files: byteLength(files),
    workingPaths: workingPaths.size,
    filePaths: filePaths.size,
    shared: shared.length,
    onlyFiles,
    evicted: onlyFiles.filter((path) => touched.has(path)),
  })
}

const sum = (key) => rows.reduce((total, row) => total + row[key], 0)
const percent = (part, whole) => (whole === 0 ? '0%' : `${Math.round((part / whole) * 100)}%`)

console.log('session            total   ws B  files B  ws%  files%  ws#  files#  shared  onlyFiles')
for (const row of rows) {
  console.log(
    `${row.name.slice(0, 18).padEnd(18)} ${String(row.total).padStart(6)} ${String(row.workingset).padStart(6)} ${String(row.files).padStart(8)} ${percent(row.workingset, row.total).padStart(4)} ${percent(row.files, row.total).padStart(7)} ${String(row.workingPaths).padStart(4)} ${String(row.filePaths).padStart(7)} ${String(row.shared).padStart(7)} ${String(row.onlyFiles.length).padStart(10)}`,
  )
}
console.log(
  `\n${rows.length} sessions: total ${sum('total')} B, working set ${sum('workingset')} B (${percent(sum('workingset'), sum('total'))}), files touched ${sum('files')} B (${percent(sum('files'), sum('total'))})`,
)
const onlyFiles = rows.flatMap((row) => row.onlyFiles)
const evicted = rows.flatMap((row) => row.evicted)
console.log(`paths only in Files touched: ${onlyFiles.length}`)
for (const path of [...new Set(onlyFiles)].slice(0, 12)) console.log(`  ${path}`)
console.log(`of those, touched by a file tool but evicted from the working set: ${[...new Set(evicted)].length}`)
for (const path of [...new Set(evicted)].slice(0, 12)) console.log(`  evicted: ${path}`)
