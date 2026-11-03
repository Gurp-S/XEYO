/**
 * Working set, second form.
 *
 * Measured on the fixture task, v1 was unstable: one run cost 153 K input
 * tokens, the next 440 K. The difference was not the amount of state carried
 * but two mechanical defects:
 *
 *   1. A stale entry dropped its body and kept only "body stale, edited at #n".
 *      The model then had no content to edit from and re-read the file, which
 *      is the very cost the section exists to remove. On the 440 K run, 109 of
 *      138 reads were repeats, and the degenerate sections shrank to 161 B.
 *   2. The section had no ceiling. Eight files at 1200 chars reached 5.3 KB,
 *      a fifth of the checkpoint, and squeezed `selected`.
 *
 * v2 keeps four facts per file and never withdraws the body:
 *
 *   path — read #12 · role: "…" · edited #18 (+12/−3): "…"
 *   <body>
 *
 * `role` is the model's own words at the moment it last touched the file —
 * read, write or edit — quoted verbatim, with its clock when that touch is
 * newer than the body. It is a statement about the past, so it cannot go
 * stale: it never claims the file still does that, only that the model then
 * thought so. The engine authors no guidance here — every line is a fact
 * about what happened.
 */

import { clamp, lineCount, pathOf, safeParse, unwrapReadResult } from './workingset.js'
import { toolResultOf } from './projection.js'

const DEFAULT_CAP_CHARS = 700
const DEFAULT_MAX_FILES = 6
const DEFAULT_SECTION_CAP = 2500
const ROLE_CHARS = 120
const EDIT_EXCERPT = 160
const MAX_EDITS = 3
const SECTION_HEADING = '## Working set'

const ITEM_HEADER = /^(.+?) — (read|write|edit) #(\d+)(.*)$/
const ROLE = / · role(?: at #(\d+))?: ("(?:[^"\\]|\\.)*")/
const EDIT = / · edited #(\d+) \(\+(\d+)\/[\-−](\d+)\): ("(?:[^"\\]|\\.)*")/g

const parseJson = (text, fallback) => {
  try {
    return String(JSON.parse(text))
  } catch {
    return fallback
  }
}

/**
 * The model's own words at the moment it issued the read.
 *
 * Tool-call messages usually open with a line naming what the read is for
 * ("Checking how the planner resolves outputs"). Taking the first non-empty
 * line keeps the section thin and keeps the sentence attributable to the model.
 */
const roleOf = (message) => {
  const parts = (message.content ?? [])
    .filter((block) => block?.type === 'text' && typeof block.text === 'string')
    .map((block) => block.text)
    .join('\n')
  const line = parts
    .split('\n')
    .map((text) => text.trim())
    .find((text) => text.length > 0)
  return line === undefined ? undefined : line.slice(0, ROLE_CHARS)
}

/**
 * Restore entries from the previous checkpoint's section.
 *
 * Reads both v2 headers and the v1 forms (`unchanged since`, `body stale`), so
 * a run that switches versions mid-session keeps every body it already had.
 *
 * @param {string} text prior checkpoint text.
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
      const entry = { path, snapshot: undefined, edits: [], role: undefined, clock: Number(clock), kind }
      const role = ROLE.exec(rest)
      if (role !== null) {
        entry.role = {
          text: parseJson(role[2], ''),
          clock: role[1] === undefined ? Number(clock) : Number(role[1]),
        }
      }
      EDIT.lastIndex = 0
      let edit = EDIT.exec(rest)
      while (edit !== null) {
        entry.edits.push({
          clock: Number(edit[1]),
          added: Number(edit[2]),
          removed: Number(edit[3]),
          newText: parseJson(edit[4], ''),
        })
        edit = EDIT.exec(rest)
      }
      if (entry.edits.length === 0) {
        // v1 stale form: the body was withheld, so there is nothing to restore.
        const edited = /edited at #(\d+)/.exec(rest)
        if (edited !== null) entry.edits.push({ clock: Number(edited[1]), added: 0, removed: 0, newText: '' })
      }
      if (rest.includes('unchanged since')) {
        entry.snapshot = { text: '', clock: Number(clock), kind, lines: 0 }
      } else if (!rest.includes('body stale')) {
        // v2 always renders the body, so the lines that follow belong to it.
        entry.snapshot = { text: '', clock: Number(clock), kind }
      }
      entries.push(entry)
      current = entry
      continue
    }
    if (current !== undefined && current.snapshot !== undefined) {
      current.snapshot.text += `${current.snapshot.text.length === 0 ? '' : '\n'}${line}`
    }
  }
  return entries
}

/**
 * @param {{ capChars?: number, maxFiles?: number, sectionCap?: number, seed?: string }} options
 * @returns {{ apply: (messages: ReadonlyArray<object>) => void, items: () => string[], size: () => number }}
 */
export function createWorkingSet(options = {}) {
  const capChars = options.capChars ?? DEFAULT_CAP_CHARS
  const maxFiles = options.maxFiles ?? DEFAULT_MAX_FILES
  const sectionCap = options.sectionCap ?? DEFAULT_SECTION_CAP
  const pendingReads = new Map()
  const entries = new Map()
  let clock = 0

  const entryOf = (path, index) => {
    let entry = entries.get(path)
    if (entry === undefined) {
      entry = { path, snapshot: undefined, edits: [], role: undefined, lastTouch: index }
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
            const entry = entryOf(path, index)
            const role = roleOf(message)
            if (role !== undefined) entry.role = { text: role, clock: index }
          } else if (block.name === 'write') {
            const content = args.content ?? args.file_text ?? args.text
            const entry = entryOf(path, index)
            if (typeof content === 'string') {
              entry.snapshot = { text: content, clock: index, kind: 'write' }
              entry.edits = []
            }
            const role = roleOf(message)
            if (role !== undefined) entry.role = { text: role, clock: index }
          } else if (block.name === 'edit') {
            const entry = entryOf(path, index)
            const newText = String(args.new_string ?? args.newText ?? '')
            const oldText = String(args.old_string ?? args.oldText ?? '')
            entry.edits.push({
              clock: index,
              added: newText.length === 0 ? 0 : lineCount(newText),
              removed: oldText.length === 0 ? 0 : lineCount(oldText),
              newText: newText.slice(0, EDIT_EXCERPT),
            })
            if (entry.edits.length > MAX_EDITS) entry.edits = entry.edits.slice(-MAX_EDITS)
            const role = roleOf(message)
            if (role !== undefined) entry.role = { text: role, clock: index }
          }
        }
        continue
      }
      // A tool result is a user-role message carrying a `tool-result` block:
      // the call id and error flag live on that block and its body is a nested
      // `content` array. `textOf` reads message-level `text` blocks only, so
      // every read result came back empty and no snapshot was ever recorded.
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
      // A re-read at #index already contains every earlier edit.
      entry.edits = entry.edits.filter((edit) => edit.clock > read.index)
    }
  }

  const render = (entry) => {
    const { snapshot } = entry
    const parts = [`${entry.path} — ${snapshot.kind} #${snapshot.clock}`]
    if (entry.role !== undefined) {
      const label = entry.role.clock === snapshot.clock ? 'role' : `role at #${entry.role.clock}`
      parts.push(` · ${label}: ${JSON.stringify(entry.role.text)}`)
    }
    for (const edit of entry.edits) {
      parts.push(
        ` · edited #${edit.clock} (+${edit.added}/−${edit.removed}): ${JSON.stringify(edit.newText)}`,
      )
    }
    // The body is always present: a stale body plus its delta is editable, a
    // withdrawn body is not, and the model pays a re-read to recover it.
    return `${parts.join('')}\n${clamp(snapshot.text.trimEnd(), capChars)}`
  }

  const items = () => {
    let ordered = [...entries.values()]
      .filter((entry) => entry.snapshot !== undefined)
      .sort((left, right) => left.lastTouch - right.lastTouch)
      .slice(-maxFiles)
    let lines = ordered.map(render)
    // Drop whole entries from the oldest end rather than truncating a body: a
    // half body costs the same as a full one and teaches less.
    while (lines.length > 1 && lines.join('\n').length > sectionCap) {
      ordered = ordered.slice(1)
      lines = ordered.map(render)
    }
    return lines
  }

  return { apply, items, size: () => entries.size }
}

/**
 * @param {ReadonlyArray<object>} messages replayed region messages, in order.
 * @param {{ capChars?: number, maxFiles?: number, sectionCap?: number, seed?: string }} options
 * @returns {string[]} one entry per file, oldest touch first.
 */
export function buildWorkingSet(messages, options = {}) {
  const tracker = createWorkingSet(options)
  tracker.apply(messages)
  return tracker.items()
}
