import { mkdir, open, readFile, rename } from 'node:fs/promises';
import path from 'node:path';

export const MANIFEST_VERSION = 2;

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

// A manifest is trusted only as far as it is well formed: one bad entry must
// not poison the whole file, so malformed entries are dropped (which makes the
// next build treat them as unknown and rebuild).
function validEntry(value) {
  if (!isPlainObject(value) || typeof value.key !== 'string' || value.key === '') return null;
  const deps = {};
  if (isPlainObject(value.deps)) {
    for (const [dep, depKey] of Object.entries(value.deps)) {
      if (typeof depKey === 'string') deps[dep] = depKey;
    }
  }
  const out = Array.isArray(value.out)
    ? value.out.filter((name) => typeof name === 'string' && name !== '')
    : [];
  return { key: value.key, deps, out };
}

export async function loadManifest(file) {
  let parsed;
  try {
    parsed = JSON.parse(await readFile(file, 'utf8'));
  } catch {
    return null;
  }
  if (!isPlainObject(parsed) || parsed.version !== MANIFEST_VERSION || !isPlainObject(parsed.files)) {
    return null;
  }
  const files = {};
  for (const [rel, value] of Object.entries(parsed.files)) {
    const entry = validEntry(value);
    if (entry) files[rel] = entry;
  }
  return { version: MANIFEST_VERSION, files };
}

// Written through a temporary file and renamed into place, so an interrupted
// save leaves either the previous manifest or the new one, never a half-written
// file that the next build cannot parse.
export async function saveManifest(file, manifest) {
  const body = `${JSON.stringify(manifest, null, 2)}\n`;
  const tmp = `${file}.tmp`;
  await mkdir(path.dirname(file), { recursive: true });
  const handle = await open(tmp, 'w');
  try {
    await handle.writeFile(body);
    await handle.sync();
  } finally {
    await handle.close();
  }
  await rename(tmp, file);
}
