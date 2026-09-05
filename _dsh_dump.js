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

function decompress(file) {
  let buf = fs.readFileSync(file);
  let text = '';
  for (const { start, end } of framesAll(buf)) {
    text += zstdDecompressSync(buf.subarray(start, end)).toString('utf8');
  }
  return text;
}

const sessionDir = process.argv[2];
const filter = process.argv[3] ? new RegExp(process.argv[3], 'i') : null;
const onlyRole = process.argv[4] || '';
const lines = decompress(sessionDir).split('\n');
console.error('lines=' + lines.length + ' filter=' + (filter ? String(filter) : '(none)') + ' role=' + onlyRole);

function textOf(block) {
  if (!block) return '';
  if (block.type === 'text') return block.text || '';
  if (block.type === 'reasoning') return '[reasoning] ' + (block.text || '');
  if (block.type === 'tool_use') return '[tool] ' + (block.name || '') + ' ' + JSON.stringify(block.input || {}).slice(0, 200);
  if (block.type === 'tool_result') {
    const c = block.content;
    if (typeof c === 'string') return '[tool_result] ' + c.slice(0, 200);
    if (Array.isArray(c)) return '[tool_result] ' + JSON.stringify(c).slice(0, 200);
    return '[tool_result] ' + String(c).slice(0, 200);
  }
  return '[' + (block.type || '?') + '] ' + String(block.text || JSON.stringify(block) || '').slice(0, 200);
}

let shown = 0;
lines.forEach((l, i) => {
  if (!l.trim() || !l.startsWith('{')) return;
  let o;
  try { o = JSON.parse(l); } catch { return; }
  let role = '';
  let content = null;
  if (o.type === 'user/message') { role = 'user'; content = o.data && o.data.content; }
  else if (o.type === 'assistant/message') { role = 'assistant'; content = o.data && o.data.message && o.data.message.content; }
  else if (o.type === 'tool/call') { role = 'tool'; content = [o.data]; }
  else return;
  if (onlyRole && role !== onlyRole) return;
  if (role === 'user') {
    const txt = Array.isArray(content) ? content.map(c => textOf(c)).join('\n') : String(content || '');
    if (filter && !filter.test(txt)) return;
    console.log(`\n===== L${i + 1} [user] =====\n${txt.slice(0, 1200)}`);
    shown++;
  } else if (role === 'assistant') {
    const txt = Array.isArray(content) ? content.filter(c => c.type === 'text').map(c => c.text || '').join('\n') : '';
    if (!txt) return;
    if (filter && !filter.test(txt)) return;
    console.log(`\n----- L${i + 1} [assistant] -----\n${txt.slice(0, 800)}`);
    shown++;
  } else if (role === 'tool') {
    const d = (content && content[0]) || {};
    const name = d.name || '';
    if (!/edit|write|patch/i.test(name)) return;
    const inp = String(d.input || '');
    if (filter && !filter.test(inp)) return;
    console.log(`\n----- L${i + 1} [tool:${name}] -----\n${inp.slice(0, 500)}`);
    shown++;
  }
  if (shown > 100) { console.log('\n[truncated at 100 messages]'); process.exit(0); }
});
