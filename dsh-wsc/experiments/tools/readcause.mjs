import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import zlib from 'node:zlib'

const M = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])
function frames(b) {
  const s = []
  for (let i = 0; i + 4 <= b.length; i++) if (b.compare(M, 0, 4, i, i + 4) === 0) s.push(i)
  const o = []
  for (let k = 0; k < s.length; k++) {
    const e = k + 1 < s.length ? s[k + 1] : b.length
    try { o.push(zlib.zstdDecompressSync(b.subarray(s[k], e)).toString('utf8')) } catch {}
  }
  return o
}
const base = path.join(os.homedir(), '.dsh', 'sessions')
function load(run) {
  const dir = fs.readdirSync(base).find(d => d.includes('runs-' + run + '--'))
  const walk = p => {
    for (const e of fs.readdirSync(p, { withFileTypes: true })) {
      const q = path.join(p, e.name)
      if (e.isDirectory()) { const h = walk(q); if (h) return h } else if (e.name.endsWith('.zstd')) return q
    }
    return null
  }
  return frames(fs.readFileSync(walk(path.join(base, dir)))).join('').split(/\r?\n/)
    .filter(l => l.trim()).map(l => { try { return JSON.parse(l) } catch { return null } }).filter(Boolean)
}

for (const run of process.argv.slice(2)) {
  const ev = load(run)
  const txt = e => JSON.stringify(e.data || {})
  const results = ev.filter(e => e.type === 'tool/result')
  const miss = results.filter(e => /missing_read|no prior Read/i.test(txt(e)))
  const otherErr = results.filter(e => /"isError":true/.test(txt(e)))
  // reads grouped by compaction epoch
  let epoch = 0
  const perEpoch = []
  for (const e of ev) {
    if (e.type === 'compaction/end') { epoch++; continue }
    if (e.type === 'tool/call' && e.data.name === 'read') {
      perEpoch[epoch] = perEpoch[epoch] || []
      try { perEpoch[epoch].push(JSON.parse(e.data.arguments).file_path) } catch {}
    }
  }
  const dupPerEpoch = perEpoch.map((a, i) => 'e' + i + ':' + (a ? a.length : 0) + '/' + (a ? new Set(a).size : 0)).join(' ')
  console.log('== ' + run)
  console.log('  tool results=' + results.length + ' missing_read=' + miss.length + ' isError=' + otherErr.length)
  console.log('  sample miss: ' + (miss[0] ? txt(miss[0]).slice(0, 220) : '-'))
  console.log('  reads per epoch (calls/distinct): ' + dupPerEpoch)
}
