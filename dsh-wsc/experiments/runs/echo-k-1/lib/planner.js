import { mkdir, readdir, rm, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { readSource } from './fingerprint.js';
import { formatFor, isTextFormat } from './formats.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';
export const DEFAULT_CONCURRENCY = 4;

export async function walkTree(dir, base) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walkTree(abs, base)));
    else if (entry.isFile()) files.push(path.relative(base, abs).split(path.sep).join('/'));
  }
  return files.sort();
}

// Only a relative specifier can name another source: a scheme (http:, data:)
// or an absolute path points outside the tree, so it has no fingerprint and is
// left exactly as written.
export function resolveDep(rel, spec) {
  if (/^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(spec)) return null;
  const target = path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec));
  if (target === '.' || target === '..' || target.startsWith('../')) return null;
  return target;
}

async function exists(abs) {
  try {
    await stat(abs);
    return true;
  } catch {
    return false;
  }
}

async function allExist(dir, rels) {
  for (const rel of rels) {
    if (!(await exists(path.join(dir, rel)))) return false;
  }
  return true;
}

// A build is planned from two facts only: the current bytes under --src and the
// outputs the previous manifest claims to own. Nothing else on disk is trusted,
// and no file is read twice: the bytes that produce the fingerprint are the
// bytes that produce the output.
export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const sources = await walkTree(srcDir, srcDir);
  const previous = await loadManifest(manifestPath);
  const prevFiles = previous?.files ?? {};

  const records = new Map();
  for (const rel of sources) {
    const ext = path.posix.extname(rel);
    const { bytes, key } = await readSource(path.join(srcDir, rel));
    records.set(rel, {
      rel,
      ext,
      bytes,
      key,
      text: isTextFormat(ext) ? bytes.toString('utf8') : '',
      deps: {},
    });
  }

  const keyOf = (rel) => records.get(rel)?.key ?? 'missing';
  const source = (rel) => records.get(rel) ?? null;

  for (const record of records.values()) {
    for (const spec of formatFor(record.ext).specifiers(record.text)) {
      const target = resolveDep(record.rel, spec);
      if (target) record.deps[target] = keyOf(target);
    }
  }

  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = {};

  for (const record of records.values()) {
    const prev = prevFiles[record.rel];
    const prevOut = Array.isArray(prev?.out) ? prev.out : null;
    const recordedDeps = prev?.deps ?? {};
    const depsChanged = Object.keys(record.deps).some((dep) => recordedDeps[dep] !== record.deps[dep]);
    // An entry whose outputs are gone is not a valid cache hit: the manifest
    // describes the tree, it does not replace it.
    const intact = prevOut ? await allExist(outDir, prevOut) : false;
    if (prev && prev.key === record.key && !depsChanged && intact) {
      skipped.push(record.rel);
      nextFiles[record.rel] = { key: record.key, deps: record.deps, out: prevOut };
      continue;
    }
    built.push(record.rel);
    const emitted = formatFor(record.ext).emit({
      rel: record.rel,
      text: record.text,
      bytes: record.bytes,
      resolve: (spec) => resolveDep(record.rel, spec),
      source,
    });
    for (const [name, contents] of emitted.contents) outputs.set(name, contents);
    nextFiles[record.rel] = { key: record.key, deps: record.deps, out: emitted.out };
  }

  // Outputs are owned by the manifest. Anything the previous manifest owned and
  // this plan does not is deleted, which covers deleted sources and hashed
  // assets whose name changed, without ever touching a file the build did not
  // create.
  const previousOutputs = new Set();
  for (const entry of Object.values(prevFiles)) {
    for (const rel of entry?.out ?? []) previousOutputs.add(rel);
  }
  const nextOutputs = new Set();
  for (const entry of Object.values(nextFiles)) {
    for (const rel of entry.out) nextOutputs.add(rel);
  }

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    removed: Object.keys(prevFiles).filter((rel) => !(rel in nextFiles)).sort(),
    removedOutputs: [...previousOutputs].filter((rel) => !nextOutputs.has(rel)).sort(),
    built,
    skipped,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

async function writeAll(outDir, outputs, concurrency) {
  const entries = [...outputs];
  let cursor = 0;
  const worker = async () => {
    for (;;) {
      const index = cursor;
      cursor += 1;
      if (index >= entries.length) return;
      const [rel, contents] = entries[index];
      const abs = path.join(outDir, rel);
      await mkdir(path.dirname(abs), { recursive: true });
      await writeFile(abs, contents);
    }
  };
  const width = Math.max(1, Math.min(concurrency, entries.length));
  await Promise.all(Array.from({ length: width }, () => worker()));
}

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const plan = await planBuild(opts, cwd);
  const report = {
    built: plan.built,
    skipped: plan.skipped,
    removed: plan.removed,
    removedOutputs: plan.removedOutputs,
    outputs: plan.outputs.size,
    dryRun: Boolean(opts.dryRun),
    durationMs: 0,
  };
  if (opts.dryRun) {
    report.durationMs = Date.now() - started;
    return report;
  }
  await mkdir(plan.outDir, { recursive: true });
  await writeAll(plan.outDir, plan.outputs, opts.concurrency ?? DEFAULT_CONCURRENCY);
  for (const rel of plan.removedOutputs) {
    await rm(path.join(plan.outDir, rel), { force: true });
  }
  // The manifest is written last and atomically: a build that dies halfway
  // leaves the previous manifest, so the next build simply rebuilds.
  await saveManifest(plan.manifestPath, plan.next);
  report.durationMs = Date.now() - started;
  return report;
}
