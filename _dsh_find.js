const fs = require('fs');
const path = require('path');
const { zstdDecompressSync } = require('node:zlib');

const ZSTD_MAGIC = 4247762216;

function* walk(d) {
  for (const ent of fs.readdirSync(d, { withFileTypes: true })) {
    const fp = path.join(d, ent.name);
    if (ent.isDirectory()) yield* walk(fp);
    else if (ent.name.endsWith('.zstd')) yield fp;
  }
}

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

const KEY = /ComposerQuickMenu|CommandPalette|技能面板|加号|斜杠|slashManifest|handleComposerSlash|技能菜单|quickmenu|技能栏|\/面板|\/斜杠/i;

const root = process.argv[2];
const results = [];
for (const f of walk(root)) {
  let buf;
  try { buf = fs.readFileSync(f); } catch { continue; }
  let lines = [];
  try {
    let text = '';
    for (const { start, end } of framesAll(buf)) {
      text += zstdDecompressSync(buf.subarray(start, end)).toString('utf8');
    }
    lines = text.split('\n');
  } catch (e) { continue; }
  if (!lines.length) continue;
  const hits = [];
  lines.forEach((l, i) => { if (KEY.test(l)) hits.push(i + 1); });
  if (hits.length) {
    const ctx = hits.slice(0, 5).map(n => {
      const l = lines[n - 1] || '';
      const m = l.match(KEY);
      const idx = m ? m.index : 0;
      return 'L' + n + ': ' + l.slice(Math.max(0, idx - 70), idx + 170).replace(/\s+/g, ' ').trim();
    });
    results.push({ file: f, hits: hits.length, ctx });
  }
}
results.sort((a, b) => b.hits - a.hits);
console.log('matched files: ' + results.length + '\n');
for (const r of results.slice(0, 30)) {
  console.log('=== ' + r.file.replace(root + path.sep, '').replaceAll(path.sep, '/') + '  hits=' + r.hits);
  for (const c of r.ctx) console.log('   ' + c);
}
