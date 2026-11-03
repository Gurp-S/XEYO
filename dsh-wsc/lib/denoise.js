/**
 * Deterministic view-level denoise rules, ported from XENYON `wsc/denoise`.
 *
 * Every rule rewrites a copy of the message content; the session log keeps the
 * original bytes. Rules never touch error results or non-text blocks.
 */
import { createHash } from 'node:crypto'

const ANSI = /\x1b\[[0-9;?]*[A-Za-z]/g
const DOTS = /^[.sFE]{8,}$/
const BLANKS = /\n{3,}/g

/** Every rule, in application order. */
export const ALL_DENOISE_RULES = [
  'strip_noise_lines',
  'collapse_stack',
  'diff_digest',
  'dedupe_identical',
  'dedupe_reads',
  'outline_json',
  'truncate_head_tail',
]

const textOf = (message) =>
  message.content
    .filter((block) => block.type === 'text')
    .map((block) => block.text)
    .join('\n')

const withText = (message, text) => ({
  ...message,
  content: [
    { type: 'text', text },
    ...message.content.filter((block) => block.type !== 'text'),
  ],
})

/** Drop ANSI escapes, carriage-return progress lines, pytest dots, and blank runs. */
export function stripNoiseLines(text) {
  const out = []
  for (const raw of text.split('\n')) {
    const line = raw.includes('\r') ? raw.split('\r').at(-1) : raw
    const cleaned = line.replace(ANSI, '')
    if (DOTS.test(cleaned.trim())) continue
    out.push(cleaned)
  }
  return out.join('\n').replace(BLANKS, '\n\n')
}

/** Collapse runs of identical consecutive lines into one line plus a count. */
export function collapseStack(text) {
  const lines = text.split('\n')
  const out = []
  let index = 0
  while (index < lines.length) {
    let run = 1
    while (index + run < lines.length && lines[index + run] === lines[index]) run += 1
    out.push(run > 1 ? `${lines[index]}  ×${run}` : lines[index])
    index += run
  }
  return out.join('\n')
}

/** Keep a bounded head and tail, marking the omitted middle by size. */
export function truncateHeadTail(text, head = 800, tail = 300) {
  if (text.length <= head + tail + 80) return text
  const omitted = text.length - head - tail
  return `${text.slice(0, head)}\n…[${omitted} chars omitted]…\n${text.slice(-tail)}`
}

/** Replace a large JSON payload with a key/type outline. */
export function outlineJson(text, maxLines = 40) {
  if (text.length < 1500) return text
  let value
  try {
    value = JSON.parse(text)
  } catch {
    return text
  }
  const lines = []
  const walk = (node, path, depth) => {
    if (lines.length >= maxLines) return
    if (Array.isArray(node)) {
      lines.push(`${path}: array(${node.length})`)
      if (node.length > 0 && depth < 2) walk(node[0], `${path}[0]`, depth + 1)
      return
    }
    if (node !== null && typeof node === 'object') {
      const keys = Object.keys(node)
      lines.push(`${path}: object(${keys.length} keys)`)
      if (depth < 2) for (const key of keys.slice(0, 12)) walk(node[key], `${path}.${key}`, depth + 1)
      return
    }
    lines.push(`${path}: ${node === null ? 'null' : typeof node}`)
  }
  walk(value, '$', 0)
  if (lines.length === 0) return text
  return `[json outline, ${text.length} bytes]\n${lines.join('\n')}`
}

/** Replace a unified diff with per-file change counts and hunk headers. */
export function diffDigest(text) {
  if (!text.includes('diff --git')) return text
  const files = []
  let current
  for (const line of text.split('\n')) {
    const header = /^diff --git a\/(\S+) b\/(\S+)/.exec(line)
    if (header !== null) {
      current = { path: header[2], added: 0, removed: 0, hunks: 0 }
      files.push(current)
      continue
    }
    if (current === undefined) continue
    if (line.startsWith('@@')) current.hunks += 1
    else if (line.startsWith('+') && !line.startsWith('+++')) current.added += 1
    else if (line.startsWith('-') && !line.startsWith('---')) current.removed += 1
  }
  if (files.length === 0) return text
  const body = files
    .map((file) => `${file.path} +${file.added} -${file.removed} (${file.hunks} hunks)`)
    .join('\n')
  return `[diff digest, ${text.length} bytes]\n${body}`
}

/**
 * Apply enabled rules to a copy of the region messages.
 *
 * @param {ReadonlyArray<object>} messages region messages.
 * @param {ReadonlyArray<string>} rules enabled rule ids.
 * @returns {{ messages: object[], actions: Array<{ rule: string, before: number, after: number }> }}
 */
export function applyDenoise(messages, rules) {
  const enabled = new Set(rules)
  if (enabled.size === 0) return { messages: [...messages], actions: [] }

  const callMeta = new Map()
  for (const message of messages) {
    if (message.role !== 'assistant') continue
    for (const block of message.content) {
      if (block.type !== 'tool-call') continue
      let args
      try {
        args = JSON.parse(block.arguments)
      } catch {
        args = undefined
      }
      callMeta.set(block.id, {
        name: block.name,
        path: typeof args?.path === 'string' ? args.path : args?.file_path,
      })
    }
  }

  const lastRead = new Map()
  for (const message of messages) {
    if (message.role !== 'tool') continue
    const meta = callMeta.get(message.toolCallId)
    if (meta?.name === 'read' && typeof meta.path === 'string') lastRead.set(meta.path, message.toolCallId)
  }

  const seen = new Set()
  const actions = []
  const output = messages.map((message) => {
    if (message.role !== 'tool' || message.isError === true) return message
    const text = textOf(message)
    if (text.length === 0) return message
    const meta = callMeta.get(message.toolCallId)

    if (enabled.has('dedupe_reads') && meta?.name === 'read' && lastRead.get(meta.path) !== message.toolCallId) {
      const replacement = `[superseded by a later read of ${meta.path}]`
      actions.push({ rule: 'dedupe_reads', before: text.length, after: replacement.length })
      return withText(message, replacement)
    }

    if (enabled.has('dedupe_identical')) {
      const key = text
      if (seen.has(key)) {
        const replacement = '[identical to an earlier result]'
        actions.push({ rule: 'dedupe_identical', before: text.length, after: replacement.length })
        return withText(message, replacement)
      }
      seen.add(key)
    }

    let next = text
    if (enabled.has('strip_noise_lines')) next = stripNoiseLines(next)
    if (enabled.has('collapse_stack')) next = collapseStack(next)
    if (enabled.has('diff_digest')) next = diffDigest(next)
    if (enabled.has('outline_json')) next = outlineJson(next)
    if (enabled.has('truncate_head_tail')) next = truncateHeadTail(next)

    if (next === text) return message
    actions.push({ rule: 'combined', before: text.length, after: next.length })
    return withText(message, next)
  })

  return { messages: output, actions }
}

/** Per-session runtime state for cross-call rules. */
export function createDenoiseState() {
  return { reads: new Map(), seen: new Set() }
}

const hashOf = (text) => createHash('sha1').update(text).digest('hex')

/**
 * Runtime denoise for one tool result, applied before the result enters the
 * request history. Cross-call rules use the session state.
 *
 * `read` results keep their exact bytes unless an identical repeat is detected;
 * rewriting source text would defeat the tool's purpose.
 *
 * @param {string} text joined text content of the result.
 * @param {{ toolName: string, callId: string, args: unknown, state: object }} context
 * @returns {{ text: string, rules: string[] } | null} replacement, or null to keep the original.
 */
export function runtimeDenoise(text, context) {
  const { toolName, callId, args, state } = context
  const hash = hashOf(text)
  const path =
    typeof args?.path === 'string'
      ? args.path
      : typeof args?.file_path === 'string'
        ? args.file_path
        : undefined

  if (toolName === 'read' && path !== undefined) {
    const previous = state.reads.get(path)
    state.reads.set(path, { callId, hash })
    if (previous !== undefined && previous.hash === hash) {
      return { text: `[read ${path} again; identical to call ${previous.callId}]`, rules: ['dedupe_reads'] }
    }
    return null
  }

  if (state.seen.has(hash)) return { text: '[identical to an earlier result]', rules: ['dedupe_identical'] }
  state.seen.add(hash)

  const rules = []
  let next = text
  const apply = (id, fn) => {
    const before = next
    next = fn(next)
    if (next !== before) rules.push(id)
  }
  apply('strip_noise_lines', stripNoiseLines)
  apply('collapse_stack', collapseStack)
  apply('diff_digest', diffDigest)
  apply('outline_json', outlineJson)
  apply('truncate_head_tail', truncateHeadTail)

  return rules.length === 0 ? null : { text: next, rules }
}
