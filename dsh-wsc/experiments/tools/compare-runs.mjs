// Compare recorded runs: totals, tool mix, read attribution, and per-compaction
// detail (what each checkpoint actually carried).
//
//   node tools/compare-runs.mjs echo-d-1 echo-e-1 native-1 ...
//
// Reads ~/.dsh/sessions/*-runs-<name>--/session.jsonl.zstd and
// experiments/report/raw/<name>.json (written by trial.ps1).
import { readFileSync, writeFileSync, existsSync, readdirSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { readSessionEvents } from './read-session.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const exp = path.resolve(here, '..');
const sessions = path.join(homedir(), '.dsh', 'sessions');

const names = process.argv.slice(2);
if (names.length === 0) {
  process.stderr.write('usage: node tools/compare-runs.mjs <run-name>...\n');
  process.exit(2);
}

const sessionFileOf = (name) => {
  const dir = readdirSync(sessions).find((entry) => entry.includes(`-runs-${name}--`));
  if (dir === undefined) return undefined;
  const root = path.join(sessions, dir);
  const walk = (at) => {
    for (const entry of readdirSync(at, { withFileTypes: true })) {
      const next = path.join(at, entry.name);
      if (entry.isDirectory()) {
        const found = walk(next);
        if (found !== undefined) return found;
      } else if (entry.name === 'session.jsonl.zstd') {
        return next;
      }
    }
    return undefined;
  };
  return walk(root);
};

/** Split a checkpoint text into `{ heading, bytes }` blocks, in order. */
const sectionsOf = (text) => {
  const blocks = [];
  let current = null;
  for (const line of text.split('\n')) {
    if (line.startsWith('## ')) {
      if (current !== null) blocks.push(current);
      current = { heading: line.slice(3, 60), lines: [line] };
    } else if (current !== null) {
      current.lines.push(line);
    }
  }
  if (current !== null) blocks.push(current);
  return blocks.map((block) => ({
    heading: block.heading,
    bytes: Buffer.byteLength(block.lines.join('\n'), 'utf8'),
    items: block.lines.filter((line) => /^-\s|^\s+-\s/.test(line)).length,
  }));
};

const details = [];
for (const name of names) {
  const file = sessionFileOf(name);
  if (file === undefined) {
    details.push({ name, missing: 'session' });
    continue;
  }
  const events = readSessionEvents(file);
  const calls = {};
  const reads = [];
  const tools = {};
  let steps = 0;
  let compactions = 0;
  const perCompaction = [];
  let inputTokens = 0;
  let outputTokens = 0;

  for (const event of events) {
    if (event.type === 'step/start') steps += 1;
    if (event.type === 'tool/call') {
      const call = event.data ?? {};
      const tool = call.name ?? call.call?.name ?? '?';
      calls[tool] = (calls[tool] ?? 0) + 1;
      if (tool === 'read') {
        const args = call.arguments ?? call.call?.arguments;
        let parsed;
        try {
          parsed = typeof args === 'string' ? JSON.parse(args) : args;
        } catch {
          parsed = undefined;
        }
        const target = parsed?.file_path ?? parsed?.path
        if (typeof target === 'string') reads.push(target);
      }
    }
    if (event.type === 'tool/result') {
      const data = event.data ?? {};
      const tool = calls === undefined ? '?' : (data.name ?? 'result');
      tools[tool] = (tools[tool] ?? 0) + 1;
    }
    if (event.type === 'compaction/summary') {
      compactions += 1;
      const text = (event.data?.summary ?? [])
        .map((part) => (typeof part === 'string' ? part : (part?.text ?? '')))
        .join('\n');
      const shadowedTokens = event.data?.shadowedTokenCount ?? null;
      const bytes = Buffer.byteLength(text, 'utf8');
      perCompaction.push({
        index: compactions,
        shadowedTokens,
        bytes,
        // Bytes per shadowed token: how much of the region the checkpoint keeps.
        keepRatio: shadowedTokens === null ? null : Number((bytes / (shadowedTokens * 4)).toFixed(3)),
        sections: sectionsOf(text),
      });
    }
    if (event.type === 'assistant/message') {
      const usage = event.data?.usage ?? event.data?.message?.usage;
      if (usage !== undefined) {
        inputTokens += usage.inputTokens ?? usage.promptTokens ?? 0;
        outputTokens += usage.outputTokens ?? usage.completionTokens ?? 0;
      }
    }
  }

  const distinct = new Set(reads);
  const perFile = {};
  for (const read of reads) perFile[read] = (perFile[read] ?? 0) + 1;
  const hottest = Object.entries(perFile)
    .sort((left, right) => right[1] - left[1])
    .slice(0, 8)
    .map(([file, count]) => ({ file: path.basename(file), count }));

  const recordPath = path.join(exp, 'report', 'raw', `${name}.json`);
  const record = existsSync(recordPath) ? JSON.parse(readFileSync(recordPath, 'utf8')) : null;

  details.push({
    name,
    session: path.basename(path.dirname(file)),
    seconds: record?.seconds ?? null,
    score: record?.score ?? null,
    passed: record?.passed ?? null,
    total: record?.total ?? null,
    steps,
    calls: Object.values(calls).reduce((sum, count) => sum + count, 0),
    reads: reads.length,
    distinctFiles: distinct.size,
    readsPerFile: distinct.size === 0 ? null : Number((reads.length / distinct.size).toFixed(1)),
    compactions,
    compactionsPerStep: steps === 0 ? null : Number((compactions / steps).toFixed(2)),
    callsByTool: Object.fromEntries(Object.entries(calls).sort((left, right) => right[1] - left[1])),
    hottest,
    inputTokens: inputTokens === 0 ? null : inputTokens,
    outputTokens: outputTokens === 0 ? null : outputTokens,
    checkpointBytes: perCompaction.map((entry) => entry.bytes),
    perCompaction,
  });
}

const outJson = path.join(exp, 'report', 'raw', 'comparison.json');
writeFileSync(outJson, `${JSON.stringify(details, null, 2)}\n`, 'utf8');

const kb = (bytes) => `${(bytes / 1024).toFixed(1)}K`;
const rows = details.map((detail) => {
  if (detail.missing !== undefined) return `| ${detail.name} | missing | | | | | | |`;
  return [
    detail.name,
    detail.seconds === null ? '—' : `${detail.seconds}s`,
    detail.passed === null ? '—' : `${detail.passed}/${detail.total}`,
    detail.steps,
    detail.calls,
    detail.reads,
    detail.distinctFiles,
    detail.readsPerFile ?? '—',
    detail.compactions,
    detail.compactionsPerStep ?? '—',
    detail.checkpointBytes.length === 0 ? '—' : kb(detail.checkpointBytes.at(-1)),
  ].join(' | ');
});

const lines = [];
lines.push('| run | wall | tests | steps | calls | read | files | read/file | compactions | comp/step | last ckpt |');
lines.push('| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |');
for (const row of rows) lines.push(`| ${row} |`);
lines.push('');

for (const detail of details) {
  if (detail.missing !== undefined) continue;
  lines.push(`### ${detail.name}`);
  lines.push('');
  lines.push(`工具构成：${Object.entries(detail.callsByTool).map(([tool, count]) => `${tool}=${count}`).join('，')}`);
  if (detail.hottest.length > 0) {
    lines.push(`读得最多的文件：${detail.hottest.map((entry) => `${entry.file}×${entry.count}`).join('，')}`);
  }
  lines.push('');
  if (detail.perCompaction.length === 0) {
    lines.push('（无压缩）');
    lines.push('');
    continue;
  }
  lines.push('| # | 被压区域 tokens | checkpoint | 保留比 | 段构成 |');
  lines.push('| --- | --- | --- | --- | --- |');
  for (const entry of detail.perCompaction) {
    const sections = entry.sections
      .map((section) => `${section.heading.replace(/\s*\(.*$/, '')}=${section.bytes}B`)
      .join('，');
    lines.push(
      `| ${entry.index} | ${entry.shadowedTokens ?? '—'} | ${kb(entry.bytes)} | ${entry.keepRatio ?? '—'} | ${sections} |`,
    );
  }
  lines.push('');
}

writeFileSync(path.join(exp, 'report', 'COMPARISON.md'), `${lines.join('\n')}\n`, 'utf8');
process.stdout.write(`${lines.join('\n')}\n`);
