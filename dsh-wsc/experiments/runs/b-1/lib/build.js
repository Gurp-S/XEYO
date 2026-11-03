import { readdir, readFile, mkdir, unlink } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { readDeps } from './graph.js';
import { fingerprint } from './cache.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';
import { writeFileAtomic, removeOrphanTemps, pruneEmptyDirs } from './fsutil.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>        source directory (default: src)
  --out <dir>        output directory (default: out)
  --manifest <file>  build manifest path (default: build-manifest.json)
  --dry-run          report the plan without writing anything
  --json             print a machine-readable report
  --help, -h         show this help
`;

export function parseArgs(argv) {
  const opts = {
    src: DEFAULT_SRC,
    out: DEFAULT_OUT,
    manifest: DEFAULT_MANIFEST,
    dryRun: false,
    json: false,
    help: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--src') opts.src = argv[(index += 1)];
    else if (arg === '--out') opts.out = argv[(index += 1)];
    else if (arg === '--manifest') opts.manifest = argv[(index += 1)];
    else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  for (const key of ['src', 'out', 'manifest']) {
    if (!opts[key]) throw new Error(`--${key} needs a value`);
  }
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

function sha(input) {
  return createHash('sha1').update(input).digest('hex');
}

function resolveDep(rel, spec) {
  if (/^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(spec)) return null;
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec));
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${sha(bytes).slice(0, 8)}${ext}`;
}

const URL_RE = /url\(\s*(['"]?)([^'")]+)\1\s*\)/g;

function renderJs(text) {
  return `${text.trimEnd()}\n//# build ${sha(text).slice(0, 8)}\n`;
}

function renderJson(text, rel, srcDir, sourceBytes) {
  const own = JSON.parse(text);
  let merged = own;
  if (own && typeof own.extends === 'string') {
    const relBase = resolveDep(rel, own.extends);
    const baseBytes = relBase == null ? undefined : sourceBytes.get(relBase);
    if (baseBytes === undefined) throw new Error(`${rel}: cannot resolve extends target ${own.extends}`);
    const base = JSON.parse(baseBytes.toString('utf8'));
    const { extends: dropped, ...rest } = own;
    merged = { ...base, ...rest };
  }
  return `${JSON.stringify(merged, null, 2)}\n`;
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const sources = await walk(srcDir, srcDir);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  // Read every source once; fingerprints come from the bytes themselves so a
  // same-size rewrite or a touch with an unchanged mtime still invalidates.
  const sourceBytes = new Map();
  for (const rel of sources) sourceBytes.set(rel, await readFile(path.join(srcDir, rel)));
  const stats = new Map(sources.map((rel) => [rel, fingerprint(sourceBytes.get(rel))]));

  const deps = new Map();
  for (const rel of sources) {
    const resolved = {};
    for (const spec of await readDeps(path.join(srcDir, rel), path.posix.extname(rel))) {
      const target = resolveDep(rel, spec);
      if (!target) continue;
      resolved[target] = stats.get(target) ?? 'missing';
    }
    deps.set(rel, resolved);
  }

  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = {};

  for (const rel of sources) {
    const key = stats.get(rel);
    const resolved = deps.get(rel) ?? {};
    const prev = manifest.files[rel];
    const stale = Object.entries(resolved).some(([dep, depKey]) => (prev?.deps ?? {})[dep] !== depKey);
    const dirty = !prev || prev.key !== key || stale;
    const ext = path.posix.extname(rel);
    const outNames = [rel];
    if (!dirty) {
      skipped.push(rel);
      nextFiles[rel] = { key, deps: resolved, out: prev.out ?? outNames };
      continue;
    }
    built.push(rel);
    const bytes = sourceBytes.get(rel);
    if (ext === '.js' || ext === '.mjs') {
      outputs.set(rel, renderJs(bytes.toString('utf8')));
    } else if (ext === '.css') {
      const text = bytes.toString('utf8');
      const names = new Map();
      for (const match of text.matchAll(URL_RE)) {
        const target = match[2];
        if (names.has(target)) continue;
        const relTarget = resolveDep(rel, target);
        const targetBytes = relTarget == null ? undefined : sourceBytes.get(relTarget);
        if (targetBytes === undefined) {
          // Not a source we can hash: leave that url() exactly as written.
          names.set(target, null);
          continue;
        }
        const name = hashedName(relTarget, targetBytes);
        names.set(target, name);
        if (!outputs.has(name)) outputs.set(name, targetBytes);
        if (!outNames.includes(name)) outNames.push(name);
      }
      outputs.set(
        rel,
        text.replace(URL_RE, (whole, quote, target) => {
          const name = names.get(target);
          return name == null ? whole : `url(${name})`;
        }),
      );
    } else if (ext === '.json') {
      outputs.set(rel, renderJson(bytes.toString('utf8'), rel, srcDir, sourceBytes));
    } else {
      outputs.set(rel, bytes);
    }
    nextFiles[rel] = { key, deps: resolved, out: outNames };
  }

  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles));

  // Outputs that a previous build wrote but this plan no longer claims: deleted
  // sources and the old hashed asset names of a rebuilt CSS file.
  const keep = new Set();
  for (const [rel, entry] of Object.entries(nextFiles)) {
    keep.add(rel);
    for (const name of entry.out) keep.add(name);
  }
  const orphans = [];
  for (const entry of Object.values(manifest.files)) {
    for (const name of entry.out) if (!keep.has(name) && !orphans.includes(name)) orphans.push(name);
  }

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    removed,
    orphans,
    built,
    skipped,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

function report(plan, started, dryRun) {
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
  const plan = await planBuild(opts, cwd);
  if (opts.dryRun) return report(plan, started, true);

  await mkdir(plan.outDir, { recursive: true });
  await removeOrphanTemps(plan.outDir);
  for (const [rel, content] of plan.outputs) {
    await writeFileAtomic(path.join(plan.outDir, rel), content);
  }

  const touchedDirs = [];
  for (const rel of plan.orphans) {
    const abs = path.join(plan.outDir, rel);
    try {
      await unlink(abs);
      touchedDirs.push(path.dirname(abs));
    } catch {
      // Already gone, or never written because an earlier build was interrupted.
    }
  }
  await pruneEmptyDirs(plan.outDir, touchedDirs);

  // The manifest is the commit record of this build: it is written only after
  // every output it mentions is on disk.
  await saveManifest(plan.manifestPath, plan.next);
  return report(plan, started, false);
}
