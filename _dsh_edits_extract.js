const fs = require('fs');
const path = require('path');
const { zstdDecompressSync } = require('node:zlib');

const ZSTD_MAGIC = 4247762216;

function framesAll(buf) {
  const out = [];
  let offset = 0;
  for (;;) {
    if (buf.length - offset < 4) break;
    if (buf.readUInt32LE(offset) !== ZSTD_MAGIC) break;
    const start = offset;
    offset += 4;
    if (offset === buf.length) break;
    const descriptor = buf.readUInt8(offset);
    offset += 1;
    if ((descriptor & 24) !== 0) break;
    const contentSizeFlag = descriptor >>> 6;
    const singleSegment = (descriptor & 32) !== 0;
    const checksum = (descriptor & 4) !== 0;
    const dictionaryFlag = descriptor & 3;
    const dictionaryBytes = dictionaryFlag === 3 ? 4 : dictionaryFlag;
    const contentSizeBytes = contentSizeFlag === 0 ? (singleSegment ? 1 : 0) : (1 << contentSizeFlag);
    const remainingHeaderBytes = (singleSegment ? 0 : 1) + dictionaryBytes + contentSizeBytes;
    if (buf.length - offset < remainingHeaderBytes) break;
    offset += remainingHeaderBytes;
    let ok = false;
    for (;;) {
      if (buf.length - offset < 3) break;
      const blockHeader = buf.readUIntLE(offset, 3);
      offset += 3;
      const lastBlock = (blockHeader & 1) !== 0;
      const blockType = (blockHeader >>> 1) & 3;
      const blockSize = blockHeader >>> 3;
      if (blockType === 3) break;
      const payloadBytes = blockType === 1 ? 1 : blockSize;
      if (buf.length - offset < payloadBytes) break;
      offset += payloadBytes;
      if (lastBlock) { ok = true; break; }
    }
    if (!ok) break;
    if (checksum) {
      if (buf.length - offset < 4) break;
      offset += 4;
    }
    out.push({ start, end: offset });
  }
  return out;
}

// usage: node _dsh_edits_extract.js <session.jsonl.zstd> <out.json>
const sessionFile = process.argv[2];
const outFile = process.argv[3];

const buf = fs.readFileSync(sessionFile);
let txt = '';
for (const { start, end } of framesAll(buf)) {
  txt += zstdDecompressSync(buf.subarray(start, end)).toString('utf8');
}
const ls = txt.split('\n');

const ops = [];
for (let i = 0; i < ls.length; i++) {
  const l = ls[i];
  if (!l.startsWith('{')) continue;
  let o;
  try { o = JSON.parse(l); } catch { continue; }
  if (o.type !== 'tool/call') continue;
  const d = o.data || {};
  const name = (d.name || '').toLowerCase();
  if (!/edit|write|patch/.test(name)) continue;
  let args;
  try { args = JSON.parse(d.arguments || '{}'); } catch { continue; }
  ops.push({ line: i + 1, seq: o.seq, time: o.time, name, file: args.file_path || '', old: args.old_string || '', new: args.new_string || '', replace_all: !!args.replace_all, content: args.content || '' });
}

fs.writeFileSync(outFile, JSON.stringify(ops, null, 1), 'utf8');

const byFile = {};
for (const op of ops) {
  const k = op.file.replace(/\\/g, '/');
  byFile[k] = (byFile[k] || 0) + 1;
}
console.log('total edit ops: ' + ops.length);
const keys = Object.keys(byFile).sort();
for (const k of keys) {
  console.log((byFile[k] + '').padStart(3) + '  ' + k);
}
