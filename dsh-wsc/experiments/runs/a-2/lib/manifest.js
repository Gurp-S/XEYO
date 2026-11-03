import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

export const MANIFEST_VERSION = 2;

// An entry is only trusted when it can drive an incremental build: a key, a
// dependency map and at least one output. Anything else is dropped so the file
// is rebuilt instead of being reported as skipped with nothing on disk.
function sanitize(entry) {
  if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return null;
  if (typeof entry.key !== 'string') return null;
  const deps = {};
  if (entry.deps && typeof entry.deps === 'object' && !Array.isArray(entry.deps)) {
    for (const [dep, value] of Object.entries(entry.deps)) {
      if (typeof value === 'string') deps[dep] = value;
    }
  }
  const out = Array.isArray(entry.out) ? entry.out.filter((name) => typeof name === 'string') : [];
  if (out.length === 0) return null;
  return { key: entry.key, deps, out };
}

export async function loadManifest(file) {
  let parsed;
  try {
    parsed = JSON.parse(await readFile(file, 'utf8'));
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object' || parsed.version !== MANIFEST_VERSION) return null;
  if (!parsed.files || typeof parsed.files !== 'object' || Array.isArray(parsed.files)) return null;
  const files = {};
  for (const [rel, entry] of Object.entries(parsed.files)) {
    const clean = sanitize(entry);
    if (clean) files[rel] = clean;
  }
  return { version: MANIFEST_VERSION, files };
}

// Written to a sibling temp file and renamed into place, so an interrupted build
// leaves either the previous manifest or the new one, never half of either.
export async function saveManifest(file, manifest) {
  await mkdir(path.dirname(file), { recursive: true });
  const temp = `${file}.${process.pid}.${Date.now().toString(36)}.tmp`;
  try {
    await writeFile(temp, `${JSON.stringify(manifest, null, 2)}\n`);
    await rename(temp, file);
  } catch (error) {
    await rm(temp, { force: true });
    throw error;
  }
}
