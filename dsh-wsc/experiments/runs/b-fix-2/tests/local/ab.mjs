// A/B harness: run the same defect scenarios against any mini-build repo root.
// usage: node tests/local/ab.mjs <repoRoot>
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = path.resolve(process.argv[2]);
const { build } = await import(pathToFileURL(path.join(root, 'lib', 'build.js')).href);
const OPTS = { src: 'src', out: 'out', manifest: 'build-manifest.json', concurrency: 4 };
const TMP = path.join(root, '.ab-tmp');
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
      if (e.isDirectory()) walk(path.join(dir, e.name), r);
      else out.push(r);
    }
  })(base, '');
  return out.sort();
};
const results = [];
async function scen(name, fn) {
  const dir = fresh();
  try {
    await build(OPTS, dir);
    const ok = await fn(dir);
    results.push({ name, ok: ok === true, detail: ok === true ? '' : String(ok) });
  } catch (e) {
    results.push({ name, ok: false, detail: `threw: ${e.message}` });
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

await scen('D1 url() dependency change rebuilds css', async (d) => {
  const css0 = rd(d, 'out/style.css');
  const files0 = ls(d, 'out');
  fs.appendFileSync(path.join(d, 'src/img.png'), 'XYZ');
  await build(OPTS, d);
  const css1 = rd(d, 'out/style.css');
  const files1 = ls(d, 'out');
  if (css0 === css1 && JSON.stringify(files0) === JSON.stringify(files1)) return 'out unchanged after img.png edit';
  return true;
});

await scen('D2 json extends dependency change', async (d) => {
  const j0 = rd(d, 'out/data.json');
  fs.writeFileSync(path.join(d, 'src/base.json'), JSON.stringify({ name: 'base2', level: 2 }, null, 2));
  await build(OPTS, d);
  const j1 = rd(d, 'out/data.json');
  if (j0 === j1) return 'out/data.json unchanged after base.json edit';
  return true;
});

await scen('D3 content change with restored mtime', async (d) => {
  const p = path.join(d, 'src/a.js');
  const st = fs.statSync(p);
  const a0 = rd(d, 'out/a.js');
  fs.writeFileSync(p, fs.readFileSync(p, 'utf8').replace("'AAA'", "'ZZZ'"));
  fs.utimesSync(p, st.atime, st.mtime);
  await build(OPTS, d);
  const a1 = rd(d, 'out/a.js');
  if (a0 === a1) return 'out/a.js stale (mtime-only check)';
  return true;
});

await scen('D4 deleted source pruned from out+manifest', async (d) => {
  fs.rmSync(path.join(d, 'src/extra.js'));
  await build(OPTS, d);
  const stale = ls(d, 'out').filter((f) => f.includes('extra'));
  if (stale.length) return `stale output kept: ${stale.join(',')}`;
  const man = JSON.parse(rd(d, 'build-manifest.json') || '{}');
  const keys = Object.keys(man.files || {}).filter((k) => k.includes('extra'));
  if (keys.length) return `manifest still lists ${keys.join(',')}`;
  return true;
});

await scen('D5 corrupt manifest recovers', async (d) => {
  const mp = path.join(d, 'build-manifest.json');
  const raw = fs.readFileSync(mp, 'utf8');
  fs.writeFileSync(mp, raw.slice(0, Math.floor(raw.length / 2)));
  await build(OPTS, d);
  const man = JSON.parse(fs.readFileSync(mp, 'utf8'));
  if (!man.files || !Object.keys(man.files).length) return 'manifest not healed';
  if (!rd(d, 'out/a.js')) return 'out/a.js missing after recovery';
  return true;
});

fs.rmSync(TMP, { recursive: true, force: true });
for (const r of results) console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.detail ? `  <- ${r.detail}` : ''}`);
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${root}\n${results.length - failed}/${results.length} pass`);
process.exitCode = failed ? 1 : 0;
