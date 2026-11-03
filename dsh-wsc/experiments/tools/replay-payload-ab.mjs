// Offline A/B for the checkpoint payload policy.
//
// The trial sessions record every shadowed region, so the exact input a
// compaction saw can be rebuilt without spending a model call. This replays
// those regions through the deterministic builder under two payload policies and
// reports what the payload knobs actually buy:
//
//   node tools/replay-payload-ab.mjs <session.jsonl.zstd> [more sessions…]
//
// Per compaction it prints the checkpoint size and the share of the shadowed
// region's distinctive lines that survive verbatim. That share is the causal
// variable behind the post-compaction re-read loop: a checkpoint that keeps
// little forces the agent to read the same files again.
import { buildCheckpoint } from '../../lib/checkpoint.js'
import { readSessionEvents } from './read-session.mjs'
import { regionMessages } from './region.mjs'

/** Bypass policy: bigger payload, wider acceptance, no nested prior echo, more tool output. */
const BYPASS = {
  sourceFraction: 0.6,
  maxChars: 40000,
  quoteMaxChars: 4000,
  selectedItemCap: 4000,
  factMaxChars: 800,
  judgmentItemCap: 800,
  verificationItemCap: 500,
  priorItemCap: 3000,
  priorEchoDepth: 1,
  outputsItemCap: 1200,
  outputsItems: 24,
  outputsWeight: 0.5,
}

const files = process.argv.slice(2)
if (files.length === 0) {
  console.error('usage: node tools/replay-payload-ab.mjs <session.jsonl.zstd> [more sessions…]')
  process.exit(2)
}

const MIN_LINE = 30

/** Distinctive source lines: long enough to be meaningful, deduplicated. */
const distinctiveLines = (messages) => {
  const lines = new Set()
  for (const message of messages) {
    const parts = Array.isArray(message.content) ? message.content : []
    for (const part of parts) {
      if (part?.type !== 'text' || typeof part.text !== 'string') continue
      for (const line of part.text.split('\n')) {
        const trimmed = line.trim()
        if (trimmed.length >= MIN_LINE) lines.add(trimmed)
      }
    }
  }
  return lines
}

const retained = (lines, checkpointText) => {
  let kept = 0
  for (const line of lines) if (checkpointText.includes(line)) kept += 1
  return kept
}

const rows = []
for (const file of files) {
  const events = readSessionEvents(file)
  const bySeq = new Map(events.map((event) => [event.seq, event]))
  const summaries = events.filter((event) => event.type === 'compaction/summary')
  for (const [index, summary] of summaries.entries()) {
    const seqs = summary.data.shadowedSeqs
    if (!Array.isArray(seqs) || seqs.length === 0) continue
    const messages = regionMessages(events, seqs)
    if (messages.length === 0) continue
    const lines = distinctiveLines(messages)
    if (lines.size === 0) continue
    const shipped = buildCheckpoint({ messages })
    const bypass = buildCheckpoint({ messages }, { payload: BYPASS })
    const recordedText = (Array.isArray(summary.data.summary) ? summary.data.summary : [])
      .filter((part) => part?.type === 'text' && typeof part.text === 'string')
      .map((part) => part.text)
      .join('\n')
    rows.push({
      session: file.split(/[\\/]/).slice(-2)[0],
      compaction: index + 1,
      sourceBytes: shipped.sourceBytes,
      lines: lines.size,
      toolMessages: messages.filter((message) => message.role === 'tool').length,
      shipped: {
        bytes: Buffer.byteLength(shipped.text, 'utf8'),
        budget: shipped.budget,
        recall: Number((retained(lines, shipped.text) / lines.size).toFixed(3)),
      },
      bypass: {
        bytes: Buffer.byteLength(bypass.text, 'utf8'),
        budget: bypass.budget,
        recall: Number((retained(lines, bypass.text) / lines.size).toFixed(3)),
      },
      recorded: {
        provider: summary.data.provider ?? null,
        bytes: Buffer.byteLength(recordedText, 'utf8'),
        recall: Number((retained(lines, recordedText) / lines.size).toFixed(3)),
      },
    })
  }
}

const mean = (values) => (values.length === 0 ? 0 : values.reduce((a, b) => a + b, 0) / values.length)
const shippedRecall = mean(rows.map((row) => row.shipped.recall))
const bypassRecall = mean(rows.map((row) => row.bypass.recall))
const recordedRecall = mean(rows.map((row) => row.recorded.recall))
const shippedBytes = mean(rows.map((row) => row.shipped.bytes))
const bypassBytes = mean(rows.map((row) => row.bypass.bytes))
const recordedBytes = mean(rows.map((row) => row.recorded.bytes))

process.stdout.write(
  `${JSON.stringify(
    {
      compactions: rows.length,
      shipped: { meanBytes: Math.round(shippedBytes), meanRecall: Number(shippedRecall.toFixed(3)) },
      bypass: { meanBytes: Math.round(bypassBytes), meanRecall: Number(bypassRecall.toFixed(3)) },
      recorded: { meanBytes: Math.round(recordedBytes), meanRecall: Number(recordedRecall.toFixed(3)) },
      delta: {
        bytes: Math.round(bypassBytes - shippedBytes),
        recall: Number((bypassRecall - shippedRecall).toFixed(3)),
      },
      rows,
    },
    null,
    2,
  )}\n`,
)
