/**
 * Working-set snapshots for the checkpoint.
 *
 * A compaction that drops tool results also drops the file contents the model
 * just read. The model then re-reads them, which refills the context and
 * triggers the next compaction. Measured on the fixture task, that loop made a
 * run read 11x more than an uncompacted run for the same 16 files.
 *
 * The fix is to carry state rather than a narrative about state: keep the last
 * known content of every file the model read or wrote, and mark a snapshot
 * stale when a later edit changed it, so the model never edits from a snapshot
 * that is silently out of date.
 *
 * The tracker is stateful on purpose. One compaction only shadows a dozen
 * messages, so a set rebuilt from that region alone forgets every file read two
 * compactions ago; a checkpoint that carries its predecessor's set forward keeps
 * them.
 */

import { toolResultOf } from './projection.js'

const DEFAULT_CAP_CHARS = 1200
const DEFAULT_MAX_FILES = 8
const EDIT_EXCERPT = 160
const SECTION_HEADING = '## Working set'

/**
 * Strip the read tool's own envelope from its output.
 *
 * The tool answers with `<path>…</path>\n<type>file</type>\n<content>\n…`, and
 * the path is already printed on the item's first line, so the envelope is
 * duplicated metadata rather than file content.
 *
 * @param {string} text raw tool output.
 * @returns {string} the file body.
 */
export const unwrapReadResult = (text) => {
  const open = text.indexOf('<content>')
  const close = text.lastIndexOf('</content>')
  if (open === -1 || close <= open) return text
  return text.slice(open + '<content>'.length, close).replace(/^\r?\n/, '').replace(/\r?\n$/, '')
}

export const safeParse = (value) => {
  if (typeof value === 'object' && value !== null) return value
  if (typeof value !== 'string') return {}
  try {
    return JSON.parse(value)
  } catch {
    return {}
  }
}

export const pathOf = (args) => {
  const candidate = args.path ?? args.file_path ?? args.target_file ?? args.notebook_path
  return typeof candidate === 'string' && candidate.length > 0 ? candidate : undefined
}

/** Keep both ends of a long file: edits usually touch one or the other. */
export function clamp(text, limit) {
  if (text.length <= limit) return text
  const head = Math.floor(limit * 0.7)
  const tail = limit - head - 40
  const omitted = text.length - head - tail
  return `${text.slice(0, head)}\n… ${omitted} chars omitted …\n${text.slice(text.length - tail)}`
}

export const lineCount = (text) => text.split('\n').length

const ITEM_HEADER = /^(.+?) — (read|write|edit) #(\d+)(.*)$/

/**
 * Parse a rendered working-set section back into entries.
 *
 * The checkpoint is the only carrier between compactions, so the next set is
 * seeded from the previous section's text. A stale item carries no body (it was
 * deliberately withheld), only the edit that invalidated it.
 *
 * @param {string} text prior checkpoint text (wrapper already stripped).
 * @returns {Array<object>} entries in render order.
 */
function parseSection(text) {
  const at = text.indexOf(SECTION_HEADING)
  if (at === -1) return []
  const lines = text.slice(at).split('\n').slice(1)
  const entries = []
  let current
  for (const line of lines) {
    if (line.startsWith('## ')) break
    const header = ITEM_HEADER.exec(line)
    if (header !== null) {
      const [, path, kind, clock, rest] = header
      const entry = {
        path,
        snapshot: undefined,
        edits: [],
        clock: Number(clock),
        kind,
      }
      if (rest.includes('unchanged since')) {
        const size = /(\d+) lines/.exec(rest)
        entry.snapshot = { text: '', clock: Number(clock), kind, lines: size === null ? 0 : Number(size[1]) }
      } else {
        const edited = /edited at #(\d+)/.exec(rest)
        const excerpt = /last edit wrote: (".*")\s*$/.exec(rest)
        let newText = ''
        if (excerpt !== null) {
          try {
            newText = String(JSON.parse(excerpt[1])).slice(0, EDIT_EXCERPT)
          } catch {
            newText = ''
          }
        }
        entry.edits.push({ clock: edited === null ? Number(clock) : Number(edited[1]), newText })
      }
      entries.push(entry)
      current = entry
      continue
    }
    if (current !== undefined && current.snapshot !== undefined && line.length > 0) {
      current.snapshot.text += `${current.snapshot.text.length === 0 ? '' : '\n'}${line}`
    }
  }
  return entries
}

/**
 * Create a tracker that accumulates file state across compactions.
 *
 * @param {{ capChars?: number, maxFiles?: number, seed?: string }} options
 *   `seed` is the previous checkpoint's text; its working-set section, if any,
 *   is restored before the new region is applied.
 * @returns {{ apply: (messages: ReadonlyArray<object>) => void, items: () => string[], size: () => number }}
 */
export function createWorkingSet(options = {}) {
  const capChars = options.capChars ?? DEFAULT_CAP_CHARS
  const maxFiles = options.maxFiles ?? DEFAULT_MAX_FILES
  const pendingReads = new Map()
  const entries = new Map()
  let clock = 0

  const entryOf = (path, index) => {
    let entry = entries.get(path)
    if (entry === undefined) {
      entry = { path, snapshot: undefined, edits: [], lastTouch: index }
      entries.set(path, entry)
    }
    entry.lastTouch = index
    return entry
  }

  if (typeof options.seed === 'string' && options.seed.length > 0) {
    for (const entry of parseSection(options.seed)) {
      entries.set(entry.path, { ...entry, lastTouch: entry.clock })
      clock = Math.max(clock, entry.clock + 1)
    }
  }

  const apply = (messages) => {
    for (const message of messages) {
      const index = clock
      clock += 1
      if (message.role === 'assistant') {
        for (const block of message.content ?? []) {
          if (block?.type !== 'tool-call') continue
          const args = safeParse(block.arguments)
          const path = pathOf(args)
          if (path === undefined) continue
          if (block.name === 'read') {
            pendingReads.set(block.id, { path, index })
            entryOf(path, index)
          } else if (block.name === 'write') {
            const content = args.content ?? args.file_text ?? args.text
            const entry = entryOf(path, index)
            if (typeof content === 'string') {
              entry.snapshot = { text: content, clock: index, kind: 'write' }
              entry.edits = []
            }
          } else if (block.name === 'edit') {
            const entry = entryOf(path, index)
            const newText = String(args.new_string ?? args.newText ?? '')
            entry.edits.push({ clock: index, newText: newText.slice(0, EDIT_EXCERPT) })
          }
        }
        continue
      }
      // A tool result is a user-role message carrying a `tool-result` block:
      // the call id and the error flag live on that block, and the body is a
      // nested `content` array rather than a message-level `text` block.
      const result = toolResultOf(message)
      if (result === undefined) continue
      const read = pendingReads.get(result.callId)
      if (read === undefined) continue
      pendingReads.delete(result.callId)
      if (result.isError) continue
      const text = unwrapReadResult(result.text)
      if (text.trim().length === 0) continue
      const entry = entryOf(read.path, read.index)
      entry.snapshot = { text, clock: read.index, kind: 'read' }
      entry.edits = []
    }
  }

  const items = () => {
    const ordered = [...entries.values()]
      .filter((entry) => entry.snapshot !== undefined)
      .sort((left, right) => left.lastTouch - right.lastTouch)
      .slice(-maxFiles)

    const lines = []
    for (const entry of ordered) {
      const { snapshot } = entry
      const stale = entry.edits.filter((edit) => edit.clock > snapshot.clock)
      const source = `${snapshot.kind} #${snapshot.clock}`
      if (stale.length === 0) {
        const body = clamp(snapshot.text.trimEnd(), capChars)
        const size = snapshot.lines ?? lineCount(snapshot.text)
        lines.push(`${entry.path} — ${source}, unchanged since; ${size} lines\n${body}`)
        continue
      }
      // A stale snapshot is a trap: name the fact that it is out of date and show
      // only what the model itself wrote afterwards, never the out-of-date body.
      const lastEdit = stale.at(-1)
      const excerpt = lastEdit.newText.length > 0 ? `: ${JSON.stringify(lastEdit.newText)}` : ''
      lines.push(
        `${entry.path} — ${source}; body stale, edited at #${stale.map((edit) => edit.clock).join(', #')}` +
          `; last edit wrote${excerpt}`,
      )
    }
    return lines
  }

  return { apply, items, size: () => entries.size }
}

/**
 * @param {ReadonlyArray<object>} messages replayed region messages, in order.
 * @param {{ capChars?: number, maxFiles?: number, seed?: string }} options
 * @returns {string[]} one entry per file, oldest touch first.
 */
export function buildWorkingSet(messages, options = {}) {
  const tracker = createWorkingSet(options)
  tracker.apply(messages)
  return tracker.items()
}
