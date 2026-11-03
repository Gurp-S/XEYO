// Estimate the transcript size the model was carrying at each step, so the
// capacity for the real matrix can be placed inside the execution phase.
//
//   node tools/context-estimate.mjs <session.jsonl.zstd>
//
// Usage tokens are not usable here: the local proxy reports only the uncached
// part of the prompt, so the numbers are per-request deltas. Instead this
// counts the characters the harness actually sends back (assistant messages and
// tool results) and converts with a fixed chars-per-token ratio, anchored on the
// first request's reported prompt size.
import { readSessionEvents } from './read-session.mjs'

const CHARS_PER_TOKEN = 3.6
const file = process.argv[2]
if (file === undefined) {
  console.error('usage: node context-estimate.mjs <session.jsonl.zstd>')
  process.exit(2)
}

const events = readSessionEvents(file)
let base = 0
let chars = 0
const perStep = new Map()
let firstEdit = null
const edits = new Set(['write', 'edit', 'apply_patch', 'str_replace_editor'])

for (const event of events) {
  const data = event.data ?? {}
  if (event.type === 'assistant/chunk' && data.chunk?.usage && base === 0) {
    base = data.chunk.usage.inputTokens ?? 0
  }
  if (event.type === 'tool/call' && edits.has(data.name) && firstEdit === null) {
    firstEdit = data.step ?? null
  }
  if (event.type === 'assistant/message') {
    // Reasoning is generated but not sent back by the openai-completions API,
    // so it must not inflate the estimate.
    const content = (data.message?.content ?? []).filter((block) => block.type !== 'reasoning')
    chars += JSON.stringify(content).length
  } else if (event.type === 'tool/result') {
    chars += JSON.stringify(data.result ?? data.content ?? '').length
  } else {
    continue
  }
  const step = data.step ?? null
  if (step !== null) perStep.set(step, Math.round(base + chars / CHARS_PER_TOKEN))
}

const rows = [...perStep.entries()].sort((a, b) => a[0] - b[0])
const at = (step) => rows.filter(([s]) => s <= step).at(-1)?.[1] ?? base
console.log(JSON.stringify({
  base,
  firstEditStep: firstEdit,
  contextAtFirstEdit: firstEdit === null ? null : at(firstEdit),
  contextAtEnd: rows.at(-1)?.[1] ?? base,
  steps: rows.length,
  peak: Math.max(...rows.map(([, value]) => value)),
}))
