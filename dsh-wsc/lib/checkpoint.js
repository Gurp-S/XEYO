/**
 * Deterministic checkpoint builder.
 *
 * The checkpoint is extractive: it quotes user control text, errors, tool calls,
 * and recent assistant decisions verbatim, then drops detail to fit a fixed
 * fraction of the shadowed bytes. No model call and no paraphrase, so exact
 * paths, commands, error strings, and version identifiers survive.
 */
import { ALL_DENOISE_RULES, applyDenoise } from './denoise.js'
import { byteLength, jsonBytes, truncateBytes } from './bytes.js'
import { resolveExcerpt } from './excerpts.js'
import { collapsePriorEcho, payloadItemCap, resolvePayloadPolicy, sectionWeight, stripPriorEcho } from './payload.js'
import { buildWorkingSet } from './workingset.js'
import { buildWorkingSet as buildWorkingSetV2 } from './workingset-v2.js'
import { messageText } from './projection.js'

const HEADINGS = {
  prior: '## Prior checkpoint (historical; re-check current evidence)',
  users: '## User requests (verbatim, control)',
  control: '## User requests and instructions (verbatim, control)',
  selected: '## Selected excerpts (verbatim; role prefix shows the speaker)',
  judgments: '## Recorded judgments (model, sourced; [sN] cites a selected excerpt)',
  developers: '## Developer instructions (verbatim, control)',
  errors: '## Errors',
  outputs: '## Recent tool results',
  decisions: '## Recent assistant statements (model, not user instructions)',
  calls: '## Tool calls (oldest first)',
  files: '## Files touched',
  workingset: '## Working set (file state the model last saw)',
  verification: '## Verification state (runtime facts; #n is the message position in this region)',
}

const MAX_SECTION_ITEMS = {
  prior: 1,
  users: 8,
  developers: 4,
  errors: 12,
  outputs: 6,
  decisions: 4,
  calls: 30,
  files: 25,
  workingset: 8,
  verification: 8,
  judgments: 12,
}

const SECTION_WEIGHT = {
  prior: 0.25,
  users: 0.35,
  developers: 0.1,
  errors: 0.2,
  outputs: 0.2,
  decisions: 0.2,
  calls: 0.15,
  files: 0.1,
  // File contents are what the model needs to keep editing without re-reading,
  // so this section outranks every narration section.
  workingset: 0.45,
  verification: 0.25,
  judgments: 0.2,
}

/**
 * Section order in the rendered checkpoint, highest value first.
 *
 * The order sections are *allocated* in and the order they are *rendered* in
 * used to differ: allocation started at the control section, rendering started
 * at the prior-checkpoint echo. Because a checkpoint is cut at the budget, that
 * put the least valuable text (a copy of the previous checkpoint) in front of
 * everything else and let it survive truncation.
 */
const RENDER_ORDER = [
  'control',
  'users',
  'workingset',
  'selected',
  'prior',
  'judgments',
  'verification',
  'errors',
  'outputs',
  'decisions',
  'calls',
  'files',
]

/**
 * Per-item cap for the control section: user messages in the deterministic
 * build, the `control` section in the selective one.
 *
 * Both builders read this one value through {@link controlItemCapOf}. They used
 * to hold separate 800s, so raising one still left the other truncating the
 * task prompt mid-sentence.
 */
const CONTROL_ITEM_CAP = 800

/**
 * Resolve the control-section per-item cap from builder options.
 *
 * `0` means no per-item cap: the section budget alone decides. Any other
 * non-negative integer is taken literally; an absent or invalid value keeps the
 * shipped default so existing callers are unchanged.
 *
 * @param {object} options builder options.
 * @returns {number} byte cap, possibly Infinity.
 */
const controlItemCapOf = (options) => {
  const configured = options?.controlItemCap
  if (!Number.isInteger(configured) || configured < 0) return CONTROL_ITEM_CAP
  return configured === 0 ? Number.POSITIVE_INFINITY : configured
}

/**
 * Working-set section items, or an empty section when the feature is off.
 *
 * Both builders read it through here so the deterministic and selective paths
 * cannot drift apart on whether file state survives a compaction.
 *
 * @param {ReadonlyArray<object>} messages replayed region messages.
 * @param {object} options builder options; `workingset` is a boolean or an
 *   options object for {@link buildWorkingSet}.
 * @returns {string[]} section items.
 */
const workingsetSectionOf = (messages, options, seed) => {
  const configured = options.workingset
  if (configured === undefined || configured === false) return []
  const settings = typeof configured === 'object' ? configured : {}
  // Monotone in version: the tool description already treats anything at or
  // above 2 as the second form, so an unknown higher version must not silently
  // regress to the first.
  const build = (settings.version ?? 1) >= 2 ? buildWorkingSetV2 : buildWorkingSet
  return build(messages, seed === undefined ? settings : { ...settings, seed })
}

/**
 * Recent tool output, verbatim, as the section that fills what is left.
 *
 * Selection by a model is conservative: measured runs kept 212 B of a 14 KB
 * budget, so the checkpoint held a twentieth of what it could. This section is
 * engine-side and deterministic — the outputs a later model would otherwise
 * re-run a command to recover — and it is filled last, so it can only use
 * budget no higher-value section claimed.
 *
 * @param {ReadonlyArray<object>} messages region messages.
 * @param {object} options builder options; `outputs` is `{ items, cap }`.
 * @param {ReadonlyArray<{ text: string }>} selected excerpts already carried.
 * @param {Map<string, string>} callNames tool name per call id.
 * @returns {string[]} section items.
 */
const outputsSectionOf = (messages, options, selected, callNames) => {
  const config = options?.outputs
  if (config === undefined || config === false) return []
  const items = Number.isInteger(config?.items) ? config.items : 10
  const cap = Number.isInteger(config?.cap) ? config.cap : 900
  const quoted = selected.map((item) => item.text)
  const kept = []
  for (let index = messages.length - 1; index >= 0 && kept.length < items; index -= 1) {
    const message = messages[index]
    // The harness projects a tool result into a user-role message carrying
    // `toolCallId`; `role === 'tool'` never appears in a live region.
    const callId = message.toolCallId ?? message.source?.callId
    if (callId === undefined) continue
    const body = messageText(message, { toolText: true }).trim()
    // Empty or one-line acknowledgements carry nothing worth the bytes; a short
    // error string is exactly what must survive, so the floor stays low.
    if (body.length < 12) continue
    // A selected excerpt already holds these bytes; quoting them twice wastes
    // budget the section exists to spend on material nothing else carries.
    if (quoted.some((text) => text.includes(body))) continue
    kept.unshift({ text: truncate(body, cap), name: callNames.get(callId) ?? 'tool' })
  }
  return kept.map((item, position) => `[o${position + 1}] [tool:${item.name}] ${item.text}`)
}

/**
 * The previous checkpoint's text, if the region carries one.
 *
 * One compaction shadows only a dozen messages, so a set rebuilt from the
 * region alone forgets every file read earlier in the run. The prior
 * checkpoint's working-set section is the carrier that keeps them.
 *
 * @param {ReadonlyArray<object>} messages region messages.
 * @param {(source: unknown) => boolean} isCheckpointSource source predicate.
 * @returns {string|undefined} wrapper-free prior checkpoint text.
 */
const priorCheckpointText = (messages, isCheckpointSource) => {
  let text
  for (const message of messages) {
    if (!isCheckpointSource(message.source)) continue
    const inner = (Array.isArray(message.content) ? message.content : [])
      .filter((block) => block.type === 'text')
      .map((block) => block.text)
      .join('\n')
    text = priorBody(inner)
  }
  return text
}

/**
 * Allocation floor for the working-set section.
 *
 * File state is the only section the model can act on without a tool call, so
 * it gets what its items need instead of only its weighted share. The floor is
 * capped at half the budget, so it can never starve the control section or
 * overrun the checkpoint.
 *
 * @param {number} budget checkpoint budget in bytes.
 * @param {ReadonlyArray<string>} items section items.
 * @returns {number} bytes the section may claim at minimum.
 */
const workingsetFloor = (budget, items) => {
  if (items.length === 0) return 0
  const demand = items.reduce((total, item) => total + byteLength(item), 0)
  // A quarter, not a half: file bodies are the largest section and the only one
  // that grows with every file the model opens. Reserving half the budget made
  // a tight window compact sooner than without the section at all — the carried
  // state pushed the region back over the threshold it was meant to lower.
  return Math.min(budget, Math.floor(budget * 0.25), demand)
}

/** Per-item cap so one huge output cannot consume a whole section. */
const SECTION_ITEM_CAP = {  prior: 1200,
  // `users` is not listed: the control section reads CONTROL_ITEM_CAP instead,
  // so there is exactly one place that can truncate the task prompt.
  developers: 600,
  errors: 500,
  outputs: 240,
  decisions: 320,
  calls: 160,
  files: 120,
  workingset: 1200,
  verification: 220,
  judgments: 320,
}

const DEFAULT_MAX_CHARS = 24000
const SOURCE_FRACTION = 0.35

const textOf = (message) =>
  message.content
    .filter((block) => block.type === 'text')
    .map((block) => block.text)
    .join('\n')

const callBlocksOf = (message) => message.content.filter((block) => block.type === 'tool-call')

/**
 * Resolve a 1-based inclusive line range to a code-point span.
 *
 * The model addresses lines; the engine copies the bytes. That keeps the
 * excerpt exact and costs the model a few tokens instead of a full quote.
 *
 * @param {string} body message body, same projection the transcript showed.
 * @param {number} from first line, 1-based.
 * @param {number} to last line, inclusive.
 * @returns {{ start: number, end: number } | null} code-point span, or null when from is past the end.
 */
const lineSpan = (body, from, to) => {
  const points = Array.from(body)
  let index = 0
  let line = 1
  let start = -1
  let end = -1
  while (index < points.length) {
    if (line === from && start === -1) start = index
    while (index < points.length && points[index] !== '\n') index += 1
    if (line === to) {
      end = index
      break
    }
    index += 1
    line += 1
  }
  if (start === -1) return null
  return { start, end: end === -1 ? points.length : end }
}

const messageBytes = (message) => jsonBytes(message.content)

const safeParse = (value) => {
  if (typeof value !== 'string') return undefined
  try {
    return JSON.parse(value)
  } catch {
    return undefined
  }
}

const firstLine = (value) => {
  const text = String(value ?? '').trim()
  const index = text.indexOf('\n')
  return index === -1 ? text : text.slice(0, index)
}

const truncate = (value, limit) => {
  const text = String(value ?? '')
  return text.length <= limit ? text : `${text.slice(0, limit)}…`
}

const pathOf = (args) => {
  if (args === undefined || args === null || typeof args !== 'object') return undefined
  const candidate = args.path ?? args.file_path ?? args.target_file ?? args.notebook_path
  return typeof candidate === 'string' && candidate.length > 0 ? candidate : undefined
}

/**
 * Body of one section of a previous checkpoint.
 *
 * @param {string} text checkpoint text, wrapper already removed.
 * @param {string} heading the section heading line to read.
 * @returns {string} the lines under it, up to the next section heading; '' when
 *   the section is absent.
 */
const sectionBody = (text, heading) => {
  if (typeof text !== 'string' || text.length === 0) return ''
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

/**
 * Control section carried forward from a previous checkpoint.
 *
 * Both builders write a control section, under their own heading; a session
 * that switched builders mid-run has to read either.
 *
 * @param {string} text previous checkpoint text.
 * @returns {string} the carried control body, or '' when there is none.
 */
const carriedControl = (text) => {
  const body = sectionBody(text, HEADINGS.control) || sectionBody(text, HEADINGS.users)
  if (body.length === 0) return ''
  const [first, ...rest] = body.split('\n')
  // The section was rendered as bullets: undo that framing so the carried text
  // is re-bulleted by this build instead of nesting under a second bullet.
  const head = first.replace(/^-\s+/, '')
  const tail = rest.map((line) => line.replace(/^ {2}/, ''))
  return [head, ...tail].join('\n').trim()
}

/** Drop the framing a previous checkpoint added, keeping its inner text. */
const stripCheckpointWrapper = (text) => {
  const open = text.indexOf('<compacted-summary>')
  const close = text.lastIndexOf('</compacted-summary>')
  if (open !== -1 && close > open) {
    return text.slice(open + '<compacted-summary>'.length, close).trim()
  }
  return text
}

/**
 * Previous checkpoint text as this checkpoint may carry it.
 *
 * The wrapper goes, and with it the checkpoint's own prior-checkpoint block:
 * that block is a copy of a copy, and carrying it is what turned successive
 * checkpoints into a column of nested headings with nothing under them.
 *
 * @param {string} text raw checkpoint message text.
 * @returns {string} carryable prior text.
 */
const priorBody = (text) => stripPriorEcho(stripCheckpointWrapper(text))

const VERIFICATION_COMMAND =
  /(^|[\s;&|])(test|pytest|jest|vitest|mocha|tsc|typecheck|lint|build|go test|cargo test|npm (run )?test|pnpm (run )?test|yarn test)\b/i

/**
 * Runtime facts about which changes were followed by a check.
 *
 * This preserves the distinction the compaction must not lose: a check that
 * ran before a file changed does not verify the current file.
 *
 * @param {ReadonlyArray<object>} messages region messages in order.
 * @returns {string[]} one line per changed file, or an empty array.
 */
function buildVerificationState(messages) {
  const calls = []
  const results = new Map()
  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index]
    if (message.role === 'assistant') {
      for (const block of callBlocksOf(message)) {
        calls.push({ id: block.id, name: block.name, args: safeParse(block.arguments), index })
      }
    } else if (message.role === 'tool') {
      results.set(message.toolCallId, { isError: message.isError === true })
    }
  }

  const edits = new Map()
  const checks = []
  for (const call of calls) {
    const path = pathOf(call.args)
    if ((call.name === 'edit' || call.name === 'write') && path !== undefined) {
      edits.set(path, { index: call.index, name: call.name })
    }
    if (call.name === 'bash' || call.name === 'pwsh') {
      const command = String(call.args?.command ?? call.args?.cmd ?? '')
      if (!VERIFICATION_COMMAND.test(command)) continue
      checks.push({
        command: truncate(firstLine(command), 80),
        index: call.index,
        failed: results.get(call.id)?.isError === true,
      })
    }
  }

  const lines = []
  for (const [path, edit] of [...edits.entries()].slice(-MAX_SECTION_ITEMS.verification)) {
    const later = checks.filter((check) => check.index > edit.index)
    const latest = later.at(-1)
    const verified = later.some((check) => !check.failed)
    const tail =
      latest === undefined
        ? 'no check after that change'
        : `latest check \`${latest.command}\` at #${latest.index} → ${latest.failed ? 'failed' : 'passed'}`
    lines.push(
      `${path}: last ${edit.name} at #${edit.index}; ${tail}; verified after that change: ${verified ? 'yes' : 'no'}`,
    )
  }
  return lines
}

/**
 * Build one extractive checkpoint.
 *
 * @param {{ messages: ReadonlyArray<object> }} input replayed region messages.
 * @param {{ maxChars?: number, payload?: object }} options hard cap on checkpoint characters.
 * @returns {{ text: string, sourceBytes: number, budget: number }}
 */
export function buildCheckpoint(input, options = {}) {
  const messages = input.messages.filter((message) => message.role !== 'system')
  const sourceBytes = messages.reduce((total, message) => total + messageBytes(message), 0)
  if (messages.length === 0) return { text: '', sourceBytes, budget: 0 }

  const policy = resolvePayloadPolicy(options.payload)
  const maxChars = options.maxChars ?? policy.maxChars
  const isCheckpointSource = options.isCheckpointSource ?? (() => false)
  const budget = Math.min(maxChars, Math.max(600, Math.floor(sourceBytes * policy.sourceFraction)))
  const working =
    options.denoise === true
      ? applyDenoise(messages, options.denoiseRules ?? ALL_DENOISE_RULES).messages
      : messages

  const callNames = new Map()
  for (const message of working) {
    for (const block of callBlocksOf(message)) callNames.set(block.id, block.name)
  }

  const priorText = priorCheckpointText(working, isCheckpointSource)
  const sections = {
    prior: [],
    users: [],
    developers: [],
    errors: [],
    outputs: [],
    decisions: [],
    calls: [],
    files: [],
    workingset: workingsetSectionOf(working, options, priorText),
    verification: buildVerificationState(working),
  }
  const seenFiles = new Set()

  for (const message of working) {
    if (message.role === 'user') {
      const text = textOf(message).trim()
      if (text.length === 0) continue
      if (isCheckpointSource(message.source)) sections.prior.push(priorBody(text))
      else if (message.source?.kind === 'user') sections.users.push(text)
      continue
    }
    if (message.role === 'developer') {
      const text = textOf(message).trim()
      if (text.length > 0) sections.developers.push(text)
      continue
    }
    if (message.role === 'tool') {
      const text = textOf(message).trim()
      if (text.length === 0) continue
      const name = callNames.get(message.toolCallId) ?? 'tool'
      if (message.isError === true) sections.errors.push(`[${name}] ${text}`)
      else sections.outputs.push(`[${name}] ${text}`)
      continue
    }
    if (message.role === 'assistant') {
      const text = textOf(message).trim()
      if (text.length > 0) sections.decisions.push(text)
      for (const block of callBlocksOf(message)) {
        const args = safeParse(block.arguments)
        const path = pathOf(args)
        if (path !== undefined && !seenFiles.has(path)) {
          seenFiles.add(path)
          sections.files.push(`${path} (${block.name})`)
        }
        if (block.name === 'read' || block.name === 'write' || block.name === 'edit') {
          sections.calls.push(`${block.name} ${path ?? '(unknown path)'}`)
        } else if (block.name === 'bash' || block.name === 'pwsh') {
          sections.calls.push(`${block.name}: ${truncate(firstLine(args?.command ?? args?.cmd ?? ''), 160)}`)
        } else {
          sections.calls.push(`${block.name}(${truncate(block.arguments, 120)})`)
        }
      }
    }
  }

  // A region that no longer holds the prompt still has to carry it: the
  // previous checkpoint's control section is the copy that survives, and taking
  // it from there keeps the request independent of how much of the prior text
  // the prior section's own cap allows.
  if (sections.users.length === 0) {
    const carried = carriedControl(priorText)
    if (carried.length > 0) sections.users.push(carried)
  }

  const trimmed = {
    prior: sections.prior
      .slice(-MAX_SECTION_ITEMS.prior)
      .map((item) => collapsePriorEcho(item, policy.priorEchoDepth)),
    users: pickEnds(sections.users, MAX_SECTION_ITEMS.users),
    developers: sections.developers.slice(-MAX_SECTION_ITEMS.developers),
    errors: sections.errors.slice(-MAX_SECTION_ITEMS.errors),
    outputs: sections.outputs.slice(-(policy.outputsItems === 0 ? 0 : Math.max(1, policy.outputsItems))),
    decisions: sections.decisions.slice(-MAX_SECTION_ITEMS.decisions),
    calls: sections.calls.slice(-MAX_SECTION_ITEMS.calls),
    files: sections.files.slice(-MAX_SECTION_ITEMS.files),
    workingset: sections.workingset.slice(-MAX_SECTION_ITEMS.workingset),
    verification: sections.verification.slice(-MAX_SECTION_ITEMS.verification),
  }

  const controlItemCap = controlItemCapOf(options)
  const controlCap = Number.isFinite(controlItemCap) ? controlItemCap : null
  const controlSourceBytes = trimmed.users.reduce((total, item) => total + byteLength(String(item)), 0)

  const present = Object.keys(trimmed).filter((key) => trimmed[key].length > 0)
  const weightOf = (key) => sectionWeight(key, policy, SECTION_WEIGHT)
  const totalWeight = present.reduce((sum, key) => sum + weightOf(key), 0)
  if (present.length === 0) {
    return {
      text: '(no retained detail)',
      sourceBytes,
      budget,
      control: { sourceBytes: 0, keptBytes: 0, cap: controlCap },
    }
  }

  const bodies = {}
  let controlKeptBytes = 0
  // The control section is mandatory: it may not fall below what the cap
  // allows just because the weighted split gave it a smaller share. The floor
  // is bounded by the budget, so the section can never overrun it.
  const controlFloor = Math.min(
    budget,
    Number.isFinite(controlItemCap) ? controlItemCap : controlSourceBytes,
  )
  for (const key of present) {
    const share = Math.max(80, Math.floor((budget * weightOf(key)) / totalWeight))
    const allocation =
      key === 'users'
        ? Math.max(share, controlFloor)
        : key === 'workingset'
          ? Math.max(share, workingsetFloor(budget, trimmed.workingset))
          : share
    const cap = key === 'users' ? controlItemCap : payloadItemCap(key, policy, SECTION_ITEM_CAP)
    const body = takeWithin(trimmed[key], allocation, cap)
    if (body.length === 0) continue
    if (key === 'users') controlKeptBytes = byteLength(body)
    bodies[key] = `${HEADINGS[key]}\n${body}`
  }

  // Rendered in value order, not declaration order: the previous checkpoint's
  // echo used to sit at the head of every checkpoint, so a truncation kept the
  // echo and cut the content behind it.
  const parts = RENDER_ORDER.map((key) => bodies[key]).filter((part) => part !== undefined)

  let text = parts.join('\n\n')
  if (byteLength(text) > budget) text = `${truncateBytes(text, budget)}\n[checkpoint truncated]`
  return {
    text,
    sourceBytes,
    budget,
    control: { sourceBytes: controlSourceBytes, keptBytes: controlKeptBytes, cap: controlCap },
  }
}

/**
 * Build a checkpoint from model-selected verbatim quotes.
 *
 * The model returns exact strings; the engine keeps only quotes that appear
 * byte-for-byte in the region. Control messages and prior checkpoints are
 * mandatory. Returns null when no quote matched, so the caller can fall back.
 *
 * @param {{ messages: ReadonlyArray<object> }} input replayed region messages.
 * @param {{ quotes?: readonly string[], spans?: readonly object[], fragments?: readonly object[], ranges?: readonly object[], facts?: readonly object[], toolText?: boolean, isCheckpointSource?: (source: unknown) => boolean, maxChars?: number }} options
 * @returns {{ text: string, sourceBytes: number, budget: number, selectedCount: number } | null}
 */
export function buildSelectiveCheckpoint(input, options = {}) {
  const messages = input.messages.filter((message) => message.role !== 'system')
  const sourceBytes = messages.reduce((total, message) => total + messageBytes(message), 0)
  if (messages.length === 0) return null

  const isCheckpointSource = options.isCheckpointSource ?? (() => false)
  const policy = resolvePayloadPolicy(options.payload)
  const maxChars = options.maxChars ?? policy.maxChars
  const budget = Math.min(maxChars, Math.max(600, Math.floor(sourceBytes * policy.sourceFraction)))

  const callNames = new Map()
  for (const message of messages) {
    for (const block of callBlocksOf(message)) callNames.set(block.id, block.name)
  }

  const prior = []
  const control = []
  for (const message of messages) {
    const text = textOf(message).trim()
    if (text.length === 0) continue
    if (message.role === 'user') {
      if (isCheckpointSource(message.source)) prior.push(priorBody(text))
      else if (message.source?.kind === 'user') control.push(text)
      continue
    }
    if (message.role === 'developer') control.push(text)
  }

  const matched = []
  let droppedAmbiguous = 0
  for (const raw of options.quotes ?? []) {
    const quote = String(raw ?? '').trim()
    if (quote.length < 8 || quote.length > policy.quoteMaxChars) continue

    // Bind to bytes only when the quote occurs exactly once in the region.
    // A repeated quote has no unique source, so it is dropped rather than
    // guessed.
    const occurrences = []
    for (let index = 0; index < messages.length; index += 1) {
      const body = textOf(messages[index])
      let from = 0
      for (;;) {
        const at = body.indexOf(quote, from)
        if (at === -1) break
        occurrences.push(index)
        from = at + quote.length
      }
    }
    if (occurrences.length !== 1) {
      droppedAmbiguous += 1
      continue
    }

    const index = occurrences[0]
    const message = messages[index]
    // Control messages and prior checkpoints are already mandatory; quoting
    // them again would duplicate the same bytes.
    if (message.role === 'developer') continue
    if (message.role === 'user' && (message.source?.kind === 'user' || isCheckpointSource(message.source))) {
      continue
    }
    const role =
      message.role === 'tool'
        ? `tool:${callNames.get(message.toolCallId) ?? 'tool'}`
        : message.role
    matched.push({ text: quote, role, index })
  }

  // Addressed selections are engine-side: a span or an exact fragment inside a
  // named message. The engine resolves the address and recomputes the digest,
  // so the selected text cannot drift from the bytes it claims.
  const known = new Map(
    messages.map((message, index) => [
      `m${index + 1}`,
      {
        kind: 'message',
        payload: message.content,
        // Same projection the selection transcript showed, so a span or a line
        // range addresses exactly the bytes the model saw.
        text: messageText(message, { toolText: options.toolText === true }),
        ...(message.toolCallId === undefined ? {} : { callId: message.toolCallId }),
      },
    ]),
  )
  let droppedExcerpts = 0
  const addressed = [
    ...(options.spans ?? []).map((item) => ({ ...item, addressed: 'span' })),
    ...(options.fragments ?? []).map((item) => ({ ...item, addressed: 'fragment' })),
  ]
  // Line ranges arrive as addresses, not text: resolve them into spans here so
  // the rest of the pipeline cannot tell them apart from a model-written span.
  for (const item of options.ranges ?? []) {
    const index = sourceIndex(item.source, messages.length)
    if (index === -1) {
      droppedExcerpts += 1
      continue
    }
    const body = messageText(messages[index], { toolText: options.toolText === true })
    const span = lineSpan(body, item.from, item.to)
    if (span === null) {
      droppedExcerpts += 1
      continue
    }
    addressed.push({ source: `m${index + 1}`, start: span.start, end: span.end, addressed: 'span' })
  }
  for (const item of addressed) {
    const index = sourceIndex(item.source, messages.length)
    if (index === -1) {
      droppedExcerpts += 1
      continue
    }
    const message = messages[index]
    if (message.role === 'developer') continue
    if (message.role === 'user' && (message.source?.kind === 'user' || isCheckpointSource(message.source))) {
      continue
    }
    let resolved
    try {
      resolved = resolveExcerpt(known, {
        source: `m${index + 1}`,
        ...(item.path === undefined ? {} : { path: item.path }),
        ...(item.addressed === 'fragment'
          ? { fragment: item.text }
          : { start: item.start, end: item.end }),
        ...(item.sha256 === undefined ? {} : { sha256: item.sha256 }),
      })
    } catch {
      droppedExcerpts += 1
      continue
    }
    if (resolved.text.trim().length < 8) continue
    const role =
      message.role === 'tool'
        ? `tool:${callNames.get(message.toolCallId) ?? 'tool'}`
        : message.role
    matched.push({ text: resolved.text, role, index })
  }

  const deduped = matched.filter(
    (item) =>
      !matched.some(
        (other) =>
          other !== item && other.text.includes(item.text) && other.text.length > item.text.length,
      ),
  )
  deduped.sort((left, right) => left.index - right.index)
  if (deduped.length === 0) return null

  const selected = deduped.map((item, index) => ({ ...item, ref: `s${index + 1}` }))
  const refByQuote = new Map(selected.map((item) => [item.text, item.ref]))

  const judgments = []
  const keptFacts = []
  let droppedFacts = 0
  for (const fact of options.facts ?? []) {
    const text = typeof fact?.text === 'string' ? fact.text.trim() : ''
    if (text.length === 0 || text.length > policy.factMaxChars) {
      droppedFacts += 1
      continue
    }
    const refs = Array.isArray(fact.sources)
      ? fact.sources
          .map((source) => refByQuote.get(String(source).trim()))
          .filter((ref) => ref !== undefined)
      : []
    if (refs.length === 0) {
      droppedFacts += 1
      continue
    }
    judgments.push(`${text} ${[...new Set(refs)].map((ref) => `[${ref}]`).join('')}`)
    keptFacts.push({ text, sources: [...new Set(refs)] })
  }

  const priorText = priorCheckpointText(messages, isCheckpointSource)
  // Same carry-forward as the deterministic build: the prompt outlives the
  // region, and the previous checkpoint's control section is where it lives.
  if (control.length === 0) {
    const carried = carriedControl(priorText)
    if (carried.length > 0) control.push(carried)
  }
  const sections = {
    prior: prior
      .slice(-MAX_SECTION_ITEMS.prior)
      .map((item) => collapsePriorEcho(item, policy.priorEchoDepth)),
    control: pickEnds(control, MAX_SECTION_ITEMS.users),
    selected: selected.map((item) => `[${item.ref}] [${item.role}] ${item.text}`),
    judgments: judgments.slice(0, MAX_SECTION_ITEMS.judgments),
    workingset: workingsetSectionOf(messages, options, priorText),
    verification: buildVerificationState(messages),
    outputs: outputsSectionOf(messages, options, selected, callNames),
  }
  const weights = {
    prior: 0.25,
    control: 0.35,
    selected: 0.4,
    judgments: 0.2,
    workingset: 0.45,
    verification: 0.2,
    outputs: 0.2,
  }
  const present = Object.keys(sections).filter((key) => sections[key].length > 0)
  const totalWeight = present.reduce((sum, key) => sum + weights[key], 0)

  const controlItemCap = controlItemCapOf(options)
  const caps = {
    prior: policy.priorItemCap,
    control: controlItemCap,
    selected: policy.selectedItemCap,
    judgments: policy.judgmentItemCap,
    workingset: policy.workingsetItemCap,
    verification: policy.verificationItemCap,
    outputs: Number.isInteger(options.outputs?.cap) ? options.outputs.cap : policy.outputsItemCap,
  }
  const controlSourceBytes = control.reduce((total, item) => total + byteLength(String(item)), 0)
  // Same mandatory-floor rule as the deterministic builder: the control section
  // is allocated at least what its cap allows, bounded by the budget.
  const controlFloor = Math.min(
    budget,
    Number.isFinite(controlItemCap) ? controlItemCap : controlSourceBytes,
  )
  const sectionBytes = {}
  let controlKeptBytes = 0
  // Sections are filled in value order against one shrinking budget. Each keeps
  // its weighted share, but never more than what earlier sections left over:
  // allocating every section a share of the same budget made the join overflow,
  // and the trailing sections (working set, verification) were cut away by the
  // final truncation — exactly when the budget was tight enough to need them.
  // The prior echo is filled after the working set and the selection: it is a
  // copy of the previous checkpoint, and filling it first is what let it eat the
  // budget those two sections exist to spend.
  const fillOrder = ['control', 'selected', 'workingset', 'prior', 'judgments', 'verification', 'outputs']
  const bodies = {}
  let remaining = budget
  for (const key of fillOrder) {
    if (!present.includes(key)) continue
    const share = Math.max(80, Math.floor((budget * weights[key]) / totalWeight))
    const wanted =
      // Filled last and takes whatever is left: it exists to stop the checkpoint
      // sitting at a fifth of its budget while the model re-runs commands.
      key === 'outputs'
        ? remaining
        : key === 'control'
          ? Math.max(share, controlFloor)
          : key === 'workingset'
            ? Math.max(share, workingsetFloor(budget, sections[key]))
            : share
    const allocation = Math.min(wanted, remaining)
    if (allocation <= 24) continue
    const body = takeWithin(sections[key], allocation, caps[key] ?? 400)
    if (body.length === 0) continue
    if (key === 'control') controlKeptBytes = byteLength(body)
    sectionBytes[key] = byteLength(body)
    bodies[key] = `${HEADINGS[key]}\n${body}`
    remaining -= byteLength(bodies[key]) + 2
  }

  const parts = RENDER_ORDER.map((key) => bodies[key]).filter((part) => part !== undefined)
  let text = parts.join('\n\n')
  if (byteLength(text) > budget) text = `${truncateBytes(text, budget)}\n[checkpoint truncated]`
  return {
    text,
    sourceBytes,
    budget,
    selectedCount: selected.length,
    droppedAmbiguous,
    droppedExcerpts,
    judgmentCount: judgments.length,
    keptFacts,
    droppedFacts,
    control: {
      sourceBytes: controlSourceBytes,
      keptBytes: controlKeptBytes,
      cap: Number.isFinite(controlItemCap) ? controlItemCap : null,
    },
    payload: {
      budget,
      chars: byteLength(text),
      truncated: byteLength(text) >= budget,
      priorDepth: policy.priorEchoDepth,
      sections: sectionBytes,
    },
  }
}

/**
 * Lower bound of the mandatory content a checkpoint must carry.
 *
 * Computed before any model call: when control messages and prior checkpoints
 * already exceed the view budget, no safe checkpoint exists and the caller
 * must stop instead of asking a model.
 *
 * @param {{ messages: ReadonlyArray<object> }} input replayed region messages.
 * @param {{ isCheckpointSource?: (source: unknown) => boolean, maxChars?: number }} options
 * @returns {{ sourceBytes: number, budget: number, mandatoryBytes: number }}
 */
export function mandatoryLowerBound(input, options = {}) {
  const messages = input.messages.filter((message) => message.role !== 'system')
  const sourceBytes = messages.reduce((total, message) => total + messageBytes(message), 0)
  const policy = resolvePayloadPolicy(options.payload)
  const maxChars = options.maxChars ?? policy.maxChars
  const budget = Math.min(maxChars, Math.max(600, Math.floor(sourceBytes * policy.sourceFraction)))
  const isCheckpointSource = options.isCheckpointSource ?? (() => false)

  const prior = []
  const control = []
  for (const message of messages) {
    const text = textOf(message).trim()
    if (text.length === 0) continue
    if (message.role === 'user') {
      if (isCheckpointSource(message.source)) prior.push(priorBody(text))
      else if (message.source?.kind === 'user') control.push(text)
      continue
    }
    if (message.role === 'developer') control.push(text)
  }

  const priorText = takeWithin(prior.slice(-MAX_SECTION_ITEMS.prior), 2400, 1200)
  const controlText = takeWithin(pickEnds(control, MAX_SECTION_ITEMS.users), 6400, 800)
  return {
    sourceBytes,
    budget,
    mandatoryBytes: priorText.length + controlText.length + 120,
  }
}

/**
 * Map an addressed-selection source to a region index.
 *
 * Sources are one-based (`m1` is the first retained message), matching the
 * `s1..sN` reference style used for selected quotes.
 *
 * @param {unknown} source `m<index>` or a one-based number.
 * @param {number} total number of retained messages.
 * @returns {number} zero-based index, or -1 when the address is invalid.
 */
function sourceIndex(source, total) {
  const raw = typeof source === 'number' ? source : /^m(\d+)$/.exec(String(source ?? ''))?.[1]
  const value = Number(raw)
  return Number.isInteger(value) && value >= 1 && value <= total ? value - 1 : -1
}

/**
 * Keep the first two items plus the newest items, so the original request
 * survives even when later turns dominate the region.
 *
 * @param {readonly string[]} items section items, oldest first.
 * @param {number} max maximum items retained.
 * @returns {string[]} retained items in original order.
 */
function pickEnds(items, max) {  if (items.length <= max) return [...items]
  return [...items.slice(0, 2), ...items.slice(-(max - 2))]
}

/**
 * Keep items in order until their combined text reaches the allocation.
 *
 * @param {readonly string[]} items section items, oldest first.
 * @param {number} allocation byte budget for this section.
 * @returns {string} bullet list body.
 */
function takeWithin(items, allocation, itemCap = 400) {
  const lines = []
  let used = 0
  for (const item of items) {
    const remaining = allocation - used
    if (remaining <= 24) break
    const normalized = String(item).replace(/\r?\n/g, '\n  ')
    const line = `- ${truncateBytes(normalized, Math.min(itemCap, Math.max(24, remaining - 4)))}`
    lines.push(line)
    used += byteLength(line) + 1
  }
  return lines.join('\n')
}

