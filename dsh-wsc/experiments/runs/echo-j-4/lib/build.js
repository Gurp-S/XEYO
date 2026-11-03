import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { readDeps, URL_RE } from './graph.js';
import { fingerprint, hashBytes } from './cache.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';
import { outputsPresent, writeOutputs, removeOutputs } from './outputs.js';
import { mapLimit, normalizeLimit } from './pool.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';
export const DEFAULT_CONCURRENCY = 4;

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>        source directory (default: src)
  --out <dir>        output directory (default: out)
  --manifest <file>  build manifest path (default: build-manifest.json)
  --dry-run          report the plan without writing anything
  --json             print a machine-readable report
  --concurrency <n>  build at most n files at once (default: 4)
  --watch            keep running and rebuild when a source changes
  --help, -h         show this help
`;

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
    if (arg === '--src') opts.src = argv[(index += 1)];
    else if (arg === '--out') opts.out = argv[(index += 1)];
    else if (arg === '--manifest') opts.manifest = argv[(index += 1)];
    else if (arg === '--concurrency') opts.concurrency = argv[(index += 1)];
    else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--watch') opts.watch = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  for (const key of ['src', 'out', 'manifest']) {
    if (!opts[key]) throw new Error(`--${key} needs a value`);
  }
  const concurrency = Number(opts.concurrency);
  if (!Number.isInteger(concurrency) || concurrency < 1) {
    throw new Error(`--concurrency needs a positive integer`);
  }
  opts.concurrency = concurrency;
  return opts;
}

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
  return `${base}.${hashBytes(bytes).slice(0, 8)}${ext}`;
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const limit = normalizeLimit(opts.concurrency ?? DEFAULT_CONCURRENCY);
  const sources = await walk(srcDir, srcDir);
  const manifest =
    (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: Object.create(null) };

  const keys = new Map();
  await mapLimit(sources, limit, async (rel) => {
    keys.set(rel, await fingerprint(path.join(srcDir, rel)));
  });

  const deps = new Map();
  await mapLimit(sources, limit, async (rel) => {
    const abs = path.join(srcDir, rel);
    const resolved = Object.create(null);
    for (const spec of await readDeps(abs, path.posix.extname(rel))) {
      const target = resolveDep(rel, spec);
      if (target) resolved[target] = keys.get(target) ?? 'missing';
    }
    deps.set(rel, resolved);
  });

  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = Object.create(null);
  const stale = [];

  await mapLimit(sources, limit, async (rel) => {
    const key = keys.get(rel);
    const resolved = deps.get(rel) ?? {};
    const prev = manifest.files[rel];
    const depsChanged = Object.entries(resolved).some(([dep, depKey]) => (prev?.deps ?? {})[dep] !== depKey);
    // A recorded output that no longer exists is as good as no record at all: the
    // manifest must heal itself instead of vouching for files that are gone.
    const dirty =
      !prev || prev.key !== key || depsChanged || !(await outputsPresent(outDir, prev.out));
    if (!dirty) {
      skipped.push(rel);
      nextFiles[rel] = { key, deps: resolved, out: prev.out };
      return;
    }
    const ext = path.posix.extname(rel);
    const outNames = [rel];
    const abs = path.join(srcDir, rel);
    if (ext === '.js' || ext === '.mjs') {
      const text = await readFile(abs, 'utf8');
      outputs.set(rel, `${text.trimEnd()}\n//# build ${hashBytes(text).slice(0, 8)}\n`);
    } else if (ext === '.css') {
      const text = await readFile(abs, 'utf8');
      const names = new Map();
      for (const match of text.matchAll(URL_RE)) {
        const target = match[1];
        const relTarget = resolveDep(rel, target);
        const bytes = await readFile(path.join(srcDir, relTarget));
        const base = hashedName(relTarget, bytes);
        // The asset is emitted beside the stylesheet and the url stays a bare
        // hashed name, so the relative reference resolves in the output tree
        // no matter how deep the stylesheet sits.
        const dir = path.posix.dirname(rel);
        const name = dir === '.' ? base : `${dir}/${base}`;
        names.set(target, base);
        outputs.set(name, bytes);
        outNames.push(name);
      }
      outputs.set(rel, text.replace(URL_RE, (whole, target) => `url(${names.get(target) ?? target})`));
    } else if (ext === '.json') {
      const own = JSON.parse(await readFile(abs, 'utf8'));
      let merged = own;
      if (own && typeof own.extends === 'string') {
        const relBase = resolveDep(rel, own.extends);
        const base = JSON.parse(await readFile(path.join(srcDir, relBase), 'utf8'));
        const { extends: dropped, ...rest } = own;
        merged = { ...base, ...rest };
      }
      outputs.set(rel, `${JSON.stringify(merged, null, 2)}\n`);
    } else {
      outputs.set(rel, await readFile(abs));
    }
    built.push(rel);
    nextFiles[rel] = { key, deps: resolved, out: outNames };
    stale.push(...(prev?.out ?? []));
  });

  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles));
  for (const rel of removed) stale.push(...(manifest.files[rel].out ?? []));

  // Only names that nothing produces any more may go: a stylesheet's hashed asset
  // can be shared with another stylesheet.
  const produced = new Set();
  for (const entry of Object.values(nextFiles)) for (const name of entry.out) produced.add(name);
  const staleOutputs = [...new Set(stale)].filter((name) => !produced.has(name)).sort();

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    concurrency: limit,
    outputs,
    removed,
    staleOutputs,
    built: built.sort(),
    skipped: skipped.sort(),
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const plan = await planBuild(opts, cwd);
  if (opts.dryRun) {
    return {
      built: plan.built,
      skipped: plan.skipped,
      removed: plan.removed,
      staleOutputs: plan.staleOutputs,
      outputs: plan.outputs.size,
      concurrency: plan.concurrency,
      dryRun: true,
      durationMs: Date.now() - started,
    };
  }
  await mkdirOut(plan.outDir);
  await writeOutputs(plan.outDir, plan.outputs, plan.concurrency);
  await removeOutputs(plan.outDir, plan.staleOutputs);
  // The manifest goes last: an interruption leaves the previous manifest in place,
  // and the next build re-derives everything the interrupted one did not record.
  await saveManifest(plan.manifestPath, plan.next);
  return {
    built: plan.built,
    skipped: plan.skipped,
    removed: plan.removed,
    staleOutputs: plan.staleOutputs,
    outputs: plan.outputs.size,
    concurrency: plan.concurrency,
    dryRun: false,
    durationMs: Date.now() - started,
  };
}

async function mkdirOut(dir) {
  const { mkdir } = await import('node:fs/promises');
  await mkdir(dir, { recursive: true });
}
