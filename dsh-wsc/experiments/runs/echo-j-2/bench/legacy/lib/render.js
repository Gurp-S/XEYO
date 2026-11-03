import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { sha } from './fingerprint.js';
import { resolveDep } from './deps.js';

const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${sha(bytes).slice(0, 8)}${ext}`;
}

function assetPath(rel, name) {
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), name));
}

async function readBytesOrNull(abs) {
  try {
    return await readFile(abs);
  } catch (error) {
    if (error && error.code === 'ENOENT') return null;
    throw error;
  }
}

async function mergeJson(abs, rel, srcDir) {
  const own = JSON.parse(await readFile(abs, 'utf8'));
  if (!own || typeof own !== 'object' || typeof own.extends !== 'string') return own;
  const relBase = resolveDep(rel, own.extends);
  const base = relBase ? await mergeJson(path.join(srcDir, relBase), relBase, srcDir) : {};
  const { extends: _dropped, ...rest } = own;
  return { ...base, ...rest };
}

// Renders one source file. Returns the primary output text/bytes plus any
// content-hashed assets that must be emitted alongside it.
export async function renderSource({ abs, rel, srcDir }) {
  const ext = path.posix.extname(rel);
  const assets = new Map();
  if (ext === '.js' || ext === '.mjs') {
    const text = await readFile(abs, 'utf8');
    return { content: `${text.trimEnd()}\n//# build ${sha(text).slice(0, 8)}\n`, assets };
  }
  if (ext === '.css') {
    const text = await readFile(abs, 'utf8');
    const names = new Map();
    for (const match of text.matchAll(URL_RE)) {
      const target = match[1];
      if (names.has(target)) continue;
      const relTarget = resolveDep(rel, target);
      if (!relTarget) continue;
      const bytes = await readBytesOrNull(path.join(srcDir, relTarget));
      // An unresolvable target stays as written; the dependency is recorded as
      // missing so the stylesheet rebuilds once the asset appears.
      if (!bytes) continue;
      const name = hashedName(relTarget, bytes);
      names.set(target, name);
      assets.set(assetPath(rel, name), bytes);
    }
    const content = text.replace(URL_RE, (whole, target) => {
      const name = names.get(target);
      return name ? `url(${name})` : whole;
    });
    return { content, assets };
  }
  if (ext === '.json') {
    return { content: `${JSON.stringify(await mergeJson(abs, rel, srcDir), null, 2)}\n`, assets };
  }
  return { content: await readFile(abs), assets };
}
