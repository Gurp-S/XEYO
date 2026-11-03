import { readdir, readFile, stat, mkdir, writeFile, unlink, rmdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { readDeps, URL_RE } from './graph.js';
import { cacheKey } from './cache.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';
import { mapLimit, parseConcurrency } from './limit.js';

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
  --watch            rebuild whenever a source file changes
  --concurrency <n>  build at most n files at once (default: 1)
  --json             print a machine-readable report
  --help, -h         show this help
`;

export function parseArgs(argv) {
  const opts = {
    src: DEFAULT_SRC,
    out: DEFAULT_OUT,
    manifest: DEFAULT_MANIFEST,
    concurrency: 1,
    dryRun: false,
    watch: false,
    json: false,
    help: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--src') opts.src = argv[(index += 1)];
    else if (arg === '--out') opts.out = argv[(index += 1)];
    else if (arg === '--manifest') opts.manifest = argv[(index += 1)];
    else if (arg === '--concurrency') opts.concurrency = parseConcurrency(argv[(index += 1)]);
    else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--watch') opts.watch = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  for (const key of ['src', 'out', 'manifest']) {
    if (!opts[key]) throw new Error(`--${key} needs a value`);
  }
  return opts;
}

async function walk(dir, base, skip) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (skip?.(abs)) continue;
    if (entry.isDirectory()) files.push(...(await walk(abs, base, skip)));
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

function isOutside(parent, child) {
  const relative = path.relative(parent, child);
  return relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative);
}

function resolveOutput(outDir, rel) {
  if (typeof rel !== 'string' || rel === '') return null;
  const abs = path.resolve(outDir, rel);
  if (path.relative(outDir, abs) === '' || isOutside(outDir, abs)) return null;
  return abs;
}

function isInside(parent, child) {
  return path.relative(parent, child) !== '' && !isOutside(parent, child);
}

async function outputsPresent(outDir, entry, rel, ext) {
  if (!entry || !Array.isArray(entry.out) || entry.out.length === 0) return false;
  if (!entry.out.includes(rel)) return false;
  // Only stylesheets emit auxiliary (hashed asset) outputs.
  if (ext !== '.css' && (entry.out.length !== 1 || entry.out[0] !== rel)) return false;
  for (const out of entry.out) {
    const abs = resolveOutput(outDir, out);
    if (abs === null) return false;
    try {
      if (!(await stat(abs)).isFile()) return false;
    } catch {
      return false;
    }
  }
  return true;
}

async function buildFile(srcDir, rel, ext) {
  const abs = path.join(srcDir, rel);
  const output = new Map();
  const outNames = [rel];
  if (ext === '.js' || ext === '.mjs') {
    const text = await readFile(abs, 'utf8');
    output.set(rel, `${text.trimEnd()}\n//# build ${sha(text).slice(0, 8)}\n`);
  } else if (ext === '.css') {
    const text = await readFile(abs, 'utf8');
    const names = new Map();
    const missing = new Set();
    URL_RE.lastIndex = 0;
    for (const match of text.matchAll(URL_RE)) {
      const target = match[1];
      const relTarget = resolveDep(rel, target);
      if (relTarget === null || names.has(target) || missing.has(target)) continue;
      let bytes;
      try {
        bytes = await readFile(path.join(srcDir, relTarget));
      } catch (error) {
        // A deleted target leaves the reference as-is; the old hashed output
        // is no longer claimed and is cleaned up as stale.
        if (error.code === 'ENOENT') {
          missing.add(target);
          continue;
        }
        throw error;
      }
      const name = hashedName(relTarget, bytes);
      // The rewritten url is a bare basename, so the asset must live next to
      // the stylesheet for nested sources too.
      const dir = path.posix.dirname(rel);
      const outRel = dir === '.' ? name : path.posix.join(dir, name);
      names.set(target, name);
      output.set(outRel, bytes);
      if (!outNames.includes(outRel)) outNames.push(outRel);
    }
    URL_RE.lastIndex = 0;
    output.set(rel, text.replace(URL_RE, (whole, target) => `url(${names.get(target) ?? target})`));
  } else if (ext === '.json') {
    const own = JSON.parse(await readFile(abs, 'utf8'));
    let merged = own;
    if (own && typeof own === 'object' && !Array.isArray(own) && typeof own.extends === 'string') {
      const relBase = resolveDep(rel, own.extends);
      const { extends: dropped, ...rest } = own;
      let base;
      if (relBase !== null) {
        try {
          base = JSON.parse(await readFile(path.join(srcDir, relBase), 'utf8'));
        } catch (error) {
          if (error.code !== 'ENOENT') throw error;
        }
      }
      merged = base === undefined ? rest : { ...base, ...rest };
    }
    output.set(rel, `${JSON.stringify(merged, null, 2)}\n`);
  } else {
    output.set(rel, await readFile(abs));
  }
  return { output, outNames };
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const concurrency = opts.concurrency ?? 1;
  // Never treat our own outputs or manifest as sources when they live under
  // --src; otherwise watch mode would feed the build back into itself.
  const manifestTmpPrefix = `.${path.basename(manifestPath)}.`;
  const outInsideSrc = outDir !== srcDir && isInside(srcDir, outDir);
  const skip = (abs) => {
    if (abs === manifestPath) return true;
    const base = path.basename(abs);
    if (base.startsWith(manifestTmpPrefix) && base.endsWith('.tmp')) return true;
    if (!outInsideSrc) return false;
    return abs === outDir || isInside(outDir, abs);
  };
  const sources = await walk(srcDir, srcDir, skip);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  // Fingerprint every source by content. Dependencies are collected from the
  // same bytes so JavaScript imports, CSS url() targets, and JSON extends are
  // all represented in the manifest.
  const infos = await mapLimit(sources, concurrency, async (rel) => {
    const abs = path.join(srcDir, rel);
    const ext = path.posix.extname(rel);
    const bytes = await readFile(abs);
    return { rel, ext, key: cacheKey(bytes), specifiers: await readDeps(abs, ext, bytes) };
  });

  const keys = new Map();
  for (const info of infos) keys.set(info.rel, info.key);

  // A dependency may point outside --src (for example "../shared/base.json").
  // Fingerprint whatever the build can actually read, so changes there still
  // invalidate the dependent file.
  const dependencyKeys = new Map(keys);
  const externalTargets = new Set();
  for (const info of infos) {
    for (const spec of info.specifiers) {
      const target = resolveDep(info.rel, spec);
      if (target !== null && !dependencyKeys.has(target)) externalTargets.add(target);
    }
  }
  await mapLimit([...externalTargets], concurrency, async (target) => {
    try {
      dependencyKeys.set(target, cacheKey(await readFile(path.join(srcDir, target))));
    } catch {
      dependencyKeys.set(target, 'missing');
    }
  });

  const deps = new Map();
  for (const info of infos) {
    const resolved = new Map();
    for (const spec of info.specifiers) {
      const target = resolveDep(info.rel, spec);
      if (target !== null) resolved.set(target, dependencyKeys.get(target) ?? 'missing');
    }
    deps.set(info.rel, Object.fromEntries(resolved));
  }

  const results = await mapLimit(infos, concurrency, async (info) => {
    const { rel, ext, key } = info;
    const resolved = deps.get(rel) ?? {};
    const prev = Object.hasOwn(manifest.files, rel) ? manifest.files[rel] : undefined;
    const stale = Object.entries(resolved).some(
      ([dep, depKey]) => (prev?.deps ?? {})[dep] !== depKey,
    );
    let dirty = !prev || prev.key !== key || stale;
    // A manifest entry is not proof that its output still exists: heal missing
    // outputs even when the source itself is untouched.
    if (!dirty && !(await outputsPresent(outDir, prev, rel, ext))) dirty = true;
    if (!dirty) return { rel, dirty: false, out: prev.out, outputs: null };
    const { output, outNames } = await buildFile(srcDir, rel, ext);
    return { rel, dirty: true, out: outNames, outputs: output };
  });

  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextEntries = [];
  for (const result of results) {
    if (result.dirty) {
      built.push(result.rel);
      for (const [name, content] of result.outputs) outputs.set(name, content);
    } else {
      skipped.push(result.rel);
    }
    nextEntries.push([
      result.rel,
      {
        key: keys.get(result.rel),
        deps: deps.get(result.rel) ?? {},
        out: result.out,
      },
    ]);
  }
  const nextFiles = Object.fromEntries(nextEntries);

  const removed = Object.keys(manifest.files).filter((rel) => !Object.hasOwn(nextFiles, rel));

  // Any output named by the previous manifest but not claimed by the new one
  // is stale (deleted source, or a hashed asset whose content changed).
  const claimed = new Set();
  for (const entry of Object.values(nextFiles)) {
    for (const out of entry.out) if (typeof out === 'string') claimed.add(out);
  }
  const staleOutputs = new Set();
  for (const [rel, entry] of Object.entries(manifest.files)) {
    const previous = Array.isArray(entry?.out) ? entry.out : [rel];
    for (const out of previous) {
      if (typeof out === 'string' && !claimed.has(out)) staleOutputs.add(out);
    }
  }

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    removed,
    staleOutputs,
    built,
    skipped,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

async function pruneEmptyDirs(outDir, rels) {
  const dirs = new Set();
  for (const rel of rels) {
    const abs = resolveOutput(outDir, rel);
    if (abs !== null) dirs.add(path.dirname(abs));
  }
  const depth = (dir) => path.relative(outDir, dir).split(path.sep).length;
  const ordered = [...dirs].sort((a, b) => depth(b) - depth(a));
  for (const dir of ordered) {
    let current = dir;
    while (isInside(outDir, current)) {
      try {
        await rmdir(current);
      } catch {
        break;
      }
      current = path.dirname(current);
    }
  }
}

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const plan = await planBuild(opts, cwd);
  if (opts.dryRun) {
    return {
      built: plan.built,
      skipped: plan.skipped,
      removed: plan.removed,
      outputs: plan.outputs.size,
      dryRun: true,
      durationMs: Date.now() - started,
    };
  }

  const concurrency = opts.concurrency ?? 1;
  await mkdir(plan.outDir, { recursive: true });

  // Remove stale outputs first so a file can be replaced by a directory (or
  // vice versa) without the new write colliding with the old entry.
  const stale = [...plan.staleOutputs];
  await mapLimit(stale, concurrency, async (rel) => {
    const abs = resolveOutput(plan.outDir, rel);
    if (abs === null) return;
    try {
      await unlink(abs);
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  });
  await pruneEmptyDirs(plan.outDir, stale);

  await mapLimit([...plan.outputs], concurrency, async ([rel, content]) => {
    const abs = resolveOutput(plan.outDir, rel);
    if (abs === null) throw new Error(`refusing to write outside output directory: ${rel}`);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  });

  // Save last: if the process dies mid-build the old manifest still describes
  // the old outputs, so the next run rebuilds instead of trusting a lie.
  await saveManifest(plan.manifestPath, plan.next);

  return {
    built: plan.built,
    skipped: plan.skipped,
    removed: plan.removed,
    outputs: plan.outputs.size,
    dryRun: false,
    durationMs: Date.now() - started,
  };
}
