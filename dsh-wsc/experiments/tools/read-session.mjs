// Read a DSH session log (`session.jsonl.zstd`).
//
// The store appends one zstd frame per write, so the file is a concatenation of
// frames rather than a single stream; `zstdDecompressSync` only decodes the
// first one. This helper splits on the zstd magic number, decodes every frame,
// and exposes the events as JSONL.
import { readFileSync } from 'node:fs'
import { zstdDecompressSync } from 'node:zlib'

const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])

export function readSessionEvents(file) {
  const buffer = readFileSync(file)
  const starts = []
  for (let index = 0; index < buffer.length - 4; index += 1) {
    if (buffer[index] === MAGIC[0] && buffer.compare(MAGIC, 0, 4, index, index + 4) === 0) starts.push(index)
  }
  if (starts.length === 0) throw new Error(`${file}: no zstd frame found`)

  const events = []
  for (let index = 0; index < starts.length; index += 1) {
    const end = index + 1 < starts.length ? starts[index + 1] : buffer.length
    let text
    try {
      text = zstdDecompressSync(buffer.subarray(starts[index], end)).toString('utf8')
    } catch {
      continue
    }
    for (const line of text.split('\n')) {
      const trimmed = line.trim()
      if (trimmed === '') continue
      try {
        events.push(JSON.parse(trimmed))
      } catch {
        // A frame can end mid-line when the store rotates; skip the fragment.
      }
    }
  }
  return events
}

if (process.argv[1]?.endsWith('read-session.mjs')) {
  const [file, mode = 'summary'] = process.argv.slice(2)
  if (file === undefined) {
    console.error('usage: node read-session.mjs <session.jsonl.zstd> [summary|jsonl|usage]')
    process.exit(2)
  }
  const events = readSessionEvents(file)
  if (mode === 'jsonl') {
    for (const event of events) console.log(JSON.stringify(event))
  } else if (mode === 'usage' || mode === 'steps') {
    // A step's usage appears twice: once as a `usage` chunk and once on the
    // assembled assistant message. Count each source separately, then prefer
    // the chunk source so a request is never billed twice.
    const chunked = []
    const messaged = []
    for (const event of events) {
      const chunk = event.data?.chunk?.usage
      const message = event.data?.message?.usage
      if (chunk !== undefined) chunked.push({ step: event.data?.step, usage: chunk })
      if (message !== undefined) messaged.push({ step: event.data?.step, usage: message })
    }
    const rows = chunked.length > 0 ? chunked : messaged
    if (mode === 'steps') {
      console.log(JSON.stringify(rows.map((row) => ({
        step: row.step,
        input: row.usage.inputTokens ?? row.usage.promptTokens ?? 0,
        output: row.usage.outputTokens ?? row.usage.completionTokens ?? 0,
      }))))
    } else {
      let input = 0
      let output = 0
      let cached = 0
      for (const row of rows) {
        input += row.usage.inputTokens ?? row.usage.promptTokens ?? 0
        output += row.usage.outputTokens ?? row.usage.completionTokens ?? 0
        cached += row.usage.cachedInputTokens ?? 0
      }
      console.log(JSON.stringify({ events: events.length, requests: rows.length, input, output, cached }))
    }
  } else {
    const types = {}
    for (const event of events) types[event.type ?? '?'] = (types[event.type ?? '?'] ?? 0) + 1
    console.log(JSON.stringify({ events: events.length, types }))
  }
}
