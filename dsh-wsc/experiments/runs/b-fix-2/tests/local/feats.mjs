// Feature checks (post-fix contract): dry-run, determinism, manifest shape, watch.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = path.resolve(process.argv[2]);
const mod = await import(pathToFileURL(path.join(root, 'lib', 'build.js')).href);
const OPTS = { src: 'src', out: 'out', manifest: 'build-manifest.json', concurrency: 4 };
const TMP = path.join(root, '.feat-tmp');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let seq = 0;
function fresh() {
  const dir = path.join(TMP, `s${seq += 1}`);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  fs.cpSync(path.join(root, 'src'), path.join(dir, 'src'), { recursive: true });
  return dir;
}
const rd = (d, p) => { try { return fs.readFileSync(path.join(d, p), 'utf8'); } catch { return null; } };
const ls = (d, p) => {
  const base = path.join(d, p);
  if (!fs.existsSync(base)) return [];
  const out = [];
  (function walk(dir, rel) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const r = rel ? `${rel}/${e.name}` : e.name;
      if (e.isDirectory()) walk(path.join(dir, e.name), r); else out.push(r);
    }
  })(base, '');
  return out.sort();
};
const res = [];
const check = (name, ok, detail = '') => res.push({ name, ok, detail });

// F1 dry-run writes nothing
{
  const d = fresh();
  const r = await mod.build({ ...OPTS, dryRun: true }, d);
  const wrote = ls(d, 'out').length || fs.existsSync(path.join(d, 'build-manifest.json'));
  check('F1 dry-run writes nothing', !wrote && r && typeof r === 'object', wrote ? 'files written' : '');
  fs.rmSync(d, { recursive: true, force: true });
}

// F2 determinism across fresh dirs
{
  const a = fresh(), b = fresh();
  await mod.build(OPTS, a); await mod.build(OPTS, b);
  const fa = ls(a, 'out'), fb = ls(b, 'out');
  let diff = JSON.stringify(fa) === JSON.stringify(fb) ? '' : 'file list differs';
  for (const f of fa) if (!diff && rd(a, `out/${f}`) !== rd(b, `out/${f}`)) diff = `content differs: ${f}`;
  check('F2 deterministic output', !diff, diff);
  fs.rmSync(a, { recursive: true, force: true }); fs.rmSync(b, { recursive: true, force: true });
}

// F3 manifest shape covers all sources
{
  const d = fresh();
  await mod.build(OPTS, d);
  const man = JSON.parse(rd(d, 'build-manifest.json') || 'null');
  const src = ls(d, 'src').filter((f) => !f.endsWith('.json') || true);
  const keys = man && man.files ? Object.keys(man.files) : [];
  const missing = src.filter((f) => !keys.includes(f));
  check('F3 manifest lists every source', !!man && keys.length > 0 && missing.length === 0,
    !man ? 'manifest unreadable' : missing.length ? `missing: ${missing.join(',')}` : '');
  fs.rmSync(d, { recursive: true, force: true });
}

// F4 watch rebuilds after change
if (typeof mod.watch !== 'function') {
  check('F4 watch rebuilds on change', false, 'no watch export');
} else {
  const d = fresh();
  const reports = [];
  const h = await mod.watch(OPTS, d, (r) => reports.push(r));
  const first = rd(d, 'out/b.js');
  const before = fs.readFileSync(path.join(d, 'src/b.js'), 'utf8');
  fs.writeFileSync(path.join(d, 'src/b.js'), before.replace('B1', 'WWW'));
  const t0 = Date.now();
  while (Date.now() - t0 < 4000 && reports.length < 2) await sleep(50);
  const second = rd(d, 'out/b.js');
  check('F4 watch rebuilds on change', reports.length >= 2 && first !== second && !!second && second.includes('WWW'),
    `reports=${reports.length} changed=${first !== second} before=${JSON.stringify(before)}`);
  if (typeof h === 'function') await h();
  else if (h && typeof h.close === 'function') await h.close();
  else if (h && typeof h.stop === 'function') await h.stop();
  fs.rmSync(d, { recursive: true, force: true });
}

fs.rmSync(TMP, { recursive: true, force: true });
for (const r of res) console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.detail ? `  <- ${r.detail}` : ''}`);
const bad = res.filter((r) => !r.ok).length;
console.log(`\n${root}\n${res.length - bad}/${res.length} pass`);
process.exit(bad ? 1 : 0);
