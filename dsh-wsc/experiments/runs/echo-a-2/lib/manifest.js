import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

export const MANIFEST_VERSION = 2;

function isEntry(entry) {
  return Boolean(
    entry &&
      typeof entry === 'object' &&
      typeof entry.key === 'string' &&
      entry.deps &&
      typeof entry.deps === 'object' &&
      !Array.isArray(entry.deps) &&
      Array.isArray(entry.out) &&
      entry.out.every((name) => typeof name === 'string'),
  );
}

export async function loadManifest(file) {
  let parsed;
  try {
    parsed = JSON.parse(await readFile(file, 'utf8'));
  } catch {
    return null;
  }
  if (!parsed || parsed.version !== MANIFEST_VERSION) return null;
  if (!parsed.files || typeof parsed.files !== 'object' || Array.isArray(parsed.files)) return null;
  const files = {};
  for (const [rel, entry] of Object.entries(parsed.files)) {
    if (isEntry(entry)) files[rel] = { key: entry.key, deps: entry.deps, out: entry.out };
  }
  return { version: MANIFEST_VERSION, files };
}

// Written to a sibling temp file and renamed into place, so an interrupted
// build can only ever leave the previous manifest or the complete new one.
export async function saveManifest(file, manifest) {
  await mkdir(path.dirname(file), { recursive: true });
  const temp = `${file}.${process.pid}.${Date.now().toString(36)}.tmp`;
  try {
    await writeFile(temp, `${JSON.stringify(manifest, null, 2)}\n`);
    await rename(temp, file);
  } finally {
    await rm(temp, { force: true });
  }
}
