import { readdir, readFile, stat, mkdir, writeFile, unlink } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { readDeps } from './graph.js';
import { contentKey } from './cache.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';

const DEFAULT_CONCURRENCY = 4;
const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

export const USAGE = `usage: mini-build [options]

options:
  --src <dir>            source directory (default: src)
  --out <dir>            output directory (default: out)
  --manifest <file>      manifest path (default: build-manifest.json)
  --dry-run              report what would change, write nothing
  --watch                rebuild when a source file changes
  --concurrency <n>      max files built at once (default: ${DEFAULT_CONCURRENCY})
  --json                 machine-readable report
  --help, -h             show this help
`;

export function parseArgs(argv) {
  const opts = {
    src: 'src',
    out: 'out',
    manifest: 'build-manifest.json',
    dryRun: false,
    watch: false,
    concurrency: DEFAULT_CONCURRENCY,
    json: false,
    help: false,
  };
  const value = (arg, i) => {
    const next = argv[i + 1];
    if (next === undefined || next.startsWith('--')) {
      throw new Error(`${arg} requires a value`);
    }
    return next;
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--src') opts.src = value(arg, i++);
    else if (arg === '--out') opts.out = value(arg, i++);
    else if (arg === '--manifest') opts.manifest = value(arg, i++);
    else if (arg === '--concurrency') opts.concurrency = Number(value(arg, i++));
    else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--watch') opts.watch = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  if (!Number.isInteger(opts.concurrency) || opts.concurrency < 1) {
    throw new Error('--concurrency must be a positive integer');
  }
  return opts;
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

async function walk(dir, root) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(abs, root)));
    else if (entry.isFile()) files.push(path.relative(root, abs).split(path.sep).join('/'));
  }
  return files.sort();
}

function sha(input) {
  return createHash('sha1').update(input).digest('hex');
}

function resolveDep(rel, spec) {
  if (typeof spec !== 'string' || spec === '') return null;
  if (/^(?:[a-z][a-z0-9+.-]*:|\/|#)/i.test(spec)) return null;
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec));
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${sha(bytes).slice(0, 8)}${ext}`;
}

function outputPath(outDir, rel) {
  const abs = path.resolve(outDir, rel);
  const base = outDir.endsWith(path.sep) ? outDir : `${outDir}${path.sep}`;
  return abs.startsWith(base) ? abs : null;
}

async function exists(abs) {
  try {
    return (await stat(abs)).isFile();
  } catch {
    return false;
  }
}

function limitOf(opts) {
  return Number.isInteger(opts.concurrency) && opts.concurrency > 0
    ? opts.concurrency
    : DEFAULT_CONCURRENCY;
}

async function mapLimit(items, limit, fn) {
  const results = new Array(items.length);
  let next = 0;
  async function worker() {
    while (true) {
      const index = next++;
      if (index >= items.length) return;
      results[index] = await fn(items[index], index);
    }
  }
  const workers = Array.from({ length: Math.min(limit, items.length) }, worker);
  await Promise.all(workers);
  return results;
}

function validEntry(entry) {
  return isObject(entry) && typeof entry.key === 'string' && isObject(entry.deps) && Array.isArray(entry.out);
}

// Direct dependencies plus, for JSON files, the whole `extends` chain: the
// merged output of a derived file depends on every base in that chain.
async function depClosure(srcDir, rel, keys) {
  const deps = {};
  const seen = new Set([rel]);
  const queue = [rel];
  while (queue.length > 0) {
    const current = queue.shift();
    const ext = path.posix.extname(current);
    let specs;
    try {
      specs = await readDeps(path.join(srcDir, current), ext);
    } catch {
      specs = [];
    }
    for (const spec of specs) {
      const target = resolveDep(current, spec);
      if (!target || seen.has(target)) continue;
      seen.add(target);
      deps[target] = keys.get(target) ?? 'missing';
      if (ext === '.json' && path.posix.extname(target) === '.json') queue.push(target);
    }
  }
  return deps;
}

// Merge an `extends` chain base-first; own keys always win.
async function resolveJson(srcDir, rel, chain = new Set()) {
  const own = JSON.parse(await readFile(path.join(srcDir, rel), 'utf8'));
  if (!isObject(own) || typeof own.extends !== 'string') return own;
  const { extends: spec, ...rest } = own;
  const baseRel = resolveDep(rel, spec);
  if (!baseRel || chain.has(baseRel)) return rest;
  const next = new Set(chain).add(baseRel);
  const base = await resolveJson(srcDir, baseRel, next);
  return isObject(base) ? { ...base, ...rest } : rest;
}

async function renderSource(srcDir, rel) {
  const ext = path.posix.extname(rel);
  const abs = path.join(srcDir, rel);
  const produced = new Map();
  const outNames = [rel];

  if (ext === '.js' || ext === '.mjs') {
    const text = await readFile(abs, 'utf8');
    produced.set(rel, `${text.trimEnd()}\n//# build ${sha(text).slice(0, 8)}\n`);
  } else if (ext === '.css') {
    const text = await readFile(abs, 'utf8');
    const names = new Map();
    for (const match of text.matchAll(URL_RE)) {
      const target = match[1];
      const targetRel = resolveDep(rel, target);
      if (!targetRel) continue;
      const bytes = await readFile(path.join(srcDir, targetRel));
      const name = hashedName(targetRel, bytes);
      names.set(target, name);
      const hashedRel = path.posix.join(path.posix.dirname(rel), name);
      if (!produced.has(hashedRel)) {
        outNames.push(hashedRel);
        produced.set(hashedRel, bytes);
      }
    }
    produced.set(
      rel,
      text.replace(URL_RE, (whole, target) =>
        names.has(target) ? `url(${names.get(target)})` : whole,
      ),
    );
  } else if (ext === '.json') {
    const merged = await resolveJson(srcDir, rel);
    produced.set(rel, `${JSON.stringify(merged, null, 2)}\n`);
  } else {
    produced.set(rel, await readFile(abs));
  }

  return { outNames, produced };
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const limit = limitOf(opts);

  const sources = await walk(srcDir, srcDir);
  const loaded = await loadManifest(manifestPath);
  const manifest = loaded ?? { version: MANIFEST_VERSION, files: {} };

  const keys = new Map();
  await mapLimit(sources, limit, async (rel) => {
    keys.set(rel, contentKey(await readFile(path.join(srcDir, rel))));
  });

  const deps = new Map();
  await mapLimit(sources, limit, async (rel) => {
    deps.set(rel, await depClosure(srcDir, rel, keys));
  });

  const entries = await mapLimit(sources, limit, async (rel) => {
    const key = keys.get(rel);
    const resolved = deps.get(rel) ?? {};
    const prev = validEntry(manifest.files[rel]) ? manifest.files[rel] : null;
    let dirty = !prev || prev.key !== key;
    if (!dirty) {
      const recorded = Object.keys(prev.deps);
      dirty =
        recorded.length !== Object.keys(resolved).length ||
        recorded.some((dep) => prev.deps[dep] !== resolved[dep]);
    }
    if (!dirty) {
      dirty = prev.out.length === 0 || !prev.out.includes(rel);
    }
    if (!dirty) {
      for (const out of prev.out) {
        const abs = outputPath(outDir, out);
        if (!abs || !(await exists(abs))) {
          dirty = true;
          break;
        }
      }
    }
    return { rel, key, resolved, prev, dirty };
  });

  const dirtyEntries = entries.filter((entry) => entry.dirty);
  const transformed = new Map();
  await mapLimit(dirtyEntries, limit, async ({ rel }) => {
    transformed.set(rel, await renderSource(srcDir, rel));
  });

  const built = [];
  const skipped = [];
  const nextFiles = {};
  const outputs = new Map();
  for (const entry of entries) {
    if (entry.dirty) {
      const result = transformed.get(entry.rel);
      built.push(entry.rel);
      nextFiles[entry.rel] = { key: entry.key, deps: entry.resolved, out: result.outNames };
      for (const [outRel, content] of result.produced) outputs.set(outRel, content);
    } else {
      skipped.push(entry.rel);
      nextFiles[entry.rel] = { key: entry.key, deps: entry.resolved, out: entry.prev.out };
    }
  }

  const desired = new Set();
  for (const entry of Object.values(nextFiles)) {
    for (const out of entry.out) desired.add(out);
  }
  const stale = new Set();
  for (const prev of Object.values(manifest.files)) {
    if (!validEntry(prev)) continue;
    for (const out of prev.out) {
      if (!desired.has(out)) stale.add(out);
    }
  }

  const removed = Object.keys(manifest.files)
    .filter((rel) => !Object.hasOwn(nextFiles, rel))
    .sort();

  return {
    srcDir,
    outDir,
    manifestPath,
    built,
    skipped,
    removed,
    outputs,
    staleOutputs: [...stale].sort(),
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const plan = await planBuild(opts, cwd);
  const limit = limitOf(opts);
  const report = {
    built: plan.built,
    skipped: plan.skipped,
    removed: plan.removed,
    outputs: plan.outputs.size,
    dryRun: Boolean(opts.dryRun),
    durationMs: 0,
  };
  if (opts.dryRun) {
    report.durationMs = Date.now() - started;
    return report;
  }

  await mkdir(plan.outDir, { recursive: true });
  for (const rel of plan.staleOutputs) {
    const abs = outputPath(plan.outDir, rel);
    if (!abs) continue;
    try {
      await unlink(abs);
    } catch (error) {
      if (error.code !== 'ENOENT' && error.code !== 'EISDIR') throw error;
    }
  }

  await mapLimit([...plan.outputs.entries()], limit, async ([rel, content]) => {
    const abs = path.join(plan.outDir, rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  });
  await saveManifest(plan.manifestPath, plan.next);

  report.durationMs = Date.now() - started;
  return report;
}
