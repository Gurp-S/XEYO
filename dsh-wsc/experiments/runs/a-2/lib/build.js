import { mkdir, readdir, readFile, rm, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { cacheKey, hashBytes } from './cache.js';
import { cssTargets, depSpecifiers, jsonExtends, rewriteCss } from './graph.js';
import { loadManifest, MANIFEST_VERSION, saveManifest } from './manifest.js';
import { mapLimit } from './pool.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';
export const DEFAULT_CONCURRENCY = 1;

const VALUE_FLAGS = ['src', 'out', 'manifest'];
const BOOLEAN_FLAGS = ['dry-run', 'json', 'watch', 'help'];
// Extensions whose bytes are decoded to find dependencies.
const TEXT_EXT = new Set(['.js', '.mjs', '.css', '.json']);

export const USAGE = `mini-build [options]

  --src <dir>        source directory (default: ${DEFAULT_SRC})
  --out <dir>        output directory (default: ${DEFAULT_OUT})
  --manifest <file>  manifest file (default: ${DEFAULT_MANIFEST})
  --concurrency <n>  build at most <n> files at once (default: ${DEFAULT_CONCURRENCY})
  --watch            rebuild whenever a source file changes
  --dry-run          report what would happen without writing anything
  --json             print the report as JSON
  --help, -h         show this message
`;

function parseConcurrency(value) {
  const limit = Number(value);
  if (!Number.isInteger(limit) || limit < 1) {
    throw new Error('--concurrency needs a positive integer');
  }
  return limit;
}

export function parseArgs(argv) {
  const opts = {
    src: DEFAULT_SRC,
    out: DEFAULT_OUT,
    manifest: DEFAULT_MANIFEST,
    concurrency: DEFAULT_CONCURRENCY,
    dryRun: false,
    json: false,
    watch: false,
    help: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '-h') {
      opts.help = true;
      continue;
    }
    if (!arg.startsWith('--')) throw new Error(`unknown argument: ${arg}`);
    const key = arg.slice(2);
    if (VALUE_FLAGS.includes(key)) {
      opts[key] = takeValue(argv, index, key);
      index += 1;
    } else if (key === 'concurrency') {
      opts.concurrency = parseConcurrency(takeValue(argv, index, key));
      index += 1;
    } else if (BOOLEAN_FLAGS.includes(key)) {
      opts[key === 'dry-run' ? 'dryRun' : key] = true;
    } else {
      throw new Error(`unknown argument: ${arg}`);
    }
  }
  return opts;
}

function takeValue(argv, index, key) {
  const value = argv[index + 1];
  if (!value) throw new Error(`--${key} needs a value`);
  return value;
}

async function walk(dir, base) {
  const files = [];
  const entries = await readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    const rel = path.relative(base, abs).split(path.sep).join('/');
    if (entry.isDirectory()) {
      files.push(...(await walk(abs, base)));
    } else if (entry.isFile()) {
      files.push(rel);
    }
  }
  return files.sort();
}

// A specifier only names a file inside the source tree. Absolute paths,
// protocols, fragments and anything climbing out of the tree are left alone.
function resolveDep(rel, spec) {
  if (/^(?:[a-z][a-z0-9+.-]*:|\/|#)/i.test(spec)) return null;
  const target = path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec));
  if (target.startsWith('..') || path.posix.isAbsolute(target)) return null;
  return target;
}

function hashedName(relTarget, bytes) {
  const ext = path.posix.extname(relTarget);
  const base = path.posix.basename(relTarget, ext);
  return `${base}.${hashBytes(bytes).slice(0, 8)}${ext}`;
}

function replaceBasename(target, name) {
  const base = path.posix.basename(target);
  return `${target.slice(0, target.length - base.length)}${name}`;
}

function normalizeConcurrency(value) {
  return Number.isInteger(value) && value > 0 ? value : DEFAULT_CONCURRENCY;
}

async function exists(abs) {
  try {
    await stat(abs);
    return true;
  } catch {
    return false;
  }
}

// Resolves an output name to a path inside the output directory, or null when a
// (possibly hand-edited) manifest points somewhere else.
function outPath(outDir, rel) {
  const abs = path.resolve(outDir, rel);
  const inside = path.relative(outDir, abs);
  if (inside === '' || inside.startsWith('..') || path.isAbsolute(inside)) return null;
  return abs;
}

async function outputsPresent(outDir, names) {
  const checks = await Promise.all(names.map((name) => {
    const abs = outPath(outDir, name);
    return abs ? exists(abs) : false;
  }));
  return checks.every(Boolean);
}

function sortKeys(object) {
  return Object.fromEntries(Object.entries(object).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)));
}

// Produces the files one source emits: the source's own output first, then any
// hashed assets a stylesheet pulls in.
async function renderSource(rel, srcDir) {
  const abs = path.join(srcDir, rel);
  const ext = path.posix.extname(rel);
  if (ext === '.js' || ext === '.mjs') {
    const text = await readFile(abs, 'utf8');
    return [[rel, `${text.trimEnd()}\n//# build ${hashBytes(text).slice(0, 8)}\n`]];
  }
  if (ext === '.css') {
    const text = await readFile(abs, 'utf8');
    const names = new Map();
    const assets = new Map();
    for (const target of cssTargets(text)) {
      if (names.has(target)) continue;
      const relTarget = resolveDep(rel, target);
      const base = path.posix.basename(target);
      if (!relTarget || !base) continue;
      let bytes;
      try {
        bytes = await readFile(path.join(srcDir, relTarget));
      } catch {
        // A missing asset leaves the reference untouched; it becomes a
        // dependency with a `missing` fingerprint, so it rebuilds when added.
        continue;
      }
      const name = hashedName(relTarget, bytes);
      names.set(target, replaceBasename(target, name));
      assets.set(path.posix.join(path.posix.dirname(relTarget), name), bytes);
    }
    return [[rel, rewriteCss(text, names)], ...assets];
  }
  if (ext === '.json') {
    const text = await readFile(abs, 'utf8');
    const own = JSON.parse(text);
    let merged = own;
    const spec = jsonExtends(text);
    const relBase = spec ? resolveDep(rel, spec) : null;
    if (relBase) {
      const base = JSON.parse(await readFile(path.join(srcDir, relBase), 'utf8'));
      const { extends: _dropped, ...rest } = own;
      merged = { ...base, ...rest };
    }
    return [[rel, `${JSON.stringify(merged, null, 2)}\n`]];
  }
  return [[rel, await readFile(abs)]];
}

export async function planBuild(opts, cwd = process.cwd()) {
  const limit = normalizeConcurrency(opts.concurrency);
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const sources = await walk(srcDir, srcDir);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  const keys = new Map();
  const deps = new Map();
  await mapLimit(sources, limit, async (rel) => {
    const abs = path.join(srcDir, rel);
    if (!TEXT_EXT.has(path.posix.extname(rel))) {
      keys.set(rel, await cacheKey(abs));
      deps.set(rel, {});
      return;
    }
    const bytes = await readFile(abs);
    keys.set(rel, hashBytes(bytes));
    const resolved = {};
    for (const spec of depSpecifiers(rel, bytes.toString('utf8'))) {
      const target = resolveDep(rel, spec);
      if (target) resolved[target] = null;
    }
    deps.set(rel, resolved);
  });
  for (const [rel, resolved] of deps) {
    for (const target of Object.keys(resolved)) resolved[target] = keys.get(target) ?? 'missing';
    deps.set(rel, sortKeys(resolved));
  }

  const results = await mapLimit(sources, limit, async (rel) => {
    const key = keys.get(rel);
    const resolved = deps.get(rel) ?? {};
    const prev = manifest.files[rel];
    const stale = Object.entries(resolved).some(([dep, depKey]) => (prev?.deps ?? {})[dep] !== depKey);
    const present = prev ? await outputsPresent(outDir, prev.out) : false;
    const dirty = !prev || prev.key !== key || stale || !present;
    if (!dirty) return { rel, key, deps: resolved, out: prev.out, files: [], dirty: false };
    const files = await renderSource(rel, srcDir);
    return { rel, key, deps: resolved, out: files.map(([name]) => name), files, dirty: true };
  });

  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = {};
  const expected = new Set();
  for (const result of results) {
    if (result.dirty) built.push(result.rel);
    else skipped.push(result.rel);
    for (const [name, content] of result.files) outputs.set(name, content);
    for (const name of result.out) expected.add(name);
    nextFiles[result.rel] = { key: result.key, deps: result.deps, out: result.out };
  }

  // Every output the previous manifest promised that this build no longer
  // produces: outputs of deleted sources and hashed assets that changed name.
  const prune = [];
  const seen = new Set();
  for (const entry of Object.values(manifest.files)) {
    for (const name of entry.out) {
      if (expected.has(name) || seen.has(name)) continue;
      seen.add(name);
      prune.push(name);
    }
  }
  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles));

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    prune: prune.sort(),
    removed,
    built,
    skipped,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

function report(plan, dryRun, started) {
  return {
    built: plan.built,
    skipped: plan.skipped,
    removed: plan.removed,
    outputs: plan.outputs.size,
    dryRun,
    durationMs: Date.now() - started,
  };
}

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const limit = normalizeConcurrency(opts.concurrency);
  const plan = await planBuild(opts, cwd);
  if (opts.dryRun) return report(plan, true, started);
  await mkdir(plan.outDir, { recursive: true });
  await mapLimit([...plan.outputs], limit, async ([rel, content]) => {
    const abs = outPath(plan.outDir, rel);
    if (!abs) return;
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  });
  await mapLimit(plan.prune, limit, async (rel) => {
    const abs = outPath(plan.outDir, rel);
    if (abs) await rm(abs, { force: true });
  });
  // The manifest goes last: until the outputs exist it must keep describing the
  // previous state, never a state that is only half on disk.
  await saveManifest(plan.manifestPath, plan.next);
  return report(plan, false, started);
}
