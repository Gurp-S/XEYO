const fs = require('fs');
const path = require('path');
const { zstdDecompressSync } = require('node:zlib');

const ZSTD_MAGIC = 4247762216;

// replicate scanZstdFrames from dsh lib (maxFrames=1)
function scanFirstFrame(buffer) {
  let offset = 0;
  while (offset < buffer.length) {
    const start = offset;
    if (buffer.length - offset < 4) return { first: null, torn: start };
    if (buffer.readUInt32LE(offset) !== ZSTD_MAGIC) throw new Error(`invalid frame magic at byte ${offset}`);
    offset += 4;
    if (offset === buffer.length) return { first: null, torn: start };
    const descriptor = buffer.readUInt8(offset);
    offset += 1;
    if ((descriptor & 24) !== 0) throw new Error(`reserved frame-header bit at byte ${offset-1}`);
    const contentSizeFlag = descriptor >>> 6;
    const singleSegment = (descriptor & 32) !== 0;
    const checksum = (descriptor & 4) !== 0;
    const dictionaryFlag = descriptor & 3;
    const dictionaryBytes = dictionaryFlag === 3 ? 4 : dictionaryFlag;
    const contentSizeBytes = contentSizeFlag === 0 ? (singleSegment ? 1 : 0) : (1 << contentSizeFlag);
    const remainingHeaderBytes = (singleSegment ? 0 : 1) + dictionaryBytes + contentSizeBytes;
    if (buffer.length - offset < remainingHeaderBytes) return { first: null, torn: start };
    offset += remainingHeaderBytes;
    for (;;) {
      if (buffer.length - offset < 3) return { first: null, torn: start };
      const blockHeader = buffer.readUIntLE(offset, 3);
      offset += 3;
      const lastBlock = (blockHeader & 1) !== 0;
      const blockType = (blockHeader >>> 1) & 3;
      const blockSize = blockHeader >>> 3;
      if (blockType === 3) throw new Error(`reserved block type at byte ${offset-3}`);
      const payloadBytes = blockType === 1 ? 1 : blockSize;
      if (buffer.length - offset < payloadBytes) return { first: null, torn: start };
      offset += payloadBytes;
      if (lastBlock) break;
    }
    if (checksum) {
      if (buffer.length - offset < 4) return { first: null, torn: start };
      offset += 4;
    }
    return { first: { start, end: offset }, torn: null };
  }
  return { first: null, torn: null };
}

// replicate assertZstdHeaderFrame
function assertHeader(plaintext) {
  if (plaintext.length === 0 || plaintext.indexOf(10) !== plaintext.length - 1) {
    return `first frame not exactly one header line (len=${plaintext.length}, lastByte=${bufferHexTail(plaintext)})`;
  }
  return null;
}
function bufferHexTail(b) {
  const tail = Buffer.from(b.slice(-12));
  return tail.toString('hex') + ' (' + JSON.stringify(tail.toString('utf8').replace(/\r/g,'\\r')) + ')';
}

function diagnose(file) {
  try {
    const stat = fs.statSync(file);
    const buf = fs.readFileSync(file);
    const { first, torn } = scanFirstFrame(buf);
    if (!first) return { file, size: stat.size, status: 'NO-FIRST-FRAME', torn };
    let plaintext;
    try {
      plaintext = zstdDecompressSync(buf.subarray(first.start, first.end));
    } catch (e) {
      return { file, size: stat.size, status: 'DECOMPRESS-FAIL', firstLen: first.end - first.start, err: String(e.message).slice(0,120) };
    }
    const h = assertHeader(plaintext);
    return { file, size: stat.size, status: h ? 'CORRUPT-HEADER' : 'OK', firstLen: first.end - first.start, tail: bufferHexTail(plaintext) };
  } catch (e) {
    return { file, size: -1, status: 'READ-ERR', err: String(e.message).slice(0,120) };
  }
}

const root = process.argv[2];
if (!root) { console.log('usage: node _dsh_scan.js <sessions_root>'); process.exit(1); }
const files = [];
(function walk(d){
  for (const ent of fs.readdirSync(d, { withFileTypes: true })) {
    const fp = path.join(d, ent.name);
    if (ent.isDirectory()) walk(fp);
    else if (ent.name.endsWith('.zstd')) files.push(fp);
  }
})(root);
console.log(`scanning ${files.length} .zstd files under ${root}\n`);
let corrupt = 0, ok = 0, other = 0;
for (const f of files) {
  const r = diagnose(f);
  if (r.status === 'OK') { ok++; }
  else { other++; }
  if (r.status !== 'OK') {
    console.log(`${r.status}  ${path.basename(path.dirname(f))}/${path.basename(f)}  size=${r.size}${r.tail?(' tail='+r.tail):''}${r.err?(' err='+r.err):''}`);
  }
}
console.log(`\nDONE  OK=${ok}  BAD=${other}`);
