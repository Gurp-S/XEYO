import { readFile } from 'node:fs/promises';
import { writeFileAtomic } from './atomic.js';

export const MANIFEST_VERSION = 2;

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

// A missing, truncated, foreign-version or shapeless manifest is treated as
// "no manifest" so the next build does a full rebuild instead of crashing.
export async function loadManifest(file) {
  let parsed;
  try {
    parsed = JSON.parse(await readFile(file, 'utf8'));
  } catch {
    return null;
  }
  if (!isPlainObject(parsed) || parsed.version !== MANIFEST_VERSION || !isPlainObject(parsed.files)) return null;
  return parsed;
}

export async function saveManifest(file, manifest) {
  await writeFileAtomic(file, `${JSON.stringify(manifest, null, 2)}\n`);
}
