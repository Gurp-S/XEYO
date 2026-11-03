import { readFile } from 'node:fs/promises';
import { writeFileAtomic } from './fsx.js';

export const MANIFEST_VERSION = 2;

// A manifest that cannot be read back is treated as absent: the next build
// then rebuilds from scratch instead of crashing on a half-written file.
export async function loadManifest(file) {
  try {
    const parsed = JSON.parse(await readFile(file, 'utf8'));
    return parsed && parsed.version === MANIFEST_VERSION ? parsed : null;
  } catch {
    return null;
  }
}

// The manifest is the record that lets a build skip work, so it is written
// through the same temporary-sibling-and-rename path as every other output.
export async function saveManifest(file, manifest) {
  await writeFileAtomic(file, `${JSON.stringify(manifest, null, 2)}\n`);
}
