import { readFile } from 'node:fs/promises';
import { writeFileAtomic } from './atomic.js';

export const MANIFEST_VERSION = 2;

function isManifest(value) {
  return Boolean(
    value &&
      typeof value === 'object' &&
      !Array.isArray(value) &&
      value.version === MANIFEST_VERSION &&
      value.files &&
      typeof value.files === 'object' &&
      !Array.isArray(value.files),
  );
}

/**
 * A missing, truncated, or structurally wrong manifest is not an error: it means
 * "no usable prior state", so the next build simply rebuilds everything.
 */
export async function loadManifest(file) {
  let raw;
  try {
    raw = await readFile(file, 'utf8');
  } catch {
    return null;
  }
  try {
    const parsed = JSON.parse(raw);
    return isManifest(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export async function saveManifest(file, manifest) {
  await writeFileAtomic(file, `${JSON.stringify(manifest, null, 2)}\n`);
}
