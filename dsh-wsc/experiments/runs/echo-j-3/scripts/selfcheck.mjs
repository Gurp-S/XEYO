import assert from 'node:assert/strict';
import { cp, mkdtemp, readFile, readdir, rm, stat, utimes, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from '../lib/build.js';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const srcRoot = path.join(repoRoot, 'src');

async function project() {
  const dir = await mkdtemp(path.join(tmpdir(), 'mb-check-'));
  await cp(srcRoot, path.join(dir, 'src'), { recursive: true });
  return dir;
}
const run = (dir, extra = {}) => build({ src: 'src', out: 'out', manifest: 'build-manifest.json', ...extra }, dir);
const read = (dir, rel) => readFile(path.join(dir, rel), 'utf8');
const exists = async (p) => !!(await stat(p).catch(() => null));

const dir = await project();
try {
  const first = await run(dir);
  assert.equal(first.skipped.length, 0);
  assert.match(await read(dir, 'out/a.js'), /\/\/# build [0-9a-f]{8}/);
  assert.match(await read(dir, 'out/style.css'), /url\(img\.[0-9a-f]{8}\.png\)/);
  const manifest = JSON.parse(await read(dir, 'build-manifest.json'));
  assert.equal(manifest.version, 2);
  assert.ok(manifest.files['a.js']);
  assert.ok(await exists(path.join(dir, 'out', manifest.files['style.css'].out[1])));

  const second = await run(dir);
  assert.deepEqual([second.built.length, second.removed.length], [0, 0]);
  assert.equal(second.skipped.length, first.built.length);

  // mtime-preserving rewrite still rebuilds
  const aPath = path.join(dir, 'src/a.js');
  const stamp = (await stat(aPath)).mtime;
  await writeFile(aPath, `${await read(dir, 'src/a.js')}\n// changed\n`);
  await utimes(aPath, stamp, stamp);
  assert.deepEqual((await run(dir)).built, ['a.js']);

  // dependency bytes change rebuilds the dependent file only
  const imgPath = path.join(dir, 'src/img.png');
  const before = await readFile(imgPath);
  await writeFile(imgPath, Buffer.concat([before, Buffer.from('x')]));
  const dep = await run(dir);
  assert.ok(dep.built.includes('style.css'));
  assert.ok(!dep.built.includes('a.js'));

  // a changed base object rebuilds the extending file
  await writeFile(path.join(dir, 'src/base.json'), '{"name":"base","level":2,"tone":"warm"}\n');
  const rebased = await run(dir);
  assert.ok(rebased.built.includes('data.json'));
  assert.match(await read(dir, 'out/data.json'), /"tone": "warm"/);
  assert.match(await read(dir, 'out/data.json'), /"name": "demo"/);

  // a dangling extends target is a build error and writes nothing
  const goodData = await read(dir, 'out/data.json');
  const goodManifest = await read(dir, 'build-manifest.json');
  await rm(path.join(dir, 'src/base.json'));
  await assert.rejects(run(dir), /base\.json/);
  assert.equal(await read(dir, 'out/data.json'), goodData);
  assert.equal(await read(dir, 'build-manifest.json'), goodManifest);
  await writeFile(path.join(dir, 'src/base.json'), '{"name":"base","level":2,"tone":"warm"}\n');

  // deleting a source removes its outputs, and manifest no longer names it
  const extraManifest = JSON.parse(await read(dir, 'build-manifest.json'));
  const extraOut = extraManifest.files['extra.js'].out[0];
  await rm(path.join(dir, 'src/extra.js'));
  const removed = await run(dir);
  assert.deepEqual(removed.removed, ['extra.js']);
  assert.ok(!(await exists(path.join(dir, 'out', extraOut))));

  // a missing output heals on the next build
  const bOut = path.join(dir, 'out/b.js');
  await rm(bOut);
  assert.deepEqual((await run(dir)).built, ['b.js']);
  assert.ok(await exists(bOut));

  // dry run writes nothing
  const dryDir = await project();
  await run(dryDir, { dryRun: true });
  assert.deepEqual(await readdir(dryDir), ['src']);
  await rm(dryDir, { recursive: true, force: true });

  // concurrency does not change the result, and a full rebuild equals the
  // incremental output byte for byte
  const soloDir = await project();
  await run(soloDir, { concurrency: 1 });
  const parDir = await project();
  await run(parDir, { concurrency: 8 });
  const snapshot = async (d) => {
    const out = path.join(d, 'out');
    const names = (await readdir(out)).sort();
    return Promise.all(names.map(async (n) => [n, await readFile(path.join(out, n), 'base64')]));
  };
  const compare = (label, a, b) => {
    const mapA = new Map(a);
    const mapB = new Map(b);
    const keys = [...new Set([...mapA.keys(), ...mapB.keys()])].sort();
    const bad = keys.filter((k) => mapA.get(k) !== mapB.get(k));
    assert.deepEqual(bad, [], `${label}: ${bad.join(', ')}`);
  };
  compare('concurrency', await snapshot(parDir), await snapshot(soloDir));

  const freshDir = await project();
  await rm(path.join(freshDir, 'src'), { recursive: true, force: true });
  await cp(path.join(dir, 'src'), path.join(freshDir, 'src'), { recursive: true });
  await run(freshDir);
  compare('incremental vs full', await snapshot(freshDir), await snapshot(dir));
  await rm(soloDir, { recursive: true, force: true });
  await rm(parDir, { recursive: true, force: true });
  await rm(freshDir, { recursive: true, force: true });

  console.log('selfcheck ok');
} finally {
  await rm(dir, { recursive: true, force: true });
}
