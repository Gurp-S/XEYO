import { readdir, readFile, mkdir, writeFile, unlink, access } from 'node:fs/promises';
import path from 'node:path';
import { collectDeps } from './graph.js';
import { fingerprint } from './cache.js';
import { render, resolveDep } from './render.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';
import { mapLimit } from './limit.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';
export const DEFAULT_CONCURRENCY = 8;

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>          source directory (default: src)
  --out <dir>          output directory (default: out)
  --manifest <file>    build manifest path (default: build-manifest.json)
  --concurrency <n>    files rendered in parallel (default: 8)
  --watch              rebuild on source changes until interrupted
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
    else if (arg === '--concurrency') opts.concurrency = Number(argv[(index += 1)]);
    else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--watch') opts.watch = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  for (const key of ['src', 'out', 'manifest']) {
    if (!opts[key]) throw new Error(`--${key} needs a value`);
  }
  if (!Number.isInteger(opts.concurrency) || opts.concurrency < 1) throw new Error('--concurrency needs a positive integer');
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

async function exists(abs) {
  try {
    await access(abs);
    return true;
  } catch {
    return false;
  }
}

/**
 * Decide what this build must do.
 *
 * A source is dirty when its bytes changed, when any dependency's bytes
 * changed, or when one of its declared outputs is missing from disk. Bytes,
 * not mtimes: a file rewritten with the same size and timestamp still has to
 * invalidate everything derived from it.
 */
export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);

  const sources = await walk(srcDir, srcDir);
  const { manifest, status: manifestStatus } = await loadManifest(manifestPath);

  const bytes = new Map();
  await mapLimit(sources, opts.concurrency ?? DEFAULT_CONCURRENCY, async (rel) => {
    bytes.set(rel, await readFile(path.join(srcDir, rel)));
  });

  const keys = new Map();
  for (const rel of sources) keys.set(rel, fingerprint(bytes.get(rel)));

  const deps = new Map();
  for (const rel of sources) {
    const text = bytes.get(rel).toString('utf8');
    const resolved = {};
    for (const spec of collectDeps(text, path.posix.extname(rel))) {
      const target = resolveDep(rel, spec);
      if (target) resolved[target] = keys.get(target) ?? 'missing';
    }
    deps.set(rel, resolved);
  }

  const readSource = (rel) => bytes.get(rel);
  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = {};

  for (const rel of sources) {
    const key = keys.get(rel);
    const resolved = deps.get(rel) ?? {};
    const prev = manifest.files[rel];
    const prevDeps = prev?.deps ?? null;
    const depsChanged =
      prevDeps === null ||
      Object.keys(prevDeps).length !== Object.keys(resolved).length ||
      Object.entries(resolved).some(([dep, depKey]) => prevDeps[dep] !== depKey);
    const missingOut = prev ? (await mapLimit(prev.out, 4, (name) => exists(path.join(outDir, name)))).some((ok) => !ok) : true;
    const dirty = !prev || prev.key !== key || depsChanged || missingOut;

    if (!dirty) {
      skipped.push(rel);
      nextFiles[rel] = { key, deps: resolved, out: prev.out };
      continue;
    }

    built.push(rel);
    const rendered = render(rel, bytes.get(rel), { readSource });
    for (const [name, content] of rendered.outputs) outputs.set(name, content);
    nextFiles[rel] = { key, deps: resolved, out: rendered.out };
  }

  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles));
  const owned = new Set(Object.values(nextFiles).flatMap((entry) => entry.out));
  const candidates = [
    ...removed.flatMap((rel) => manifest.files[rel].out ?? []),
    ...Object.keys(nextFiles)
      .filter((rel) => manifest.files[rel])
      .flatMap((rel) => (manifest.files[rel].out ?? []).filter((name) => !nextFiles[rel].out.includes(name))),
  ];
  const deleted = [...new Set(candidates)].filter((name) => !owned.has(name)).sort();

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    manifestStatus,
    outputs,
    built,
    skipped,
    removed,
    deleted,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const plan = await planBuild(opts, cwd);
  const report = {
    built: plan.built,
    skipped: plan.skipped,
    removed: plan.removed,
    deleted: plan.deleted,
    outputs: plan.outputs.size,
    manifest: plan.manifestStatus,
    dryRun: Boolean(opts.dryRun),
  };
  if (opts.dryRun) return { ...report, durationMs: Date.now() - started };

  await mkdir(plan.outDir, { recursive: true });
  await mapLimit([...plan.outputs], opts.concurrency ?? DEFAULT_CONCURRENCY, async ([rel, content]) => {
    const abs = path.join(plan.outDir, rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  });
  await mapLimit(plan.deleted, 4, async (rel) => {
    try {
      await unlink(path.join(plan.outDir, rel));
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  });
  // The manifest is a promise about what is on disk, so it is committed last.
  await saveManifest(plan.manifestPath, plan.next);
  return { ...report, durationMs: Date.now() - started };
}
