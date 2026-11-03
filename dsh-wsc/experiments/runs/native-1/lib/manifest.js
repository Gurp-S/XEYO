import { mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';

export const MANIFEST_VERSION = 2;

function isPlainObject(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isStringMap(value) {
  return isPlainObject(value) && Object.values(value).every((v) => typeof v === 'string');
}

/**
 * Load a manifest, returning `null` for anything we cannot trust.
 *
 * A manifest is a cache, never the source of truth, so a damaged one must only
 * cost a rebuild. It must never throw and it must never hand back an entry that
 * is missing fields the planner dereferences.
 */
export async function loadManifest(file) {
  let parsed;
  try {
    parsed = JSON.parse(await readFile(file, 'utf8'));
  } catch {
    return null;
  }
  if (!isPlainObject(parsed) || parsed.version !== MANIFEST_VERSION) return null;

  const files = {};
  if (isPlainObject(parsed.files)) {
    for (const [rel, entry] of Object.entries(parsed.files)) {
      if (!isPlainObject(entry)) continue;
      if (typeof entry.key !== 'string') continue;
      const deps = isStringMap(entry.deps) ? entry.deps : {};
      const out = Array.isArray(entry.out) ? entry.out.filter((p) => typeof p === 'string') : [];
      files[rel] = { key: entry.key, deps, out };
    }
  }
  return { version: MANIFEST_VERSION, files };
}

/**
 * Write a manifest atomically.
 *
 * `rename` within one directory is atomic, so a crash mid-write leaves either
 * the previous manifest or the new one, never a truncated file.
 */
export async function saveManifest(file, manifest) {
  await mkdir(dirname(file), { recursive: true });
  const tmp = join(dirname(file), `.${Date.now()}-${Math.random().toString(16).slice(2)}.tmp`);
  try {
    await writeFile(tmp, JSON.stringify(manifest, null, 2) + '\n');
    await rename(tmp, file);
  } catch (err) {
    await unlink(tmp).catch(() => {});
    throw err;
  }
}
