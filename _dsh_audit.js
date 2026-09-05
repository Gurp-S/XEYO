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

function* walk(d) {
  for (const ent of fs.readdirSync(d, { withFileTypes: true })) {
    const fp = path.join(d, ent.name);
    if (ent.isDirectory()) yield* walk(fp);
    else if (ent.name.endsWith('.zstd')) yield { file: fp, mtime: fs.statSync(fp).mtimeMs };
  }
}

// usage: node _dsh_audit.js <sessions_root> <out.json>
const root = process.argv[2];
const outFile = process.argv[3];

// file -> { sessions: {sessId: {ops, first, last}}, }
const byFile = {};

for (const { file, mtime } of walk(root)) {
  const sess = path.basename(path.dirname(file));
  let buf;
  try { buf = fs.readFileSync(file); } catch { continue; }
  let txt = '';
  try {
    for (const { start, end } of framesAll(buf)) {
      txt += zstdDecompressSync(buf.subarray(start, end)).toString('utf8');
    }
  } catch { continue; }
  const ls = txt.split('\n');
  for (const l of ls) {
    if (!l.startsWith('{')) continue;
    let o;
    try { o = JSON.parse(l); } catch { continue; }
    if (o.type !== 'tool/call') continue;
    const d = o.data || {};
    const name = (d.name || '').toLowerCase();
    if (!/edit|write|patch/.test(name)) continue;
    let args;
    try { args = JSON.parse(d.arguments || '{}'); } catch { continue; }
    const fp = (args.file_path || '').replace(/\\/g, '/');
    if (!fp) continue;
    const key = fp.replace(/^.*?\/XenYon code\//, '').replace(/^D:\/lea\/XenYon code\//, '');
    const rec = byFile[key] || (byFile[key] = { sessions: {} });
    const s = rec.sessions[sess] || (rec.sessions[sess] = { ops: 0, first: 0, last: 0 });
    s.ops += 1;
    s.first = s.first || o.time || 0;
    s.last = Math.max(s.last, o.time || 0);
  }
}

fs.writeFileSync(outFile, JSON.stringify(byFile), 'utf8');
const entries = Object.entries(byFile).sort((a, b) => Object.keys(b[1].sessions).length - Object.keys(a[1].sessions).length);
console.log('files edited by sessions: ' + entries.length);
for (const [file, rec] of entries.slice(0, 60)) {
  const sessN = Object.keys(rec.sessions).length;
  const opsN = Object.values(rec.sessions).reduce((x, y) => x + y.ops, 0);
  const last = new Date(Math.max(...Object.values(rec.sessions).map(s => s.last))).toISOString().slice(0, 16).replace('T', ' ');
  console.log(String(sessN).padStart(3) + ' sessions, ' + String(opsN).padStart(4) + ' ops, last ' + last + '  ' + file);
}
