// Contract verification for the four reported defects and the two new options.
// Runs the real build in-process against throwaway fixtures under tests/.verify-work.
// Usage: node tests/verify.mjs
import { cp, mkdir, readFile, readdir, rm, stat, utimes, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build, parseArgs } from '../lib/build.js';
import { mapLimit } from '../lib/pool.js';
import { startWatch } from '../lib/watch.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const work = path.join(root, 'tests/.verify-work');
const src = '.verify-src';
const out = '.verify-out';
const manifestFile = '.verify-manifest.json';
const srcDir = path.join(work, src);
const outDir = path.join(work, out);
const manifestPath = path.join(work, manifestFile);

const results = [];
const check = (name, ok, detail) => results.push({ name, ok: Boolean(ok), detail });

const baseOpts = parseArgs(['--src', src, '--out', out, '--manifest', manifestFile]);
const withFlag = (...flags) => ({ ...baseOpts, ...parseArgs([...flags, '--src', src, '--out', out, '--manifest', manifestFile]) });
const run = (extra = {}) => build({ ...baseOpts, ...extra }, work);
const read = (rel) => readFile(path.join(work, rel), 'utf8');
const exists = (rel) => stat(path.join(work, rel)).then(() => true, () => false);
const manifest = async () => JSON.parse(await read(manifestFile));
const sha1 = (text) => createHash('sha1').update(text).digest('hex').slice(0, 8);

await rm(work, { recursive: true, force: true });
await mkdir(work, { recursive: true });
await cp(path.join(root, 'src'), srcDir, { recursive: true });

// --- Defect 1b: a base file pulled in through JSON extends must dirty the derived file.
await writeFile(path.join(srcDir, 'base.json'), '{"a":1,"b":1}\n');
await writeFile(path.join(srcDir, 'derived.json'), '{"extends":"./base.json","b":2}\n');
await run();
const derivedBefore = JSON.parse(await read(`${out}/derived.json`));
await writeFile(path.join(srcDir, 'base.json'), '{"a":9,"b":1}\n');
const extendsReport = await run();
const derivedAfter = JSON.parse(await read(`${out}/derived.json`));
check('1b merged output is correct', derivedBefore.a === 1 && derivedBefore.b === 2 && !('extends' in derivedBefore), derivedBefore);
check('1b base change rebuilds derived', extendsReport.built.includes('derived.json') && derivedAfter.a === 9, {
  built: extendsReport.built,
  derivedAfter,
});

// --- Defect 2: same size, same mtime, different bytes must rebuild.
const notePath = path.join(srcDir, 'note.js');
await writeFile(notePath, 'aaaa\n');
await run();
const stamp = (await stat(notePath)).mtime;
await writeFile(notePath, 'bbbb\n');
await utimes(notePath, stamp, stamp);
const mtimeReport = await run();
const noteOut = await read(`${out}/note.js`);
check(
  '2 rewritten source with untouched mtime rebuilds',
  mtimeReport.built.includes('note.js') && noteOut.includes(sha1('bbbb\n')),
  { built: mtimeReport.built, noteOut },
);

// --- Defect 3a: deleting a source removes its output and its manifest entry.
await writeFile(path.join(srcDir, 'gone.js'), 'export const gone = 1;\n');
await run();
await rm(path.join(srcDir, 'gone.js'));
const deleteReport = await run();
const afterDelete = await manifest();
check(
  '3a deleted source drops output and manifest entry',
  !(await exists(`${out}/gone.js`)) && !('gone.js' in afterDelete.files) && deleteReport.removed.includes('gone.js'),
  { removed: deleteReport.removed, files: Object.keys(afterDelete.files) },
);

// --- Defect 3b: a manifest naming an output that vanished must heal.
await rm(path.join(outDir, 'note.js'));
const healReport = await run();
check(
  '3b missing output is rebuilt from manifest state',
  (await exists(`${out}/note.js`)) && healReport.built.includes('note.js'),
  { built: healReport.built },
);

// --- Defect 4: a half-written manifest must not crash the next build.
await writeFile(manifestPath, (await read(manifestFile)).slice(0, 40));
let interruptedError = null;
try {
  await run();
} catch (error) {
  interruptedError = String(error?.message ?? error);
}
const healed = await manifest();
check(
  '4 truncated manifest recovers',
  interruptedError === null && healed.version === 2 && 'note.js' in healed.files,
  { interruptedError, version: healed.version },
);

// --- Feature: --concurrency bounds parallelism and never changes output bytes.
let inFlight = 0;
let peak = 0;
await mapLimit(Array.from({ length: 12 }, (_, i) => i), 3, async () => {
  inFlight += 1;
  peak = Math.max(peak, inFlight);
  await new Promise((resolve) => setTimeout(resolve, 5));
  inFlight -= 1;
});
check('concurrency limit is honoured', peak <= 3 && peak > 1, { peak });

const serialize = async (dir) => {
  const names = (await readdir(dir)).sort();
  return Promise.all(names.map(async (name) => [name, await readFile(path.join(dir, name), 'utf8')]));
};
await rm(outDir, { recursive: true, force: true });
await rm(manifestPath, { force: true });
await run({ concurrency: 1 });
const serial = await serialize(outDir);
await rm(outDir, { recursive: true, force: true });
await rm(manifestPath, { force: true });
const parallelReport = await run(withFlag('--concurrency', '8'));
const parallel = await serialize(outDir);
check(
  'concurrency 1 and 8 produce identical bytes',
  JSON.stringify(serial) === JSON.stringify(parallel),
  { names: parallel.map(([name]) => name), built: parallelReport.built.length },
);

// --- Feature: --dry-run writes nothing at all.
await rm(outDir, { recursive: true, force: true });
await rm(manifestPath, { force: true });
const dryReport = await run(withFlag('--dry-run'));
check(
  'dry-run writes neither out nor manifest',
  !(await exists(out)) && !(await exists(manifestFile)) && dryReport.built.length > 0,
  { planned: dryReport.built.length },
);

// --- Existing contract: an unchanged rebuild skips every file.
const firstReport = await run();
const secondReport = await run();
check(
  'unchanged rebuild skips everything',
  firstReport.built.length > 0 && secondReport.built.length === 0 && secondReport.removed.length === 0,
  { first: firstReport.built.length, second: secondReport.built.length },
);

// --- Feature: --watch rebuilds after a source change.
const reports = [];
const handle = await startWatch(baseOpts, { cwd: work, onReport: (report) => reports.push(report) });
await writeFile(path.join(srcDir, 'watched.js'), 'export const watched = 1;\n');
const deadline = Date.now() + 4000;
while (Date.now() < deadline && !(await exists(`${out}/watched.js`))) {
  await new Promise((resolve) => setTimeout(resolve, 100));
}
await handle.close();
check(
  'watch rebuilds on change',
  reports.length >= 2 && (await exists(`${out}/watched.js`)),
  { reports: reports.length, built: reports.at(-1)?.built },
);

const failed = results.filter((result) => !result.ok);
console.log(JSON.stringify({ failed: failed.length, results }, null, 2));
process.exitCode = failed.length === 0 ? 0 : 1;
