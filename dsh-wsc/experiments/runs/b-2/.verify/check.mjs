import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { build } from '../lib/build.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const sha = (b) => crypto.createHash('sha1').update(b).digest('hex').slice(0, 8);

const results = [];
async function check(name, fn) {
  try {
    const detail = await fn();
    results.push({ name, ok: true, detail: detail ?? '' });
  } catch (e) {
    results.push({ name, ok: false, detail: e.message });
  }
}
function eq(actual, expected, label) {
  if (actual !== expected) throw new Error(`${label}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
}
function ok(cond, label) {
  if (!cond) throw new Error(label);
}
function mk(files) {
  const dir = fs.mkdtempSync(path.join(process.env.TEMP ?? '/tmp', 'mb-'));
  for (const [rel, content] of Object.entries(files)) {
    const p = path.join(dir, 'src', rel);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, content);
  }
  return dir;
}
const run = (dir) => build({ src: path.join(dir, 'src'), out: path.join(dir, 'out'), manifest: path.join(dir, 'm.json') });
const rd = (dir, rel) => fs.readFileSync(path.join(dir, 'out', rel));
const rds = (dir, rel) => rd(dir, rel).toString('utf8');
const exists = (dir, rel) => fs.existsSync(path.join(dir, 'out', rel));
const manifest = (dir) => JSON.parse(fs.readFileSync(path.join(dir, 'm.json'), 'utf8'));
function listOut(dir) {
  const base = path.join(dir, 'out');
  if (!fs.existsSync(base)) return [];
  const acc = [];
  (function walk(d) {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p);
      else acc.push(path.relative(base, p).split(path.sep).join('/'));
    }
  })(base);
  return acc.sort();
}

await check('js: banner + trimmed trailing ws', async () => {
  const d = mk({ 'a.js': 'let x = 1;   \n\n\nconst y = 2;\t\n' });
  await run(d);
  const src = 'let x = 1;   \n\n\nconst y = 2;\t\n';
  eq(rds(d, 'a.js'), `let x = 1;\n\n\nconst y = 2;\n//# build ${sha(src)}\n`, 'body');
});

await check('mjs treated like js', async () => {
  const d = mk({ 'a.mjs': 'export const a = 1;\n' });
  await run(d);
  ok(rds(d, 'a.mjs').startsWith('export const a = 1;\n//# build '), `got ${JSON.stringify(rds(d, 'a.mjs'))}`);
});

await check('css: url() rewritten to hashed asset name', async () => {
  const d = mk({ 'style.css': '.a{background:url(./img/logo.png)}\n', 'img/logo.png': Buffer.from([1, 2, 3, 4]) });
  await run(d);
  const name = `logo.${sha(Buffer.from([1, 2, 3, 4]))}.png`;
  eq(rds(d, 'style.css'), `.a{background:url(${name})}\n`, 'css text');
});

await check('css: asset lives next to the css output', async () => {
  const d = mk({ 'sub/style.css': '.a{background:url(../img/logo.png)}\n', 'img/logo.png': Buffer.from([9, 9]) });
  await run(d);
  const name = `logo.${sha(Buffer.from([9, 9]))}.png`;
  ok(exists(d, `sub/${name}`), `asset not next to css: out=${JSON.stringify(listOut(d))}`);
});

await check('css: data: and http(s): urls untouched', async () => {
  const d = mk({ 'style.css': '.a{background:url(data:image/png;base64,AAA)}\n.b{background:url(https://x.test/y.png)}\n' });
  await run(d);
  const css = rds(d, 'style.css');
  ok(css.includes('url(data:image/png;base64,AAA)'), 'data url rewritten');
  ok(css.includes('url(https://x.test/y.png)'), 'http url rewritten');
});

await check('css: url() with quotes and spaces', async () => {
  const d = mk({ 's.css': ".a{background:url('./i.png')}\n.b{background:url( \"./i.png\" )}\n", 'i.png': Buffer.from([5]) });
  await run(d);
  const name = `i.${sha(Buffer.from([5]))}.png`;
  const css = rds(d, 's.css');
  ok(css.includes(`url(${name})`) && !css.includes("'./i.png'"), `quotes not handled: ${css}`);
});

await check('json: extends merged, own keys win, extends dropped', async () => {
  const d = mk({ 'base.json': '{"a":1,"b":2}', 'child.json': '{"extends":"./base.json","b":3}' });
  await run(d);
  eq(rds(d, 'child.json'), '{\n  "a": 1,\n  "b": 3\n}\n', 'merged');
  eq(rds(d, 'base.json'), '{\n  "a": 1,\n  "b": 2\n}\n', 'base');
});

await check('json: no extends -> reformatted', async () => {
  const d = mk({ 'p.json': '{"a":1}' });
  await run(d);
  eq(rds(d, 'p.json'), '{\n  "a": 1\n}\n', 'json');
});

await check('binary copied byte for byte', async () => {
  const d = mk({ 'x.bin': Buffer.from([0, 255, 13, 10, 0]) });
  await run(d);
  ok(rd(d, 'x.bin').equals(Buffer.from([0, 255, 13, 10, 0])), 'bytes differ');
});

await check('manifest shape: version 2, key/deps/out', async () => {
  const d = mk({ 'a.js': 'x\n' });
  await run(d);
  const m = manifest(d);
  eq(m.version, 2, 'version');
  ok(m.files['a.js'], 'no entry');
  eq(typeof m.files['a.js'].key, 'string', 'key');
  ok(Array.isArray(m.files['a.js'].out), 'out not array');
});

await check('incremental: second run rebuilds nothing', async () => {
  const d = mk({ 'a.js': 'x\n', 'b.css': '.a{color:red}\n' });
  await run(d);
  const before = fs.statSync(path.join(d, 'out', 'a.js')).mtimeMs;
  const r = await run(d);
  eq(fs.statSync(path.join(d, 'out', 'a.js')).mtimeMs, before, 'a.js rewritten');
  eq(r.built.length, 0, `built: ${JSON.stringify(r.built)}`);
});

await check('incremental: asset change rebuilds css + drops stale asset', async () => {
  const d = mk({ 'style.css': '.a{background:url(./i.png)}\n', 'i.png': Buffer.from([1]) });
  await run(d);
  fs.writeFileSync(path.join(d, 'src', 'i.png'), Buffer.from([2]));
  await run(d);
  ok(rds(d, 'style.css').includes(`i.${sha(Buffer.from([2]))}.png`), 'css stale');
  ok(!exists(d, `i.${sha(Buffer.from([1]))}.png`), `stale asset left: ${JSON.stringify(listOut(d))}`);
});

await check('json extends: base change rebuilds child', async () => {
  const d = mk({ 'base.json': '{"a":1}', 'child.json': '{"extends":"./base.json"}' });
  await run(d);
  fs.writeFileSync(path.join(d, 'src', 'base.json'), '{"a":2}');
  await run(d);
  ok(rds(d, 'child.json').includes('"a": 2'), `child stale: ${rds(d, 'child.json')}`);
});

await check('delete source removes output and manifest entry', async () => {
  const d = mk({ 'a.js': 'x\n', 'b.js': 'y\n' });
  await run(d);
  fs.unlinkSync(path.join(d, 'src', 'b.js'));
  await run(d);
  ok(!exists(d, 'b.js'), 'output left behind');
  ok(!manifest(d).files['b.js'], 'manifest entry left behind');
});

await check('determinism: two clean builds byte-identical', async () => {
  const files = { 'a.js': 'let x=1;\n', 's.css': '.a{background:url(./i.png)}\n', 'i.png': Buffer.from([3, 3, 3]), 'c.json': '{"extends":"./b.json","z":1}', 'b.json': '{"a":1}' };
  const d1 = mk(files);
  await run(d1);
  const d2 = mk(files);
  await run(d2);
  eq(JSON.stringify(listOut(d1)), JSON.stringify(listOut(d2)), 'file lists differ');
  for (const f of listOut(d1)) ok(rd(d1, f).equals(rd(d2, f)), `bytes differ: ${f}`);
});

await check('incremental == clean from same prior state', async () => {
  const files = { 'a.js': 'let x=1;\n', 's.css': '.a{background:url(./i.png)}\n', 'i.png': Buffer.from([4]) };
  const clean = mk(files);
  await run(clean);
  const inc = mk(files);
  await run(inc);
  for (const d of [inc, clean]) fs.writeFileSync(path.join(d, 'src', 'a.js'), 'let x=2;\n');
  await run(inc);
  await run(clean);
  eq(JSON.stringify(listOut(inc)), JSON.stringify(listOut(clean)), 'file lists differ');
  for (const f of listOut(inc)) ok(rd(inc, f).equals(rd(clean, f)), `bytes differ: ${f}`);
});

await check('dry-run writes nothing', async () => {
  const d = mk({ 'a.js': 'x\n' });
  await build({ src: path.join(d, 'src'), out: path.join(d, 'out'), manifest: path.join(d, 'm.json'), dryRun: true });
  eq(listOut(d).length, 0, 'out written');
  ok(!fs.existsSync(path.join(d, 'm.json')), 'manifest written');
});

await check('js: banner hashes original source bytes', async () => {
  const d = mk({ 'a.js': '  spaced  \n' });
  await run(d);
  ok(rds(d, 'a.js').endsWith(`//# build ${sha('  spaced  \n')}\n`), `banner ${JSON.stringify(rds(d, 'a.js'))}`);
});

await check('empty source tree does not throw', async () => {
  await run(mk({}));
});

const fail = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.ok ? '' : `\n        ${r.detail}`}`);
console.log(`\n${results.length - fail.length}/${results.length} passed`);
