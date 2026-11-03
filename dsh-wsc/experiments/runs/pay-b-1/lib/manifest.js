import { readFile } from 'node:fs/promises';
import { writeFileAtomic } from './atomic.js';

export const MANIFEST_VERSION = 2;

export async function loadManifest(file) {
  try {
    const parsed = JSON.parse(await readFile(file, 'utf8'));
    return parsed && parsed.version === MANIFEST_VERSION ? parsed : null;
  } catch {
    return null;
  }
}

export async function saveManifest(file, manifest) {
  await writeFileAtomic(file, `${JSON.stringify(manifest, null, 2)}\n`);
}
