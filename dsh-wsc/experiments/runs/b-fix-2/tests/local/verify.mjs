// Local A/B harness for the four defects (not part of `npm test`).
// Runs in-process: the sandbox blocks piped stdio for spawned programs.
import assert from 'node:assert/strict';
import { cp, mkdtemp, readFile, rm, stat, utimes, writeFile, unlink, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build, watch, parseArgs } from '../../lib/build.js';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

async function project() {
  const dir = await mkdtemp(path.join(tmpdir(), 'mini-build-verify-'));
  await cp(repoRoot, dir, {
    recursive: true,
    filter: (s) => !/[\\/](out|node_modules|tests)([\\/]|$)/.test(s) && !s.endsWith('build-manifest.json'),
  });
  return dir;
}
const buildIn = (dir, argv = []) => build(parseArgs(['--json', ...argv]), dir);

const results = [];
async function check(name, fn) {
  const dir = await project();
  try {
    await fn(dir);
    results.push(`PASS ${name}`);
  } catch (error) {
    results.push(`FAIL ${name}: ${error.message}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

// 1. fingerprint must come from bytes, not mtime/size.
await check('content change with preserved mtime rebuilds', async (dir) => {
  const file = path.join(dir, 'src/a.js');
  const before = await stat(file);
  await buildIn(dir);
  const original = await readFile(file, 'utf8');
  const mutated = original.replace('const a', 'let a');
  assert.notEqual(mutated, original, 'fixture needs `const a` to flip');
  await writeFile(file, mutated);
  await utimes(file, before.atime, before.mtime);
  const report = await buildIn(dir);
  assert.deepEqual(report.built, ['a.js'], `expected rebuild, got ${JSON.stringify(report)}`);
});

// 2. a css url() target is a dependency of the css file.
await check('css rebuilds when a url() target changes', async (dir) => {
  await buildIn(dir);
  const css1 = await readFile(path.join(dir, 'out/style.css'), 'utf8');
  const png = path.join(dir, 'src/img.png');
  await writeFile(png, Buffer.concat([await readFile(png), Buffer.from([0])]));
  const report = await buildIn(dir);
  assert.ok(report.built.includes('style.css'), `css not rebuilt: ${JSON.stringify(report)}`);
  const css2 = await readFile(path.join(dir, 'out/style.css'), 'utf8');
  assert.notEqual(css1, css2, 'hashed asset name did not change');
  const names = await readdir(path.join(dir, 'out'));
  const hashed = names.filter((n) => /^img\.[0-9a-f]{8}\.png$/.test(n));
  assert.equal(hashed.length, 1, `stale hashed asset kept: ${names.join(',')}`);
  assert.ok(css2.includes(hashed[0]), 'css does not point at the live asset');
});

// 3. json "extends" is a dependency of the deriving file.
await check('json rebuilds when its extends base changes', async (dir) => {
  await buildIn(dir);
  const base = path.join(dir, 'src/base.json');
  await writeFile(base, `${JSON.stringify({ ...JSON.parse(await readFile(base, 'utf8')), added: 'x' }, null, 2)}\n`);
  const report = await buildIn(dir);
  assert.ok(report.built.includes('data.json'), `expected derived rebuild, got ${JSON.stringify(report.built)}`);
  const out = JSON.parse(await readFile(path.join(dir, 'out/data.json'), 'utf8'));
  assert.equal(out.added, 'x', 'derived output did not pick up the base change');
  assert.equal(out.extends, undefined);
});

// 4. a manifest entry whose output vanished must heal.
await check('deleted output is rebuilt', async (dir) => {
  await buildIn(dir);
  await unlink(path.join(dir, 'out/a.js'));
  const report = await buildIn(dir);
  assert.deepEqual(report.built, ['a.js'], `expected heal, got ${JSON.stringify(report)}`);
  assert.ok((await stat(path.join(dir, 'out/a.js'))).isFile());
});

// 5. a corrupt manifest is treated as absent, not fatal.
await check('truncated manifest rebuilds instead of crashing', async (dir) => {
  await buildIn(dir);
  await writeFile(path.join(dir, 'build-manifest.json'), '{"version":2,"files":{"a.js"');
  const report = await buildIn(dir);
  assert.ok(report.built.includes('a.js'));
  JSON.parse(await readFile(path.join(dir, 'build-manifest.json'), 'utf8'));
});

// 6. dry-run writes nothing; concurrency is bounded but complete.
await check('dry-run leaves no out or manifest', async (dir) => {
  const report = await buildIn(dir, ['--dry-run']);
  assert.ok(report.built.length > 0);
  await assert.rejects(stat(path.join(dir, 'out/a.js')));
  await assert.rejects(stat(path.join(dir, 'build-manifest.json')));
});

await check('concurrency 1 matches concurrency 8 byte for byte', async (dir) => {
  await buildIn(dir, ['--concurrency', '1']);
  const files = (await readdir(path.join(dir, 'out'))).sort();
  const snap = {};
  for (const f of files) snap[f] = await readFile(path.join(dir, 'out', f), 'utf8');
  await rm(path.join(dir, 'out'), { recursive: true, force: true });
  await rm(path.join(dir, 'build-manifest.json'), { force: true });
  await buildIn(dir, ['--concurrency', '8']);
  for (const f of files) assert.equal(await readFile(path.join(dir, 'out', f), 'utf8'), snap[f], f);
});

// 7. watch rebuilds on change and reaps on delete.
await check('watch rebuilds and reaps', async (dir) => {
  const reports = [];
  const close = await watch(parseArgs([]), dir, (r) => reports.push(r));
  const settle = async (n) => {
    const deadline = Date.now() + 15000;
    while (reports.length < n) {
      if (Date.now() > deadline) throw new Error(`watch produced ${reports.length} reports, wanted ${n}`);
      await new Promise((r) => setTimeout(r, 100));
    }
  };
  try {
    await settle(1);
    await writeFile(path.join(dir, 'src/a.js'), 'export const two = 2;\n');
    await settle(2);
    assert.ok((await readFile(path.join(dir, 'out/a.js'), 'utf8')).includes('two'), 'watch did not rebuild');
    await unlink(path.join(dir, 'src/a.js'));
    await settle(3);
    await assert.rejects(stat(path.join(dir, 'out/a.js')), 'watch did not reap');
  } finally {
    await close();
  }
});

console.log(results.join('\n'));
process.exitCode = results.some((r) => r.startsWith('FAIL')) ? 1 : 0;
