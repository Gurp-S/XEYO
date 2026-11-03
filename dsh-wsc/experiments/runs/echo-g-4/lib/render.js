import path from 'node:path';
import { fingerprint } from './cache.js';

export const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

/** Targets referenced by `url(...)` in a stylesheet, in source order. */
export function extractUrlTargets(text) {
  return [...text.matchAll(URL_RE)].map((match) => match[1]);
}

export function isExternal(spec) {
  return /^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(spec);
}

/** Resolve a specifier against the referring file, or null when it leaves the tree. */
export function resolveDep(rel, spec) {
  if (isExternal(spec)) return null;
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec));
}

/** Content-addressed name, so an asset's URL changes exactly when its bytes do. */
export function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${fingerprint(bytes).slice(0, 8)}${ext}`;
}

/**
 * Render one source file.
 * Returns `{ outputs, out }` where `outputs` maps output path → bytes and
 * `out` is the complete set of output paths this source owns.
 */
export function render(rel, bytes, { readSource }) {
  const ext = path.posix.extname(rel);
  const text = ext === '.png' || ext === '.jpg' || ext === '.jpeg' || ext === '.gif' || ext === '.webp' ? null : bytes.toString('utf8');

  if (ext === '.js' || ext === '.mjs') {
    const body = text.trimEnd();
    return { outputs: new Map([[rel, `${body}\n//# build ${fingerprint(text).slice(0, 8)}\n`]]), out: [rel] };
  }

  if (ext === '.css') {
    // Rewritten urls are bare names, so each hashed asset lands in the
    // stylesheet's own output directory and resolves from there.
    const dir = path.posix.dirname(rel);
    const assets = new Map();
    const names = new Map();
    for (const target of extractUrlTargets(text)) {
      const relTarget = resolveDep(rel, target);
      if (!relTarget || names.has(target)) continue;
      const assetBytes = readSource(relTarget);
      if (!assetBytes) continue;
      const name = hashedName(relTarget, assetBytes);
      names.set(target, name);
      assets.set(path.posix.join(dir, name), assetBytes);
    }
    const css = text.replace(URL_RE, (whole, target) => `url(${names.get(target) ?? target})`);
    const outputs = new Map([[rel, css], ...assets]);
    return { outputs, out: [rel, ...assets.keys()] };
  }

  if (ext === '.json') {
    const own = JSON.parse(text);
    let merged = own;
    if (own && typeof own === 'object' && !Array.isArray(own) && typeof own.extends === 'string') {
      const relBase = resolveDep(rel, own.extends);
      const baseBytes = relBase ? readSource(relBase) : undefined;
      if (!baseBytes) throw new Error(`${rel}: extends target not found: ${own.extends}`);
      const base = JSON.parse(baseBytes.toString('utf8'));
      const { extends: dropped, ...rest } = own;
      merged = { ...base, ...rest };
    }
    return { outputs: new Map([[rel, `${JSON.stringify(merged, null, 2)}\n`]]), out: [rel] };
  }

  return { outputs: new Map([[rel, bytes]]), out: [rel] };
}
