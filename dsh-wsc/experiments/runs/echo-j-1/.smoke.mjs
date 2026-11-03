// In-process smoke check: exercises the build/watch API directly.
import { mkdtemp, mkdir, writeFile, readFile, rm, stat, utimes, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { build } from './lib/build.js';
import { watchBuild } from './lib/watch.js';

const results = [];
const check = (name, ok, detail = '') => {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ` — ${detail}` : ''}`);
};

const root = await mkdtemp(path.join(tmpdir(), 'mini-build-smoke-'));
const opts = { src: 'src', out: 'out', manifest: 'build-manifest.json', concurrency: 4 };

async function write(rel, text) {
  const abs = path.join(root, rel);
  await mkdir(path.dirname(abs), { recursive: true });
  await writeFile(abs, text);
}

async function exists(rel) {
  try {
    await stat(path.join(root, rel));
    return true;
  } catch {
    return false;
  }
}

const manifest = async () => JSON.parse(await readFile(path.join(root, opts.manifest), 'utf8'));

try {
  await write('src/a.txt', 'alpha');
  await write('src/nested/b.txt', 'beta');
  await write('src/index.html', '<link rel="stylesheet" href="style.css">');
  await write('src/style.css', 'body{background:url(missing.png)}');

  // 1. cold build
  let report = await build(opts, root);
  check('cold build compiles every file', report.built.length === 4 && report.skipped.length === 0, JSON.stringify(report.built));
  check('manifest is v2', (await manifest()).version === 2);
  check('css url() with a missing target still copies', await exists('out/style.css'));

  // 2. no-op build
  report = await build(opts, root);
  check('second build skips everything', report.built.length === 0 && report.skipped.length === 4, `built=${report.built.length}`);

  // 3. content change with a restored mtime must still rebuild
  const aAbs = path.join(root, 'src/a.txt');
  const before = await stat(aAbs);
  await writeFile(aAbs, 'alpha-2');
  await utimes(aAbs, before.atime, before.mtime);
  report = await build(opts, root);
  check('content change with unchanged mtime rebuilds', report.built.includes('a.txt'), JSON.stringify(report.built));

  // 4. removing a dependency must prune its edge, so re-adding it rebuilds
  await write('src/base.json', '{"name":"base"}');
  await write('src/data.json', '{"extends":"base.json","value":1}');
  await build(opts, root);
  const depsOf = async (rel) => Object.keys((await manifest()).files[rel]?.deps ?? {});
  check('dependency edge is recorded', (await depsOf('data.json')).includes('base.json'), JSON.stringify(await depsOf('data.json')));

  await rm(path.join(root, 'src/nested'), { recursive: true });
  report = await build(opts, root);
  check('deleted source prunes its output', report.removed.includes('nested/b.txt') && !(await exists('out/nested/b.txt')));
  check('deleted source leaves no stale dep edge', !(await depsOf('data.json')).includes('nested/b.txt'));

  await write('src/nested/b.txt', 'beta-2');
  report = await build(opts, root);
  check('re-added source builds again', report.built.includes('nested/b.txt'), JSON.stringify(report.built));

  await write('src/base.json', '{"name":"base-2"}');
  report = await build(opts, root);
  check('changed dependency rebuilds its dependents', report.built.includes('data.json'), JSON.stringify(report.built));

  await write('src/m.js', "import './n.js';\n");
  await write('src/n.js', 'export const n = 1;\n');
  await build(opts, root);
  await write('src/m.js', 'export const m = 2;\n');
  await build(opts, root);
  await write('src/n.js', 'export const n = 3;\n');
  report = await build(opts, root);
  check('dropped dependency stops triggering rebuilds', report.built.includes('n.js') && !report.built.includes('m.js'), JSON.stringify(report.built));

  await rm(path.join(root, 'src/base.json'));
  let threw = '';
  try {
    await build(opts, root);
  } catch (err) {
    threw = err.message;
  }
  check('missing extends base fails the build', /missing extends base/.test(threw), threw);
  await write('src/base.json', '{"name":"base-3"}');
  report = await build(opts, root);
  check('build recovers once the base returns', report.built.includes('data.json'), JSON.stringify(report.built));

  // 5. concurrency does not change the result
  const serial = await build({ ...opts, concurrency: 1 }, root);
  const parallel = await build({ ...opts, concurrency: 8 }, root);
  check('concurrency 8 matches a settled tree', parallel.built.length === 0 && serial.built.length === 0);
  check('outputs match sources', (await readFile(path.join(root, 'out/nested/b.txt'), 'utf8')) === 'beta-2');

  // 6. watch rebuilds on change and stops on abort
  const controller = new AbortController();
  const reports = [];
  const running = watchBuild(opts, {
    cwd: root,
    onReport: (r) => reports.push(r),
    onError: (e) => console.log(`watch error: ${e.message}`),
    signal: controller.signal,
  });
  const waitFor = async (n) => {
    const deadline = Date.now() + 4000;
    while (reports.length < n && Date.now() < deadline) await new Promise((r) => setTimeout(r, 25));
    return reports.length >= n;
  };
  check('watch runs an initial build', await waitFor(1), `reports=${reports.length}`);
  await write('src/a.txt', 'alpha-3');
  check('watch rebuilds after a change', await waitFor(2) && reports.at(-1).built.includes('a.txt'), `reports=${reports.length}`);
  check('watch output is current', (await readFile(path.join(root, 'out/a.txt'), 'utf8')) === 'alpha-3');
  controller.abort();
  await running;
  check('watch loop closes on abort', true);

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  process.exitCode = failed.length === 0 ? 0 : 1;
} finally {
  await rm(root, { recursive: true, force: true });
}
