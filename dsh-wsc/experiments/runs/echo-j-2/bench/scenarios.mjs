import { mkdtemp, mkdir, readdir, readFile, rm, stat, utimes, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const OPTS = { src: 'src', out: 'out', manifest: 'build-manifest.json' };

async function project(files) {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'mini-build-ab-'));
  for (const [rel, content] of Object.entries(files)) {
    const abs = path.join(dir, 'src', rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  }
  return dir;
}

async function tree(dir) {
  const out = {};
  const walk = async (current) => {
    for (const entry of await readdir(current, { withFileTypes: true })) {
      const abs = path.join(current, entry.name);
      if (entry.isDirectory()) await walk(abs);
      else out[path.relative(dir, abs).split(path.sep).join('/')] = await readFile(abs);
    }
  };
  await walk(dir);
  return out;
}

const same = (a, b) => {
  const keys = Object.keys(a).sort();
  const other = Object.keys(b).sort();
  if (keys.join('|') !== other.join('|')) return false;
  return keys.every((key) => a[key].equals(b[key]));
};

const BASE = {
  'a.js': 'const a = 1;\n',
  'b.js': 'const b = 2;\n',
  'style.css': 'body { background: url(img.png); }\n',
  'img.png': 'PNG-ONE',
  'data.json': '{"extends":"./base.json","b":2}\n',
  'base.json': '{"a":1}\n',
};

async function changedAsset(build) {
  const dir = await project(BASE);
  await build(OPTS, dir);
  await writeFile(path.join(dir, 'src', 'img.png'), 'PNG-TWO');
  const report = await build(OPTS, dir);
  const css = await readFile(path.join(dir, 'out', 'style.css'), 'utf8');
  const hashed = (await readdir(path.join(dir, 'out'))).filter((n) => /^img\.[0-9a-f]{8}\.png$/.test(n));
  return report.built.includes('style.css') && hashed.length === 1 && css.includes(hashed[0]);
}

async function changedJsonBase(build) {
  const dir = await project(BASE);
  await build(OPTS, dir);
  await writeFile(path.join(dir, 'src', 'base.json'), '{"a":9}\n');
  const report = await build(OPTS, dir);
  const out = JSON.parse(await readFile(path.join(dir, 'out', 'data.json'), 'utf8'));
  return report.built.includes('data.json') && out.a === 9;
}

async function sameSizeSameMtime(build) {
  const dir = await project(BASE);
  await build(OPTS, dir);
  const abs = path.join(dir, 'src', 'a.js');
  const before = await stat(abs);
  await writeFile(abs, 'const a = 7;\n');
  await utimes(abs, before.atime, before.mtime);
  const report = await build(OPTS, dir);
  const out = await readFile(path.join(dir, 'out', 'a.js'), 'utf8');
  return report.built.includes('a.js') && out.includes('const a = 7');
}

async function deletedSource(build) {
  const dir = await project(BASE);
  await build(OPTS, dir);
  await rm(path.join(dir, 'src', 'b.js'));
  await build(OPTS, dir);
  const outs = await readdir(path.join(dir, 'out'));
  const manifest = JSON.parse(await readFile(path.join(dir, 'build-manifest.json'), 'utf8'));
  return !outs.includes('b.js') && !('b.js' in manifest.files);
}

async function healsMissingOutput(build) {
  const dir = await project(BASE);
  await build(OPTS, dir);
  await rm(path.join(dir, 'out', 'a.js'));
  await build(OPTS, dir);
  return (await readdir(path.join(dir, 'out'))).includes('a.js');
}

async function halfWrittenManifest(build) {
  const dir = await project(BASE);
  await build(OPTS, dir);
  await writeFile(path.join(dir, 'build-manifest.json'), '{"version":2,"files":{"a.js"');
  await build(OPTS, dir);
  const manifest = JSON.parse(await readFile(path.join(dir, 'build-manifest.json'), 'utf8'));
  return 'a.js' in manifest.files;
}

async function deterministic(build) {
  const incremental = await project(BASE);
  await build(OPTS, incremental);
  await writeFile(path.join(incremental, 'src', 'a.js'), 'const a = 3;\n');
  await build(OPTS, incremental);
  const fresh = await project(BASE);
  await writeFile(path.join(fresh, 'src', 'a.js'), 'const a = 3;\n');
  await build(OPTS, fresh);
  return same(await tree(path.join(incremental, 'out')), await tree(path.join(fresh, 'out')));
}

async function dryRunWritesNothing(build) {
  const dir = await project(BASE);
  const report = await build({ ...OPTS, dryRun: true }, dir);
  const outs = await readdir(dir);
  return report.dryRun === true && !outs.includes('out') && !outs.includes('build-manifest.json');
}

async function concurrencyMatchesSerial(build) {
  const dir = await project(BASE);
  await build({ ...OPTS, concurrency: 1 }, dir);
  const serial = await tree(path.join(dir, 'out'));
  await rm(path.join(dir, 'out'), { recursive: true, force: true });
  await rm(path.join(dir, 'build-manifest.json'), { force: true });
  await build({ ...OPTS, concurrency: 3 }, dir);
  return same(serial, await tree(path.join(dir, 'out')));
}

export const scenarios = [
  ['css asset change rebuilds css', changedAsset],
  ['json extends base change rebuilds', changedJsonBase],
  ['same-size same-mtime rewrite rebuilds', sameSizeSameMtime],
  ['deleted source prunes output', deletedSource],
  ['missing output is rebuilt', healsMissingOutput],
  ['half-written manifest recovers', halfWrittenManifest],
  ['incremental equals full build', deterministic],
  ['dry run writes nothing', dryRunWritesNothing],
  ['concurrency matches serial', concurrencyMatchesSerial],
];

export async function runScenarios(build) {
  const results = [];
  for (const [name, run] of scenarios) {
    let pass = false;
    let detail = '';
    try {
      pass = await run(build);
    } catch (error) {
      detail = error instanceof Error ? error.message.split('\n')[0] : String(error);
    }
    results.push({ name, pass, detail });
  }
  return results;
}
