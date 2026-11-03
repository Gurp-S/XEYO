import { mkdir, readdir, readFile, rm, rmdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { readDeps } from './graph.js';
import { fingerprint, shortHash } from './cache.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';
import { DEFAULT_CONCURRENCY, mapPool, normalizeConcurrency } from './pool.js';
import { writeFileAtomic } from './atomic.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';

export { DEFAULT_CONCURRENCY };

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>          source directory (default: src)
  --out <dir>          output directory (default: out)
  --manifest <file>    build manifest path (default: build-manifest.json)
  --concurrency <n>    max files built at once (default: ${DEFAULT_CONCURRENCY})
  --watch              rebuild whenever a source file changes
  --dry-run            report the plan without writing anything
  --json               print a machine-readable report
  --help, -h           show this help
`;

export function parseArgs(argv) {
  const opts = {
    src: DEFAULT_SRC,
    out: DEFAULT_OUT,
    manifest: DEFAULT_MANIFEST,
    concurrency: DEFAULT_CONCURRENCY,
    watch: false,
    dryRun: false,
    json: false,
    help: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--src') opts.src = argv[(index += 1)];
    else if (arg === '--out') opts.out = argv[(index += 1)];
    else if (arg === '--manifest') opts.manifest = argv[(index += 1)];
    else if (arg === '--concurrency') opts.concurrency = normalizeConcurrency(argv[(index += 1)]);
    else if (arg === '--watch') opts.watch = true;
    else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  for (const key of ['src', 'out', 'manifest']) {
    if (!opts[key]) throw new Error(`--${key} needs a value`);
  }
  opts.concurrency = normalizeConcurrency(opts.concurrency);
  return opts;
}

/**
 * Deterministic, sorted walk. Symbolic links are neither files nor directories
 * here, so they are skipped exactly as before.
 */
async function walk(dir, base) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(abs, base)));
    else if (entry.isFile()) files.push(path.relative(base, abs).split(path.sep).join('/'));
  }
  return files.sort();
}

function resolveDep(rel, spec) {
  if (/^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(spec)) return null;
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec));
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${shortHash(bytes)}${ext}`;
}

const URL_RE = /url\(\s*(['"]?)([^'")]+)\1\s*\)/g;

function parseJson(rel, ctx) {
  try {
    return JSON.parse(ctx.buffers.get(rel).toString('utf8'));
  } catch (error) {
    throw new Error(`invalid JSON in ${rel}: ${error instanceof Error ? error.message : String(error)}`);
  }
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Resolve `extends` transitively: the deepest base is merged first and every
 * closer object overrides it. Returns the merged value plus every file read.
 */
async function resolveJson(rel, ctx, seen = new Set()) {
  if (seen.has(rel)) throw new Error(`circular extends: ${[...seen, rel].join(' -> ')}`);
  const own = parseJson(rel, ctx);
  if (!isPlainObject(own) || typeof own.extends !== 'string') {
    return { value: own, deps: [] };
  }
  const { extends: spec, ...rest } = own;
  const baseRel = resolveDep(rel, spec);
  if (!baseRel) return { value: rest, deps: [] };
  if (!ctx.buffers.has(baseRel)) return { value: rest, deps: [baseRel] };
  const base = await resolveJson(baseRel, ctx, new Set([...seen, rel]));
  return {
    value: isPlainObject(base.value) ? { ...base.value, ...rest } : rest,
    deps: [baseRel, ...base.deps],
  };
}

/** Every relative source file that `rel` reads while being transformed. */
async function depsFor(rel, ctx) {
  const ext = path.posix.extname(rel);
  if (ext === '.json') {
    const { deps } = await resolveJson(rel, ctx);
    return deps;
  }
  return readDeps(rel, ctx.buffers.get(rel), ext)
    .map((spec) => resolveDep(rel, spec))
    .filter((target) => target !== null);
}

/** Transform one source into its output files; `files` maps out path -> bytes. */
async function renderSource(rel, ctx) {
  const ext = path.posix.extname(rel);
  const bytes = ctx.buffers.get(rel);
  const files = new Map([[rel, bytes]]);
  if (ext === '.js' || ext === '.mjs') {
    const text = bytes.toString('utf8');
    files.set(rel, Buffer.from(`${text.trimEnd()}\n//# build ${shortHash(bytes)}\n`));
  } else if (ext === '.css') {
    const text = bytes.toString('utf8');
    const names = new Map();
    for (const match of text.matchAll(URL_RE)) {
      const target = match[2].trim();
      const relTarget = resolveDep(rel, target);
      if (!relTarget || !ctx.buffers.has(relTarget)) continue;
      const name = hashedName(relTarget, ctx.buffers.get(relTarget));
      names.set(target, name);
      files.set(name, ctx.buffers.get(relTarget));
    }
    files.set(
      rel,
      Buffer.from(text.replace(URL_RE, (whole, quote, target) => {
        const name = names.get(target.trim());
        return name ? `url(${name})` : whole;
      })),
    );
  } else if (ext === '.json') {
    const { value } = await resolveJson(rel, ctx);
    files.set(rel, Buffer.from(`${JSON.stringify(value, null, 2)}\n`));
  }
  return files;
}

async function outputExists(outDir, rel) {
  try {
    return (await stat(path.join(outDir, rel))).isFile();
  } catch {
    return false;
  }
}

function depsChanged(prev, resolved) {
  const before = prev?.deps ?? {};
  const beforeKeys = Object.keys(before);
  const afterKeys = Object.keys(resolved);
  if (beforeKeys.length !== afterKeys.length) return true;
  return afterKeys.some((dep) => !Object.hasOwn(before, dep) || before[dep] !== resolved[dep]);
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const concurrency = normalizeConcurrency(opts.concurrency);
  const sources = await walk(srcDir, srcDir);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  const buffers = new Map();
  const keys = new Map();
  await mapPool(sources, concurrency, async (rel) => {
    const bytes = await readFile(path.join(srcDir, rel));
    buffers.set(rel, bytes);
    keys.set(rel, fingerprint(bytes));
  });

  const ctx = { srcDir, outDir, buffers, keys };
  const resolvedDeps = new Map();
  await mapPool(sources, concurrency, async (rel) => {
    const resolved = {};
    for (const dep of await depsFor(rel, ctx)) resolved[dep] = keys.get(dep) ?? 'missing';
    resolvedDeps.set(rel, resolved);
  });

  // Decide staleness first, so the pool never holds more work than it needs.
  const decisions = await mapPool(sources, concurrency, async (rel) => {
    const key = keys.get(rel);
    const deps = resolvedDeps.get(rel) ?? {};
    const prev = manifest.files[rel];
    let dirty = !prev || prev.key !== key || depsChanged(prev, deps);
    if (!dirty) {
      // A manifest that names outputs which no longer exist must heal itself.
      const recorded = Array.isArray(prev.out) ? prev.out : [];
      if (recorded.length === 0) dirty = true;
      for (const out of recorded) {
        if (dirty) break;
        if (!(await outputExists(outDir, out))) dirty = true;
      }
    }
    return { rel, key, deps, prev, dirty };
  });

  const dirty = decisions.filter((decision) => decision.dirty).map((decision) => decision.rel);
  const rendered = new Map(
    await mapPool(dirty, concurrency, async (rel) => [rel, await renderSource(rel, ctx)]),
  );

  const writes = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = {};
  const stale = [];

  for (const { rel, key, deps, prev, dirty: isDirty } of decisions) {
    if (isDirty) {
      const files = rendered.get(rel);
      for (const [name, bytes] of files) writes.set(name, bytes);
      built.push(rel);
      nextFiles[rel] = { key, deps, out: [...files.keys()].sort() };
      for (const out of Array.isArray(prev?.out) ? prev.out : []) stale.push(out);
    } else {
      skipped.push(rel);
      nextFiles[rel] = { key, deps, out: prev.out };
    }
  }

  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles));
  for (const rel of removed) {
    for (const out of Array.isArray(manifest.files[rel]?.out) ? manifest.files[rel].out : []) stale.push(out);
  }

  const desired = new Set();
  for (const entry of Object.values(nextFiles)) {
    for (const out of entry.out ?? []) desired.add(out);
  }
  const deletions = [...new Set(stale)].filter((out) => !desired.has(out)).sort();

  const ordered = new Map([...writes].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)));
  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    concurrency,
    writes: ordered,
    deletions,
    removed,
    built,
    skipped,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

async function pruneEmptyDirs(dir, root) {
  let current = dir;
  while (current.startsWith(root) && current !== root) {
    try {
      if ((await readdir(current)).length > 0) return;
      await rmdir(current);
    } catch {
      return;
    }
    current = path.dirname(current);
  }
}

function report(plan, started, dryRun) {
  return {
    built: plan.built,
    skipped: plan.skipped,
    removed: plan.removed,
    deleted: plan.deletions,
    outputs: plan.writes.size,
    concurrency: plan.concurrency,
    dryRun,
    durationMs: Date.now() - started,
  };
}

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const plan = await planBuild(opts, cwd);
  if (opts.dryRun) return report(plan, started, true);

  await mkdir(plan.outDir, { recursive: true });
  for (const [rel, bytes] of plan.writes) {
    await writeFileAtomic(path.join(plan.outDir, rel), bytes);
  }
  for (const rel of plan.deletions) {
    const abs = path.join(plan.outDir, rel);
    await rm(abs, { force: true });
    await pruneEmptyDirs(path.dirname(abs), plan.outDir);
  }
  // Written last: a crash before this point just rebuilds next time.
  await saveManifest(plan.manifestPath, plan.next);
  return report(plan, started, false);
}
