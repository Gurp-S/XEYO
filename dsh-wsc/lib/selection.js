/**
 * Selection surface for the model-selected checkpoint.
 *
 * The model addresses the region by name, so the request shows a numbered
 * transcript (`[m<n> <role>]`) and the engine resolves the same numbering.
 * Quotes are verified against the original bytes; the labels exist only inside
 * the selection request.
 */

import { isToolResult, messageText } from './projection.js'

export { messageText }

/** Above this size the numbered projection is skipped and spans are not honoured. */
export const MAX_TRANSCRIPT_CHARS = 400_000

/** Auxiliary instruction for model-selected, verbatim-quote checkpoints. */
export const SELECTION_INSTRUCTION = [
  'The conversation above is a numbered transcript: each message is labelled [m<number> <role>].',
  'Select the parts of it that a later model needs to continue the work.',
  'Return only a JSON object of this exact shape:',
  '{"keep": ["<exact quote>", ...], "spans": [{"source": "m<number>", "start": <integer>, "end": <integer>}], "fragments": [{"source": "m<number>", "text": "<exact fragment>"}], "facts": [{"text": "<short judgment>", "sources": ["<exact quote from keep>"]}]}',
  'Rules:',
  '- keep, spans and fragments are three ways to select; any of them may be used, together or alone.',
  '- Every quote in keep must appear verbatim in the transcript, without its [m<number> <role>] label. Copy the exact characters; do not paraphrase, translate, or fix formatting.',
  '- A span selects that message\'s characters from start (inclusive) to end (exclusive), counted in Unicode code points from 0. A fragment selects the exact text of that message and is used only when it occurs exactly once there.',
  '- Each quote is between 8 and 1200 characters; each span covers at most 1200 code points. Select at most 60 quotes, 40 spans and 40 fragments.',
  '- Prefer: explicit user requests and corrections, decisions and their reasons, exact error strings, file paths, commands, version identifiers, and results later work depends on.',
  '- facts are optional. Each fact is one short judgment (at most 300 characters) and must cite at least one kept quote verbatim in sources.',
  '- Do not state anything the cited quotes do not support. Omit a fact rather than guessing.',
  '- Do not add commentary, headings, or explanations.',
  '- Output only the JSON object.',
].join('\n')

/**
 * Instruction for line-addressed selection.
 *
 * Every excerpt the model writes out costs output tokens, and output tokens are
 * what a compaction mostly spends: a verbatim-quote checkpoint averages ~3.4k
 * output tokens for ~550 tokens of kept text. The cheaper contract asks for
 * addresses instead of content — the engine copies the bytes.
 */
export const SELECTION_INSTRUCTION_RANGES = [
  'The conversation above is a numbered transcript: each message is labelled [m<number> <role>] and its body is numbered by line (the `N| ` prefix is not part of the text).',
  'Select the parts of it that a later model needs to continue the work.',
  'Return only a JSON object of this exact shape:',
  '{"keep": [{"source": "m<number>", "lines": [<first>, <last>]}, ...], "facts": [{"text": "<short judgment>", "sources": ["m<number>"]}]}',
  'Rules:',
  '- lines are 1-based and inclusive. The engine copies those lines verbatim, so never repeat their text in your answer.',
  '- Select at most 40 ranges, each at most 60 lines.',
  '- Prefer: explicit user requests and corrections, decisions and their reasons, exact error strings, file paths, commands, version identifiers, and results later work depends on.',
  '- facts are optional. Each fact is one short judgment (at most 200 characters) and cites at least one selected message number in sources. At most 6 facts; the copied lines already carry the rest.',
  '- Do not state anything the selected lines do not support. Omit a fact rather than guessing.',
  '- Do not add commentary, headings, or explanations.',
  '- Output only the JSON object.',
].join('\n')

/** @param {unknown} value parsed selection object @returns {object[]} usable facts. */
const parseFacts = (value) =>
  Array.isArray(value?.facts)
    ? value.facts
        .filter(
          (fact) =>
            fact !== null &&
            typeof fact === 'object' &&
            typeof fact.text === 'string' &&
            Array.isArray(fact.sources),
        )
        .slice(0, 20)
        .map((fact) => ({
          text: fact.text,
          sources: fact.sources.filter((source) => typeof source === 'string'),
        }))
    : []

/** Above this many lines one range stops being a pointer and becomes a copy. */
const MAX_RANGE_LINES = 60

/**
 * Parse a line-addressed selection.
 *
 * @param {string} text raw model output, optionally fenced.
 * @returns {{ ranges: object[], facts: object[] }}
 */
export function parseSelectionRanges(text) {
  const isSource = (value) => typeof value === 'string' || Number.isInteger(value)
  let body = String(text ?? '').trim()
  const fence = /^```(?:json)?\s*([\s\S]*?)\s*```$/i.exec(body)
  if (fence !== null) body = fence[1].trim()
  try {
    const value = JSON.parse(body)
    const keep = Array.isArray(value?.keep) ? value.keep : []
    const ranges = keep
      .filter(
        (item) =>
          item !== null &&
          typeof item === 'object' &&
          isSource(item.source) &&
          Array.isArray(item.lines) &&
          item.lines.length === 2 &&
          Number.isInteger(item.lines[0]) &&
          Number.isInteger(item.lines[1]) &&
          item.lines[0] >= 1 &&
          item.lines[1] >= item.lines[0],
      )
      .slice(0, 40)
      .map((item) => ({
        source: item.source,
        from: item.lines[0],
        to: Math.min(item.lines[1], item.lines[0] + MAX_RANGE_LINES - 1),
      }))
    return { ranges, facts: parseFacts(value).slice(0, 6) }
  } catch {
    return { ranges: [], facts: [] }
  }
}

/**
 * Project the region as a numbered transcript for the selection request.
 *
 * Numbering matches the engine's address resolution: system messages are not
 * part of the region, and a message keeps its number even when it contributes
 * no text. When the projection would be too large to send, it is not built and
 * addressed selections are refused rather than resolved against a transcript
 * the model never saw.
 *
 * The projection also reports what it contained, so the ledger can show how much
 * of the selection surface is tool output and how much of the region never
 * reached the model at all.
 *
 * @param {readonly object[]} messages region messages.
 * @param {{ toolText?: boolean, lineNumbers?: boolean }} [options] projection options.
 * @returns {{ text: string, addressable: boolean, messages: number, empty: number, tools: number, toolChars: number, chars: number }}
 */
export function numberedTranscript(messages, options = {}) {
  const retained = messages.filter((message) => message.role !== 'system')
  const parts = []
  let total = 0
  let empty = 0
  let tools = 0
  let toolChars = 0
  for (let index = 0; index < retained.length; index += 1) {
    const message = retained[index]
    const body = messageText(message, options)
    if (body.trim().length === 0) {
      empty += 1
      continue
    }
    const carriesTool = message.role === 'tool' || isToolResult(message)
    const role = carriesTool ? 'tool-result' : message.role
    // Line numbers exist only so the model can address a range; they are never
    // part of the text the engine copies back.
    const shown =
      options.lineNumbers === true
        ? body
            .split('\n')
            .map((line, number) => `${number + 1}| ${line}`)
            .join('\n')
        : body
    const entry = `[m${index + 1} ${role}]\n${shown}`
    if (carriesTool) {
      tools += 1
      toolChars += body.length
    }
    total += entry.length
    if (total > MAX_TRANSCRIPT_CHARS) {
      return { text: '', addressable: false, messages: retained.length, empty, tools, toolChars, chars: total }
    }
    parts.push(entry)
  }
  return {
    text: parts.join('\n\n'),
    addressable: true,
    messages: retained.length,
    empty,
    tools,
    toolChars,
    chars: total,
  }
}

/**
 * Parse the model's selection object.
 *
 * Malformed entries are dropped rather than repaired: a selection the engine
 * cannot verify is not a selection.
 *
 * @param {string} text raw model output, optionally fenced.
 * @returns {{ quotes: string[], spans: object[], fragments: object[], facts: object[] }}
 */
export function parseSelection(text) {
  const isSource = (value) => typeof value === 'string' || Number.isInteger(value)
  let body = String(text ?? '').trim()
  const fence = /^```(?:json)?\s*([\s\S]*?)\s*```$/i.exec(body)
  if (fence !== null) body = fence[1].trim()
  try {
    const value = JSON.parse(body)
    const keep = Array.isArray(value?.keep) ? value.keep : []
    const quotes = keep
      .filter((quote) => typeof quote === 'string' && quote.trim().length >= 8)
      .slice(0, 60)
    const spans = Array.isArray(value?.spans)
      ? value.spans
          .filter(
            (span) =>
              span !== null &&
              typeof span === 'object' &&
              isSource(span.source) &&
              Number.isInteger(span.start) &&
              Number.isInteger(span.end) &&
              span.start >= 0 &&
              span.end > span.start,
          )
          .slice(0, 40)
          .map((span) => ({
            source: span.source,
            start: span.start,
            end: span.end,
            ...(Array.isArray(span.path) ? { path: span.path } : {}),
          }))
      : []
    const fragments = Array.isArray(value?.fragments)
      ? value.fragments
          .filter(
            (item) =>
              item !== null &&
              typeof item === 'object' &&
              isSource(item.source) &&
              typeof item.text === 'string' &&
              item.text.trim().length >= 4,
          )
          .slice(0, 40)
          .map((item) => ({
            source: item.source,
            text: item.text,
            ...(Array.isArray(item.path) ? { path: item.path } : {}),
          }))
      : []
    const facts = parseFacts(value)
    return { quotes, spans, fragments, facts }
  } catch {
    return { quotes: [], spans: [], fragments: [], facts: [] }
  }
}
