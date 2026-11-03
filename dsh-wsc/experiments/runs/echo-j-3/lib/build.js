import { readFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { URL_RE, directSpecifiers, resolveDep } from './deps.js';
import { fingerprint, sha1hex } from './fingerprint.js';
import { resolveJsonObject } from './json-extends.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';
import { DEFAULT_CONCURRENCY, normalizeConcurrency, runPool } from './pool.js';
import { pathExists, pruneEmptyDirs, removeFile, walkFiles, writeFileAtomic } from './fsx.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>          source directory (default: src)
  --out <dir>          output directory (default: out)
  --manifest <file>    build manifest path (default: build-manifest.json)
  --concurrency <n>    build at most n files at once (default: ${DEFAULT_CONCURRENCY})
  --watch              keep running and rebuild when a source file changes
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
    else if (arg === '--concurrency') {
      const value = argv[(index += 1)];
      if (value === undefined) throw new Error('--concurrency needs a value');
      opts.concurrency = normalizeConcurrency(value);
    } else if (arg === '--watch') opts.watch = true;
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

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${sha1hex(bytes).slice(0, 8)}${ext}`;
}

function textOf(bytes) {
  return bytes.toString('utf8');
}

// Every file whose bytes reach this source's output, with the fingerprint the
// manifest records for it. A dependency that no longer exists is recorded as
// `missing`, so its return also rebuilds the dependent file.
async function collectDeps(rel, bytes, srcDir, known) {
  const ext = path.posix.extname(rel);
  let specifiers;
  if (ext === '.json') {
    try {
      specifiers = (await resolveJsonObject(rel, (target) => readFile(path.join(srcDir, target), 'utf8'))).bases;
    } catch {
      // A broken chain is reported when the file is rendered; for staleness
      // tracking the direct specifier is the best information available.
      specifiers = directSpecifiers(rel, textOf(bytes));
    }
  } else {
    specifiers = directSpecifiers(rel, textOf(bytes));
  }
  const resolved = {};
  for (const spec of specifiers) {
    const target = resolveDep(rel, spec);
    if (target) resolved[target] = null;
  }
  for (const target of Object.keys(resolved)) resolved[target] = known.get(target) ?? 'missing';
  return resolved;
}

async function renderFile(rel, bytes, srcDir) {
  const ext = path.posix.extname(rel);
  if (ext === '.js' || ext === '.mjs') {
    const text = textOf(bytes);
    return { content: `${text.trimEnd()}\n//# build ${sha1hex(bytes).slice(0, 8)}\n`, emitted: [] };
  }
  if (ext === '.css') {
    const text = textOf(bytes);
    const dir = path.posix.dirname(rel);
    const names = new Map();
    const emitted = [];
    for (const match of text.matchAll(URL_RE)) {
      const target = match[1];
      const targetRel = resolveDep(rel, target);
      if (!targetRel || names.has(target)) continue;
      let targetBytes;
      try {
        targetBytes = await readFile(path.join(srcDir, targetRel));
      } catch {
        // The asset is gone: the stylesheet is still emitted, with the url left
        // exactly as the source wrote it.
        continue;
      }
      const name = hashedName(targetRel, targetBytes);
      names.set(target, name);
      emitted.push([dir === '.' ? name : `${dir}/${name}`, targetBytes]);
    }
    const content = text.replace(URL_RE, (whole, target) =>
      names.has(target) ? `url(${names.get(target)})` : whole,
    );
    return { content, emitted };
  }
  if (ext === '.json') {
    const { value } = await resolveJsonObject(rel, (target) => readFile(path.join(srcDir, target), 'utf8'));
    return { content: `${JSON.stringify(value, null, 2)}\n`, emitted: [] };
  }
  return { content: bytes, emitted: [] };
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const limit = normalizeConcurrency(opts.concurrency);
  const sources = await walkFiles(srcDir);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  // A source's identity is its bytes, never its stat data: a rewrite that keeps
  // the mtime is still a different source.
  const entries = await runPool(sources, limit, async (rel) => {
    const bytes = await readFile(path.join(srcDir, rel));
    return { rel, bytes, key: fingerprint(bytes) };
  });
  const known = new Map(entries.map((entry) => [entry.rel, entry.key]));

  const deps = new Map();
  await runPool(entries, limit, async (entry) => {
    deps.set(entry.rel, await collectDeps(entry.rel, entry.bytes, srcDir, known));
  });

  const results = await runPool(entries, limit, async (entry) => {
    const { rel, bytes, key } = entry;
    const resolved = deps.get(rel) ?? {};
    const prev = manifest.files[rel];
    const prevOut = prev?.out ?? [];
    const stale =
      !prev ||
      prev.key !== key ||
      Object.entries(resolved).some(([dep, depKey]) => (prev.deps ?? {})[dep] !== depKey);
    // A manifest that names outputs which are no longer on disk never heals
    // unless the missing output itself forces a rebuild.
    const gone =
      prevOut.length === 0 ||
      (await Promise.all(prevOut.map((out) => pathExists(path.join(outDir, out))))).some((ok) => !ok);
    if (!stale && !gone) return { rel, key, resolved, skipped: true, outNames: prevOut };
    const rendered = await renderFile(rel, bytes, srcDir);
    return { rel, key, resolved, skipped: false, outNames: [rel, ...rendered.emitted.map(([name]) => name)], rendered };
  });

  const outputs = new Map();
  const built = [];
  const skipped = [];
  const deletions = [];
  const nextFiles = {};

  for (const result of results) {
    const { rel, key, resolved } = result;
    nextFiles[rel] = { key, deps: resolved, out: result.outNames };
    if (result.skipped) {
      skipped.push(rel);
      continue;
    }
    built.push(rel);
    const previous = manifest.files[rel]?.out ?? [];
    for (const out of previous) {
      if (!result.outNames.includes(out)) deletions.push(out);
    }
    for (const [name, content] of result.rendered.emitted) outputs.set(name, content);
    outputs.set(rel, result.rendered.content);
  }

  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles));
  for (const rel of removed) {
    for (const out of manifest.files[rel].out ?? []) deletions.push(out);
  }

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    removed,
    deletions,
    built,
    skipped,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

function summarize(plan, dryRun, started) {
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
  if (opts.dryRun) return summarize(plan, true, started);

  await mkdir(plan.outDir, { recursive: true });
  for (const [rel, content] of plan.outputs) {
    await writeFileAtomic(path.join(plan.outDir, rel), content);
  }
  for (const rel of plan.deletions) {
    const abs = path.join(plan.outDir, rel);
    await removeFile(abs);
    await pruneEmptyDirs(path.dirname(abs), plan.outDir);
  }
  // The manifest is written last and atomically: an interrupted build leaves
  // either the previous manifest or the new one, and redoing the work is safe.
  await saveManifest(plan.manifestPath, plan.next);
  return summarize(plan, false, started);
}
