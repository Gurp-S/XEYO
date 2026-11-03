import { mkdtemp, mkdir, writeFile, readFile, readdir, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { build, parseArgs } from './lib/build.js';
import { startWatch } from './lib/watch.js';

let fails = 0;
const ok = (cond, msg) => { console.log(`${cond ? 'PASS' : 'FAIL'} ${msg}`); if (!cond) fails++; };
const exists = async (p) => { try { await stat(p); return true; } catch { return false; } };

async function tree(dir, base = dir) {
  const out = {};
  for (const e of await readdir(dir, { withFileTypes: true })) {
    const abs = path.join(dir, e.name);
    if (e.isDirectory()) Object.assign(out, await tree(abs, base));
    else out[path.relative(base, abs).replaceAll('\\', '/')] = (await readFile(abs)).toString('base64');
  }
  return out;
}

const root = await mkdtemp(path.join(tmpdir(), 'mb-'));
const src = path.join(root, 'src');
const out = path.join(root, 'out');
const manifest = path.join(root, 'build-manifest.json');
await mkdir(path.join(src, 'styles'), { recursive: true });
await mkdir(path.join(src, 'img'), { recursive: true });

await writeFile(path.join(src, 'a.js'), 'export const a = 1;\n\n\n');
await writeFile(path.join(src, 'b.js'), 'export const b = 2;\n');
await writeFile(path.join(src, 'img/logo.png'), Buffer.from([1, 2, 3, 4]));
await writeFile(path.join(src, 'styles/site.css'), 'body{background:url(../img/logo.png)}\n');
await writeFile(path.join(src, 'base.json'), JSON.stringify({ x: 1, y: 2 }));
await writeFile(path.join(src, 'data.json'), JSON.stringify({ extends: './base.json', y: 3 }));
await writeFile(path.join(src, 'notes.txt'), 'raw bytes\n');

const opts = parseArgs(['--src', 'src', '--out', 'out', '--manifest', 'build-manifest.json', '--concurrency', '4']);

// 1. cold build
const r1 = await build(opts, root);
ok(r1.built.length === 7 && r1.skipped.length === 0, `cold build built 7 (${r1.built.length})`);
const m1 = JSON.parse(await readFile(manifest, 'utf8'));
ok(m1.version === 2, 'manifest version 2');
const css = await readFile(path.join(out, 'styles/site.css'), 'utf8');
const hashed = /url\(([^)]+)\)/.exec(css)[1];
ok(/^logo\.[0-9a-f]{8}\.png$/.test(hashed), `css url hashed: ${hashed}`);
ok(await exists(path.join(out, 'styles', hashed)), 'hashed asset emitted next to css');
ok((await readFile(path.join(out, 'a.js'), 'utf8')) === 'export const a = 1;\n//# build ' + (await readFile(path.join(out, 'a.js'), 'utf8')).match(/build ([0-9a-f]{8})/)[1] + '\n', 'js trimmed + build line + newline');
ok((await readFile(path.join(out, 'data.json'), 'utf8')) === '{\n  "x": 1,\n  "y": 3\n}\n', 'json extends merged, own keys win, extends dropped');
ok((await readFile(path.join(out, 'notes.txt'), 'utf8')) === 'raw bytes\n', 'other file copied byte for byte');
ok(Array.isArray(m1.files['styles/site.css'].deps['img/logo.png']) === false && m1.files['styles/site.css'].deps['img/logo.png'], 'css records asset dependency');
ok(m1.files['data.json'].deps['base.json'], 'json records extends dependency');

// 2. no-op rebuild
const r2 = await build(opts, root);
ok(r2.built.length === 0 && r2.skipped.length === 7 && r2.removed.length === 0, `no-op rebuild skipped 7 (built ${r2.built.length})`);

// 3. asset change invalidates the stylesheet
await writeFile(path.join(src, 'img/logo.png'), Buffer.from([9, 9, 9]));
const r3 = await build(opts, root);
ok(r3.built.includes('styles/site.css'), `asset change rebuilds css (built: ${r3.built.join(',')})`);
const css3 = await readFile(path.join(out, 'styles/site.css'), 'utf8');
const hashed3 = /url\(([^)]+)\)/.exec(css3)[1];
ok(hashed3 !== hashed, `css url changed: ${hashed3}`);
ok(await exists(path.join(out, 'styles', hashed3)), 'new hashed asset emitted');
ok(!(await exists(path.join(out, 'styles', hashed))), 'stale hashed asset removed');

// 4. base.json change invalidates data.json
await writeFile(path.join(src, 'base.json'), JSON.stringify({ x: 7, y: 2 }));
const r4 = await build(opts, root);
ok(r4.built.includes('data.json'), 'extends change rebuilds data.json');
ok((await readFile(path.join(out, 'data.json'), 'utf8')).includes('"x": 7'), 'merged value refreshed');

// 5. deletion removes output + entry
await rm(path.join(src, 'a.js'));
const r5 = await build(opts, root);
const m5 = JSON.parse(await readFile(manifest, 'utf8'));
ok(!(await exists(path.join(out, 'a.js'))), 'deleted source output removed');
ok(!m5.files['a.js'], 'deleted source manifest entry removed');

// 6. determinism: incremental state vs full rebuild from scratch
const incremental = await tree(out);
const manifestIncremental = await readFile(manifest, 'utf8');
await rm(out, { recursive: true, force: true });
await rm(manifest, { force: true });
const r6 = await build(opts, root);
ok(r6.built.length === 6, `full rebuild built 6 (${r6.built.length})`);
const full = await tree(out);
ok(JSON.stringify(incremental) === JSON.stringify(full), 'incremental output bytes == full rebuild bytes');
ok(manifestIncremental === (await readFile(manifest, 'utf8')), 'manifest identical after full rebuild');

// 7. dry-run writes nothing
await rm(out, { recursive: true, force: true });
await rm(manifest, { force: true });
const dry = parseArgs(['--src', 'src', '--out', 'out', '--manifest', 'build-manifest.json', '--dry-run']);
const r7 = await build(dry, root);
ok(r7.built.length === 6 && !(await exists(out)) && !(await exists(manifest)), 'dry-run plans but writes nothing');

// 8. concurrency does not change bytes
const c1 = parseArgs(['--src', 'src', '--out', 'out1', '--manifest', 'm1.json', '--concurrency', '1']);
const c8 = parseArgs(['--src', 'src', '--out', 'out8', '--manifest', 'm8.json', '--concurrency', '8']);
await build(c1, root);
await build(c8, root);
ok(JSON.stringify(await tree(path.join(root, 'out1'))) === JSON.stringify(await tree(path.join(root, 'out8'))), 'concurrency 1 vs 8 produce identical bytes');

// 9. watch: one rebuild per change, ignored self-writes, no overlap
const wroot = await mkdtemp(path.join(tmpdir(), 'mbw-'));
await mkdir(path.join(wroot, 'src'), { recursive: true });
await writeFile(path.join(wroot, 'src/w.js'), 'export const w = 1;\n');
const wopts = parseArgs(['--src', 'src', '--out', 'src/out', '--manifest', 'build-manifest.json']);
const reports = [];
const watcher = startWatch(wopts, { cwd: wroot, onReport: (r) => reports.push(r), debounceMs: 20 });
await new Promise((r) => setTimeout(r, 300));
ok(reports.length === 1, `watch initial build ran once (${reports.length})`);
await writeFile(path.join(wroot, 'src/w.js'), 'export const w = 2;\n');
await new Promise((r) => setTimeout(r, 400));
ok(reports.length === 2, `watch rebuilt once per change (${reports.length})`);
ok(reports[1].built.includes('w.js'), 'watch rebuild saw the changed file');
await writeFile(path.join(wroot, 'src/extra.js'), 'export const e = 1;\n');
await new Promise((r) => setTimeout(r, 400));
ok(reports.length === 3 && reports[2].built.includes('extra.js'), `watch picked up an added file (${reports.length})`);
watcher.close();
const after = reports.length;
await writeFile(path.join(wroot, 'src/w.js'), 'export const w = 3;\n');
await new Promise((r) => setTimeout(r, 300));
ok(reports.length === after, 'closed watcher stops rebuilding');

console.log(fails === 0 ? 'ALL PASS' : `${fails} FAILURES`);
process.exitCode = fails === 0 ? 0 : 1;
